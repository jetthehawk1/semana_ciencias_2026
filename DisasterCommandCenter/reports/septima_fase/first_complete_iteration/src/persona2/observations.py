"""Valida observaciones individuales sin target para inferencia en vivo."""
from __future__ import annotations

import json
import math
from pathlib import Path

from integration.persona2_contract_15_1 import OBSERVABLE_FIELDS, SCHEMA_VERSION
from .dataset import FEATURE_COLUMNS, TARGET_COLUMN
from .ingestion import DEFAULT_SENSORS_PATH


class ObservationProcessor:
    """Comparte nombres/rangos del contrato 1.0; no necesita un paquete etiquetado."""

    def __init__(self, sensors_path: str | Path = DEFAULT_SENSORS_PATH):
        try:
            config = json.loads(Path(sensors_path).read_text(encoding="utf-8"))
            if (not isinstance(config, dict) or config.get("schema_version") != SCHEMA_VERSION
                    or not isinstance(config.get("sensors"), list) or not config["sensors"]):
                raise ValueError("Version o lista de sensores no valida.")
            self.sensors = {}
            positions = set()
            for spec in config["sensors"]:
                sid, x, y, building = (spec[k] for k in ("sensor_id", "x", "y", "building_id"))
                if (not isinstance(sid, str) or not sid.strip() or sid in self.sensors
                        or type(x) is not int or type(y) is not int
                        or not (0 <= x < 160 and 0 <= y < 100) or (x, y) in positions
                        or (building is not None and (not isinstance(building, str) or not building))):
                    raise ValueError("Identidad o ubicacion de sensor no valida.")
                self.sensors[sid] = dict(spec)
                positions.add((x, y))
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise ValueError(f"Configuracion de sensores no valida: {error}") from error
        if TARGET_COLUMN in FEATURE_COLUMNS:
            raise ValueError("El target no puede formar parte de las features.")

    def prepare(self, observation: dict) -> tuple[dict, tuple]:
        if not isinstance(observation, dict):
            raise ValueError("La observacion debe ser un diccionario.")
        if TARGET_COLUMN in observation:
            raise ValueError("fire_within_2_cells es target; no debe enviarse a inferencia.")
        if set(observation) != set(OBSERVABLE_FIELDS):
            raise ValueError("Campos observables diferentes al contrato 1.0.")
        row = observation
        if (row["schema_version"] != SCHEMA_VERSION
                or not isinstance(row["run_id"], str) or not row["run_id"].strip()
                or type(row["turn"]) is not int or row["turn"] < 0
                or not isinstance(row["sensor_id"], str) or not row["sensor_id"]
                or type(row["x"]) is not int or type(row["y"]) is not int
                or not (0 <= row["x"] < 160 and 0 <= row["y"] < 100)
                or (row["building_id"] is not None
                    and (not isinstance(row["building_id"], str) or not row["building_id"]))
                or type(row["temperature_c"]) not in (int, float)
                or not math.isfinite(row["temperature_c"])
                or not -50 <= row["temperature_c"] <= 500
                or type(row["smoke_index"]) not in (int, float)
                or not math.isfinite(row["smoke_index"])
                or not 0 <= row["smoke_index"] <= 1
                or type(row["alarm"]) is not bool):
            raise ValueError("Tipo o rango de observacion no valido.")
        spec = self.sensors.get(row["sensor_id"])
        if spec is None or any(row[k] != spec[k] for k in ("x", "y", "building_id")):
            raise ValueError("Sensor o ubicacion no coincide con la configuracion.")
        clean = {key: row[key] for key in OBSERVABLE_FIELDS}
        features = tuple(int(row[k]) if k == "alarm" else float(row[k]) for k in FEATURE_COLUMNS)
        return clean, features
