"""Telemetria sintetica de viento separada del contrato termico 1.0."""
from __future__ import annotations

import json
import math
from pathlib import Path
from simulation.wind_simulation import Wind

WIND_FIELDS = frozenset({"schema_version", "data_source", "run_id", "turn", "sensor_id",
                         "x", "y", "wind_direction", "wind_speed"})


def validate_wind_observation(row, *, width=480, height=300):
    if not isinstance(row, dict) or set(row) != WIND_FIELDS:
        raise ValueError("Campos incompatibles con wind_observation/1.0.")
    if row["schema_version"] != "wind_observation/1.0" or row["data_source"] != "synthetic_simulation":
        raise ValueError("Version/origen de viento incompatible.")
    if any(not isinstance(row[k], str) or not row[k].strip() for k in ("run_id", "sensor_id")):
        raise ValueError("Identificadores de viento invalidos.")
    if type(row["turn"]) is not int or row["turn"] < 0:
        raise ValueError("Turno de viento invalido.")
    if any(type(row[k]) is not int for k in ("x", "y")) or not (0 <= row["x"] < width and 0 <= row["y"] < height):
        raise ValueError("Posicion de sensor de viento fuera del grid nativo.")
    Wind(row["wind_direction"], row["wind_speed"])
    return dict(row)


class WindTelemetry:
    def __init__(self, sensors, run_id, *, width=480, height=300):
        self.sensors, self.run_id = tuple(sensors), run_id
        if not self.sensors or len({s["sensor_id"] for s in self.sensors}) != len(self.sensors):
            raise ValueError("Sensores meteorologicos vacios o duplicados.")
        self.width, self.height = width, height
        self.observations = []
        self.current = []
        self.last_turn = -1

    def sample(self, turn, wind):
        if type(turn) is not int or turn < self.last_turn:
            raise ValueError("Turno meteorologico retrocedido.")
        if turn == self.last_turn:
            return []  # Pausa/relectura no duplica ni reescribe el dato observado.
        rows = [validate_wind_observation({"schema_version": "wind_observation/1.0",
            "data_source": "synthetic_simulation", "run_id": self.run_id, "turn": turn,
            "sensor_id": s["sensor_id"], "x": s["x"], "y": s["y"],
            "wind_direction": wind.direction, "wind_speed": float(wind.intensity)},
            width=self.width, height=self.height) for s in self.sensors]
        self.current = rows
        self.observations.extend(rows)
        self.last_turn = turn
        return rows

    def export(self, folder):
        folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
        path = folder / "wind_observations.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False, allow_nan=False)+"\n"
                                for r in self.observations), encoding="utf-8")
        manifest = folder / "wind_manifest.json"
        manifest.write_text(json.dumps({"schema_version": "wind_observation/1.0",
            "data_source": "synthetic_simulation", "run_id": self.run_id,
            "records": len(self.observations), "sensor_ids": [s["sensor_id"] for s in self.sensors],
            "coordinate_grid": [self.width, self.height], "speed_unit": "normalized_0_1",
            "time_unit": "simulation_turn_not_seconds", "wind_scope": "global_virtual_measurement"},
            indent=2)+"\n", encoding="utf-8")
        return {"wind_jsonl": path, "wind_manifest": manifest}
