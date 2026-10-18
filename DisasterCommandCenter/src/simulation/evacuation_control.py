"""Paso 8.13: orquestacion y seguimiento de salidas desde edificios.

Reutiliza IndoorPopulationDistributor e IndoorEvacuationController del Paso 8.12.
No modela incendio, rutas a puntos seguros ni segundos reales de evacuacion.
No modifica las clases previas ni campus.json.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from simulation.indoor_people import IndoorPersonManager
from simulation.indoor_population import IndoorPopulationDistributor, load_population_config
from simulation.indoor_evacuation import IndoorEvacuationController


class EvacuationControlCenter:
    """Controla alarma, pausa, turnos, reinicio y reporte de salida por puertas."""

    def __init__(self, campus_path: str | Path, entrances_path: str | Path,
                 population_path: str | Path):
        self.campus_path = Path(campus_path)
        self.entrances_path = Path(entrances_path)
        self.population_path = Path(population_path)
        self._configure()
        self.reset()

    def _configure(self):
        data = load_population_config(self.population_path)
        self.counts = data['building_counts']
        self.seed = data.get('seed', 2026)
        self.id_prefix = data.get('id_prefix', 'P')

    def reset(self):
        """Recrea la poblacion desde su semilla; no modifica los JSON."""
        manager = IndoorPersonManager.from_json(self.campus_path)
        distributor = IndoorPopulationDistributor(manager, self.entrances_path)
        people = distributor.distribute(self.counts, seed=self.seed,
                                        id_prefix=self.id_prefix)
        self.manager = manager
        self.people = people
        self.origin = {p.person_id: p.building_id for p in people}
        self.buildings = tuple(sorted(set(self.origin.values())))
        self.original_counts = dict(Counter(self.origin.values()))
        self.controller: IndoorEvacuationController | None = None
        self.phase = 'preparado'
        self.first_exit_turn: dict[str, int | None] = {n: None for n in self.buildings}
        self.last_exit_turn: dict[str, int | None] = {n: None for n in self.buildings}
        self.log = [self._sample()]

    def _sample(self) -> dict:
        summary = self.summary()
        return {
            'turno': summary['turnos'],
            'dentro': summary['dentro'],
            'salieron': summary['salieron'],
            'esperando': summary['esperando'],
            'por_edificio': {
                name: {'dentro': data['dentro'], 'salieron': data['salieron']}
                for name, data in summary['por_edificio'].items()
            },
        }

    def start_alarm(self):
        """Activa la alerta de salida en TODOS los edificios configurados."""
        if self.phase != 'preparado':
            raise ValueError('La alarma solo puede iniciarse desde PREPARADO. Usa reset().')
        self.controller = IndoorEvacuationController(self.manager, self.entrances_path)
        self.phase = 'en_curso' if self.controller.inside_count else 'completado'

    def pause(self):
        if self.phase != 'en_curso':
            raise ValueError('Solo se puede pausar una evacuacion en curso.')
        assert self.controller is not None
        self.controller.pause()
        self.phase = 'pausado'

    def resume(self):
        if self.phase != 'pausado':
            raise ValueError('Solo se puede reanudar una evacuacion pausada.')
        assert self.controller is not None
        self.controller.resume()
        self.phase = 'en_curso'

    def toggle_pause(self):
        if self.phase == 'en_curso':
            self.pause()
        elif self.phase == 'pausado':
            self.resume()
        return self.phase

    def step(self, *, manual: bool = False) -> int:
        """Un turno de movimiento; manual permite paso aislado durante PAUSA."""
        if self.phase in ('preparado', 'completado'):
            return 0
        if self.phase == 'pausado' and not manual:
            return 0
        assert self.controller is not None
        if self.phase == 'pausado':
            self.controller.resume()
        try:
            moved = self.controller.step()
        finally:
            if self.phase == 'pausado':
                self.controller.pause()

        turn = self.controller.steps
        for building in self.buildings:
            exits = sum(p.building_id is None and self.origin[p.person_id] == building
                        for p in self.people)
            if exits and self.first_exit_turn[building] is None:
                self.first_exit_turn[building] = turn
            if exits == self.original_counts[building] and self.last_exit_turn[building] is None:
                self.last_exit_turn[building] = turn
        if self.controller.inside_count == 0:
            self.phase = 'completado'
        self.log.append(self._sample())
        return moved

    def summary(self) -> dict:
        current = Counter(p.building_id for p in self.people if p.building_id is not None)
        per_building = {}
        for name in self.buildings:
            initial = self.original_counts[name]
            remaining = current[name]
            per_building[name] = {
                'inicial': initial,
                'dentro': remaining,
                'salieron': initial - remaining,
                'primer_cruce_turno': self.first_exit_turn[name],
                'ultimo_cruce_turno': self.last_exit_turn[name],
            }
        controller = self.controller
        return {
            'fase': self.phase,
            'inicial': len(self.people),
            'dentro': sum(current.values()),
            'salieron': len(self.people)-sum(current.values()),
            'esperando': controller.waiting_last_step if controller else 0,
            'turnos': controller.steps if controller else 0,
            'movimientos': controller.total_moves if controller else 0,
            'por_edificio': per_building,
        }

    def report(self) -> dict:
        return {
            'proyecto': 'Disaster Command Center',
            'paso': '8.13',
            'descripcion': 'Salida desde edificios hasta el exterior de puertas provisionales.',
            'advertencia': ('Los turnos no son segundos reales. Salir del edificio '
                            'no equivale a alcanzar una zona segura.'),
            'mapa': {'ancho': self.manager.width, 'alto': self.manager.height},
            'semilla': self.seed,
            'resumen': self.summary(),
            'historial': self.log,
        }

    def save_report(self, output_path: str | Path) -> Path:
        """Guarda JSON en la ruta elegida; util para compartir con el equipo."""
        if self.phase == 'preparado':
            raise ValueError('Inicia la alarma antes de exportar el reporte.')
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(self.report(), ensure_ascii=False, indent=2),
                               encoding='utf-8')
        return output_path
