"""Paso 12: exposición didáctica al fuego/humo e integración con evacuación.

NO es un modelo médico, toxicológico ni una evaluación real de seguridad.
La exposición es una puntuación adimensional acumulada por turno.
Conserva Person.status ('normal', 'evacuando', 'a_salvo') intacto.
Los estados de riesgo son una capa independiente de simulación.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path

from simulation.evacuation_control import EvacuationControlCenter
from simulation.indoor_evacuation import IndoorEvacuationController, CARDINAL
from simulation.wind_simulation import WindFireSmokeSimulation


@dataclass
class Exposure:
    dose: float = 0.0
    level: str = 'normal'
    fire_contact: bool = False
    peak_smoke: float = 0.0


class ExposureTracker:
    """Calcula niveles de riesgo simulados, sin modificar objetos Person."""

    def __init__(self, people, *, warning=0.35, slow=1.25, blocked=2.75):
        if not (0 < warning < slow < blocked):
            raise ValueError('Se necesitan umbrales ascendentes y positivos.')
        ids = [p.person_id for p in people]
        if len(ids) != len(set(ids)):
            raise ValueError('IDs duplicados en la poblacion.')
        self.records = {pid: Exposure() for pid in ids}
        self.warning = warning
        self.slow = slow
        self.blocked = blocked

    def update(self, people, burning, concentrations):
        """Una lectura por persona y turno, en su posición al iniciar movimiento."""
        for p in people:
            record = self.records[p.person_id]
            if record.level == 'incapacitada':
                continue  # Estado absorbente; se mantiene ocupada su celda.
            x, y = p.position
            value = concentrations[y][x]
            if not 0 <= value <= 1:
                raise ValueError('Concentracion de humo fuera del rango 0..1.')
            record.dose += float(value)
            record.peak_smoke = max(record.peak_smoke, value)
            if (x, y) in burning:
                record.fire_contact = True
                record.level = 'incapacitada'
            elif record.dose >= self.blocked:
                record.level = 'incapacitada'
            elif record.dose >= self.slow:
                record.level = 'ralentizada'
            elif record.dose >= self.warning:
                record.level = 'alerta'

    def counts(self):
        values = Counter(record.level for record in self.records.values())
        return {name: values[name] for name in ('normal','alerta','ralentizada','incapacitada')}


class HazardEvacuationController(IndoorEvacuationController):
    """Respeta rutas y puertas del Paso 8.12; evita fuego activo y personas inmoviles.

    No optimiza rutas según riesgos. Solo permite un paso seguro en vecindad
    cardinal sobre el campo de distancias preexistente. Una salida bloqueada
    puede impedir la evacuacion: esto se informa, no se teletransporta gente.
    """

    def step_with_hazards(self, tracker: ExposureTracker, burning) -> int:
        if self.paused:
            return 0
        occupied = self._occupied()
        moved = 0
        waiting = 0
        fire = set(burning)

        def eligible(pid):
            status = tracker.records[pid].level
            if status == 'incapacitada':
                return False
            # Lentitud didactica: un paso cada 2 turnos. Otras personas cada turno.
            return status != 'ralentizada' or self.steps % 2 == 0

        outdoor_ids = sorted(self.exited, key=lambda pid: (
            -self.outdoor_distance[self.exited[pid]].get(
                self.manager.people[pid].position, -1), pid))
        for pid in outdoor_ids:
            person = self.manager.people[pid]
            distance = self.outdoor_distance[self.exited[pid]]
            current = distance.get(person.position)
            if current is None or current >= self.exterior_distance:
                continue
            if not eligible(pid):
                waiting += 1
                continue
            candidates = []
            for dx, dy in CARDINAL:
                dest = (person.x+dx, person.y+dy)
                next_distance = distance.get(dest, -1)
                if (dest not in occupied and dest not in fire
                        and dest not in self.outside_doors
                        and next_distance > current):
                    candidates.append((dest, next_distance))
            candidates.sort(key=lambda v: (-v[1],
                (v[0][0]*13+v[0][1]*7+self.steps) % 17))
            if candidates:
                dest = candidates[0][0]
                previous = person.position
                self.manager.move_person(pid, dest[0]-person.x, dest[1]-person.y)
                occupied.remove(previous)
                occupied.add(dest)
                moved += 1
            else:
                waiting += 1

        indoor_ids = [pid for pid in self.ids
                      if self.manager.people[pid].building_id is not None]
        indexes = {pid: k for k, pid in enumerate(self.ids)}
        indoor_ids.sort(key=lambda pid: (
            self.indoor_distance[self.manager.people[pid].building_id][
                self.manager.people[pid].position],
            (indexes[pid]-self._priority) % max(1, len(self.ids))))
        for pid in indoor_ids:
            person = self.manager.people[pid]
            name = person.building_id
            current = person.position
            if not eligible(pid):
                waiting += 1
                continue
            if current in self.doors[name]:
                exit_cell = self.doors[name][current]
                if exit_cell in occupied or exit_cell in fire:
                    waiting += 1
                    continue
                occupied.remove(current)
                occupied.add(exit_cell)
                person.x, person.y = exit_cell
                person.building_id = None
                self.exited[pid] = name
                moved += 1
                continue
            distance = self.indoor_distance[name]
            current_distance = distance[current]
            candidates = []
            for dx, dy in CARDINAL:
                dest = (person.x+dx, person.y+dy)
                if (dest not in occupied and dest not in fire
                        and distance.get(dest, current_distance) < current_distance):
                    candidates.append(dest)
            if not candidates:
                waiting += 1
                continue
            dest = candidates[(self.steps+self._priority) % len(candidates)]
            occupied.remove(current)
            occupied.add(dest)
            person.x, person.y = dest
            moved += 1

        self._priority = (self._priority+1) % max(1, len(self.ids))
        self.steps += 1
        self.total_moves += moved
        self.waiting_last_step = waiting
        return moved


class FireEvacuationControlCenter(EvacuationControlCenter):
    """Coordina alarma, fuego + humo + viento y exposición sobre las 100 personas.

    Incendio predeterminado E30. Ninguna persona se marca 'a_salvo'.
    Si se incapacita, permanece en su posicion y bloquea esa celda.
    """

    def __init__(self, campus_path, entrances_path, population_path, *,
                 ignition=(78, 55), direction='E', intensity=0.75, seed=2026):
        self.ignition = ignition
        self.direction = direction
        self.intensity = intensity
        self.hazard_seed = seed
        self.environment = None
        self.tracker = None
        super().__init__(campus_path, entrances_path, population_path)
        if ignition is not None and not self.environment.fire.can_ignite(*ignition):
            raise ValueError('El foco inicial no es combustible o está fuera del mapa.')

    def reset(self):
        self.environment = WindFireSmokeSimulation.from_campus_json(
            self.campus_path, seed=self.hazard_seed,
            direction=self.direction, intensity=self.intensity)
        self.tracker = None
        super().reset()
        self.tracker = ExposureTracker(self.people)
        self.log = [self._sample()]

    def set_wind(self, direction, intensity):
        self.environment.set_wind(direction, intensity)
        self.direction = self.environment.wind.direction
        self.intensity = self.environment.wind.intensity

    def ignite(self, x, y):
        if self.phase == 'preparado':
            raise ValueError('Activa la alarma antes de iniciar focos adicionales.')
        self.environment.ignite(x, y)

    def start_alarm(self):
        if self.phase != 'preparado':
            raise ValueError('La alarma ya esta activada. Usa reset().')
        # Instanciar y validar todas las puertas ANTES de iniciar el fuego.
        controller = HazardEvacuationController(self.manager, self.entrances_path)
        if self.ignition is not None:
            self.environment.ignite(*self.ignition)
        self.controller = controller
        self.phase = 'en_curso' if controller.inside_count else 'completado'

    def step(self, *, manual=False):
        if self.phase in ('preparado', 'completado'):
            return 0
        if self.phase == 'pausado' and not manual:
            return 0
        controller = self.controller
        assert isinstance(controller, HazardEvacuationController)
        # Considerar focos activos antes y despues de actualizar el incendio:
        # una celda que se apaga durante el turno tambien estuvo ardiendo.
        fire_before = set(self.environment.fire.burning)
        self.environment.step()
        fire_during_turn = fire_before | set(self.environment.fire.burning)
        self.tracker.update(self.people, fire_during_turn,
                            self.environment.smoke.concentrations)
        if self.phase == 'pausado':
            controller.resume()
        try:
            moved = controller.step_with_hazards(
                self.tracker, fire_during_turn)
        finally:
            if self.phase == 'pausado':
                controller.pause()

        turn = controller.steps
        for building in self.buildings:
            exits = sum(p.building_id is None and self.origin[p.person_id] == building
                        for p in self.people)
            if exits and self.first_exit_turn[building] is None:
                self.first_exit_turn[building] = turn
            if exits == self.original_counts[building] and self.last_exit_turn[building] is None:
                self.last_exit_turn[building] = turn
        if controller.inside_count == 0:
            self.phase = 'completado'
        self.log.append(self._sample())
        return moved

    def summary(self):
        info = super().summary()
        if self.tracker is None:
            levels = {name: 0 for name in ('normal','alerta','ralentizada','incapacitada')}
        else:
            levels = self.tracker.counts()
        info['riesgo'] = levels
        info['fuego'] = self.environment.fire.stats() if self.environment else {}
        info['humo'] = self.environment.smoke.stats() if self.environment else {}
        info['viento'] = ({'direccion': self.environment.wind.direction,
                           'intensidad': self.environment.wind.intensity}
                          if self.environment else {})
        info['turnos_son_segundos'] = False
        return info

    def report(self):
        info = self.summary()
        return {
            'proyecto': 'Disaster Command Center',
            'paso': '12',
            'descripcion': 'Efecto didactico de humo y contacto con fuego sobre personas.',
            'advertencia': ('Exposicion adimensional arbitraria. Sin interpretacion medica. '
                            'No son segundos reales. Cruzar una puerta no significa estar a salvo.'),
            'resumen': info,
            'por_persona': [
                {'id': p.person_id,
                 'edificio_origen': self.origin[p.person_id],
                 'posicion': {'x': p.x, 'y': p.y},
                 'dentro': p.building_id is not None,
                 'estado_persona': p.status,
                 'nivel_riesgo': self.tracker.records[p.person_id].level,
                 'exposicion_acumulada': round(self.tracker.records[p.person_id].dose, 4),
                 'contacto_fuego': self.tracker.records[p.person_id].fire_contact}
                for p in self.people],
            'historial': self.log,
        }

    def _sample(self):
        summary = self.summary()
        return {
            'turno': summary['turnos'],
            'dentro': summary['dentro'],
            'salieron': summary['salieron'],
            'esperando': summary['esperando'],
            'riesgo': dict(summary['riesgo']),
            'celdas_ardiendo': summary['fuego'].get('burning', 0),
            'celdas_humo': summary['humo'].get('smoky_cells', 0),
        }
