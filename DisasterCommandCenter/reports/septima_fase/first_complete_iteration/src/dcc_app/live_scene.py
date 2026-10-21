"""Paso 14.4.2: puente Pygame-free entre la ventana y los motores existentes.

No altera clases de simulacion ni importa pygame. Escenarios didacticos, no
predicciones de evacuacion, incendio o riesgo medicos.
"""
from __future__ import annotations

from pathlib import Path
from simulation.evacuation_control import EvacuationControlCenter
from simulation.hazard_impact import FireEvacuationControlCenter
from simulation.wind_simulation import WIND_VECTORS

DIRECTIONS = tuple(WIND_VECTORS)


class LiveScene:
    def __init__(self, root: str | Path, *, kind: str = 'emergencia',
                 direction: str = 'E', intensity: float = 0.75):
        self.root = Path(root)
        self.direction = direction
        self.intensity = intensity
        self.kind = kind
        self.center = None
        self.reset()

    @property
    def is_emergency(self) -> bool:
        return self.kind == 'emergencia'

    def reset(self):
        files = (
            self.root / 'data' / 'campus.json',
            self.root / 'data' / 'building_entrances.json',
            self.root / 'data' / 'ocupacion_ejemplo.json',
        )
        if self.kind == 'emergencia':
            self.center = FireEvacuationControlCenter(
                *files, ignition=(78, 55), direction=self.direction,
                intensity=self.intensity, seed=2026)
        elif self.kind == 'normal':
            self.center = EvacuationControlCenter(*files)
        else:
            raise ValueError('Escenario desconocido')

    def toggle_kind(self):
        # Cambiar de escenario implica crear una simulacion nueva.
        if self.center.phase != 'preparado':
            raise ValueError('Reinicia con R antes de cambiar el escenario.')
        self.kind = 'normal' if self.is_emergency else 'emergencia'
        self.reset()
        return self.kind

    def start(self):
        self.center.start_alarm()

    def toggle_pause(self):
        return self.center.toggle_pause()

    def step(self, *, manual: bool = False):
        return self.center.step(manual=manual)

    @property
    def info(self) -> dict:
        return self.center.summary()

    @property
    def people(self):
        return self.center.people

    @property
    def environment(self):
        return self.center.environment if self.is_emergency else None

    @property
    def exposure(self):
        return self.center.tracker if self.is_emergency else None

    def set_wind(self, direction: str, intensity: float):
        if not self.is_emergency:
            raise ValueError('El viento solo se simula en el escenario de emergencia.')
        self.center.set_wind(direction, intensity)
        self.direction = self.center.direction
        self.intensity = self.center.intensity

    def cycle_wind(self):
        idx = DIRECTIONS.index(self.direction)
        self.set_wind(DIRECTIONS[(idx + 1) % len(DIRECTIONS)], self.intensity)
        return self.direction

    def adjust_wind(self, amount: float):
        self.set_wind(self.direction, round(max(0.0, min(1.0, self.intensity + amount)), 2))
        return self.intensity

    def ignite(self, x: int, y: int):
        if not self.is_emergency:
            raise ValueError('Activa el escenario con incendio usando T y luego A.')
        self.center.ignite(x, y)
