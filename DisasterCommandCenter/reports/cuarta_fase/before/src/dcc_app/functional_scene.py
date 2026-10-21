"""Escena funcional de main; mantiene el API de controles y exportacion."""
from __future__ import annotations

import json
from uuid import uuid4
from integration.refined_sensor_view import source_sensor_environment
from integration.sensor_export import export_sensor_dataset
from simulation.functional_scenario import FunctionalSimulation
from simulation.sensor_simulation import VirtualSensorNetwork
from .mode_scene import ModeSensorScene
from .model import load_campus


class FunctionalScene(ModeSensorScene):
    def __init__(self, root, *, mode=None, direction=None, intensity=None, kind="emergencia", configuracion=None):
        from pathlib import Path
        root = Path(root)
        config = json.loads((root / "data/functional_scenario.json").read_text(encoding="utf-8"))
        self.scale = config["subdivision"]
        self.source_snapshot = load_campus(root / "data/campus.json", root / "data/building_entrances.json")
        super().__init__(root, mode=mode, kind=kind, configuracion=configuracion,
                         direction=direction if direction is not None else config["wind"]["direction"],
                         intensity=intensity if intensity is not None else config["wind"]["speed"])

    def reset(self):
        self.center = FunctionalSimulation(self.root, kind=self.kind, mode=self.mode,
                                           direction=self.direction, intensity=self.intensity)
        self.session = getattr(self, "session", 0) + 1
        self.run_id = "dcc_functional_" + uuid4().hex
        config = json.loads((self.root / "data/sensores_paso_13.json").read_text(encoding="utf-8"))
        self.sensor_positions = tuple({**sensor, "x": sensor["x"]*self.scale+self.scale//2,
                                      "y": sensor["y"]*self.scale+self.scale//2}
                                     for sensor in config["sensors"])
        self.network = None
        self.current_readings, self.reading_history = [], []

    def _take_sample(self):
        if not self.is_emergency:
            return
        view = source_sensor_environment(self.environment, self.source_snapshot.terrain, self.scale)
        if self.network is None:
            self.network = VirtualSensorNetwork(view, self.root / "data/campus.json",
                self.root / "data/sensores_paso_13.json", run_id=self.run_id,
                seed=2026, temperature_noise=.15, smoke_noise=.005)
        else:
            self.network.environment = view
        rows = self.network.sample()
        self.current_readings = rows
        self.reading_history.extend(rows)

    def configure_wind(self, *, direction, speed):
        """Punto unico para futuros sliders; velocidad normalizada 0..1."""
        self.set_wind(direction, speed)
        return self.center.wind_history.state

    def select_ignition(self, x, y):
        return self.center.select_ignition(x, y)

    def export_readings(self, directory):
        if not self.reading_history:
            raise ValueError("No hay lecturas; inicia la alarma en emergencia.")
        return export_sensor_dataset(self.reading_history, directory, metadata={
            "scenario": "functional_refined", "people": len(self.people),
            "subdivision": self.scale, "native_grid": [self.center.manager.width, self.center.manager.height],
            "export_coordinate_grid": [self.source_snapshot.width, self.source_snapshot.height],
            "smoke_projection": "maximum_of_subcells", "fire_projection": "any_burning_subcell",
            "target_distance_unit": "source_grid_cell", "person_manager_mode": self.mode,
            "final_turn": self.info["turnos"],
        })
