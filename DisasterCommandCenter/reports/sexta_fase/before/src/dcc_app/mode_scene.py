"""Paso 14.4.4: escena con selector reversible por instancia.

No modifica clases originales. Toma el modo configurado UNA sola vez al abrir
la escena; cambiar el archivo JSON no altera simulaciones en curso.
Los valores de fuego, humo y sensores son sinteticos y didacticos.
"""
from __future__ import annotations

import json
from pathlib import Path

from selector_modo_14_3_6B import MODOS, crear_centro, leer_modo
from integration.sensor_export import export_sensor_dataset
from simulation.sensor_simulation import VirtualSensorNetwork
from .sensor_scene import SensorLiveScene


class ModeSensorScene(SensorLiveScene):
    """Conserva sensores/controles del Paso 14.4.3 y selecciona el controlador."""

    def __init__(self, root: str | Path, *, kind: str = 'emergencia',
                 mode: str | None = None, configuracion: str | Path | None = None,
                 direction: str = 'E', intensity: float = 0.75):
        self.configuracion = (Path(configuracion) if configuracion is not None
                              else Path(root) / 'data' / 'modo_ejecucion_14_3_6B.json')
        if mode is None:
            self.mode = leer_modo(self.configuracion)
        elif mode in MODOS:
            self.mode = mode
        else:
            raise ValueError('Modo invalido: original u optimizado.')
        super().__init__(root, kind=kind, direction=direction, intensity=intensity)

    def reset(self):
        """Recrea completamente el motor y los sensores en el modo de esta sesion."""
        files = (
            self.root / 'data' / 'campus.json',
            self.root / 'data' / 'building_entrances.json',
            self.root / 'data' / 'ocupacion_ejemplo.json',
        )
        options = ({'ignition': (78, 55), 'direction': self.direction,
                    'intensity': self.intensity, 'seed': 2026}
                   if self.kind == 'emergencia' else {})
        # selector_modo_14_3_6B es la fabrica aprobada en 14.3.6B.
        self.center = crear_centro(self.kind, *files, modo=self.mode, **options)

        # Misma configuracion de sensores de 14.4.3, ligada al NUEVO motor.
        # Evita seguir muestreando un ambiente perteneciente a un motor anterior.
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
                files[0], sensors_path,
                run_id=f'dcc_14_4_3_sesion_{self.session:04d}',
                seed=2026, temperature_noise=.15, smoke_noise=.005,
            )
        self.current_readings = []
        self.reading_history = []

    def set_mode(self, new_mode: str):
        """Cambio permitido SOLO antes de activar la alarma; nunca migra estados.

        Este cambio solo afecta a esta ventana: NO modifica el JSON guardado.
        """
        if new_mode not in MODOS:
            raise ValueError('Modo invalido: original u optimizado.')
        if self.center.phase != 'preparado':
            raise ValueError('Para cambiar de modo, reinicia con R antes de la alarma.')
        if new_mode == self.mode:
            return self.mode
        if new_mode == 'optimizado' and leer_modo(self.configuracion) != 'optimizado':
            raise ValueError('Modo optimizado no autorizado: activalo con gestionar_modo_14_3_6B.py.')
        previous = self.mode
        self.mode = new_mode
        try:
            self.reset()
        except Exception:
            # Fallar cerrado: restaurar la seleccion anterior y escena preparada.
            self.mode = previous
            self.reset()
            raise
        return self.mode

    def cycle_mode(self):
        return self.set_mode('original' if self.mode == 'optimizado' else 'optimizado')

    def export_readings(self, directory: str | Path):
        """Exporta el formato conocido e identifica el modo usado en el dataset."""
        if not self.reading_history:
            raise ValueError('No hay lecturas para exportar. Inicia la alarma en emergencia.')
        return export_sensor_dataset(
            self.reading_history, directory,
            metadata={
                'application_step': '14.4.4',
                'scenario': self.kind,
                'people': len(self.people),
                'final_turn': self.info['turnos'],
                'wind_towards': self.direction,
                'wind_intensity_relative': self.intensity,
                'person_manager_mode': self.mode,
            },
        )
