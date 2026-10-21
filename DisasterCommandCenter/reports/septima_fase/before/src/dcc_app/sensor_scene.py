"""Paso 14.4.3: sensores sincronizados con LiveScene (sin importar Pygame).

No cambia los motores. Las lecturas sinteticas son educativas, no datos
meteorologicos, termicos ni alarmas fisicas. En evacuacion normal, el paso 13
no dispone de un ambiente de fuego/humo, asi que no se inventan lecturas.
"""
from __future__ import annotations

import json
from pathlib import Path

from simulation.sensor_simulation import VirtualSensorNetwork
from integration.sensor_export import export_sensor_dataset
from .live_scene import LiveScene


class SensorLiveScene(LiveScene):
    def reset(self):
        super().reset()
        self.session = getattr(self, 'session', 0) + 1
        sensors_path = self.root / 'data' / 'sensores_paso_13.json'
        config = json.loads(sensors_path.read_text(encoding='utf-8'))
        if config.get('schema_version') != '1.0' or not isinstance(config.get('sensors'), list):
            raise ValueError('Configuracion de sensores incompatible.')
        self.sensor_positions = tuple(config['sensors'])
        self.network = None
        if self.is_emergency:
            self.network = VirtualSensorNetwork(
                self.environment,
                self.root / 'data' / 'campus.json',
                sensors_path,
                run_id=f'dcc_14_4_3_sesion_{self.session:04d}',
                seed=2026,
                temperature_noise=.15,
                smoke_noise=.005,
            )
        self.current_readings: list[dict] = []
        self.reading_history: list[dict] = []

    def _take_sample(self):
        if self.network is None:
            return
        readings = self.network.sample()
        self.current_readings = readings
        self.reading_history.extend(readings)

    def start(self):
        super().start()
        if self.is_emergency:
            self._take_sample()  # Turno 0, una vez activada la alarma.

    def step(self, *, manual: bool = False):
        old_turn = self.environment.fire.turn if self.is_emergency else None
        result = super().step(manual=manual)
        if self.is_emergency and self.environment.fire.turn > old_turn:
            self._take_sample()
        return result

    @property
    def sensor_stats(self) -> dict:
        latest = self.current_readings
        return {
            'installed': len(self.sensor_positions),
            'active': bool(self.network is not None and latest),
            'alarms': sum(bool(r['alarm']) for r in latest),
            'total_records': len(self.reading_history),
            'last_turn': latest[0]['turn'] if latest else None,
            'max_temperature_c': max((r['temperature_c'] for r in latest), default=None),
            'max_smoke_index': max((r['smoke_index'] for r in latest), default=None),
        }

    def export_readings(self, directory: str | Path):
        if not self.reading_history:
            raise ValueError('No hay lecturas para exportar. Activa primero la alarma en emergencia.')
        return export_sensor_dataset(
            self.reading_history, directory,
            metadata={
                'application_step': '14.4.3',
                'scenario': self.kind,
                'people': len(self.people),
                'final_turn': self.info['turnos'],
                'wind_towards': self.direction,
                'wind_intensity_relative': self.intensity,
            },
        )
