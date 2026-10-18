"""Adaptador lector para Persona 2 (Paso 15.1).

Lee exportaciones del Paso 13/14.4.4 sin tocar la simulacion.
Diferencia lecturas observables de una etiqueta sintetica de referencia.
No requiere PostgreSQL, IA, Pygame ni servicios externos.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from integration.sensor_export import COLUMNS

SCHEMA_VERSION = "1.0"
OBSERVABLE_FIELDS = tuple(k for k in COLUMNS if k != "fire_within_2_cells")


def _strict_json(text: str):
    def reject_constant(value):
        raise ValueError(f"Valor numerico no JSON: {value}")
    return json.loads(text, parse_constant=reject_constant)


def _is_finite_number(x):
    return type(x) in (int, float) and math.isfinite(x)


def read_sensor_package(folder: str | Path, *, sensors_path: str | Path | None = None) -> dict:
    """Valida un conjunto CSV + JSONL + manifiesto y devuelve su parte observable.

    No escribe archivos. No modifica el dataset ni la simulacion.
    Raise ValueError on invalid or inconsistent datasets.
    """
    folder = Path(folder)
    try:
        manifest = _strict_json((folder / "manifiesto_sensores.json").read_text(encoding="utf-8"))
        lines = (folder / "lecturas_sensores.jsonl").read_text(encoding="utf-8").splitlines()
        with (folder / "lecturas_sensores.csv").open(encoding="utf-8-sig", newline="") as f:
            csv_reader = csv.DictReader(f)
            if csv_reader.fieldnames != list(COLUMNS):
                raise ValueError("CSV: columnas diferentes al contrato 1.0.")
            csv_rows = list(csv_reader)
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise ValueError(f"No se pudo abrir/interpretar el paquete: {e}") from e

    if not isinstance(manifest, dict) or any(manifest.get(k) != v for k, v in (
        ("schema_version", SCHEMA_VERSION),
        ("dataset_kind", "synthetic_simulation"),
        ("time_unit", "simulation_turn_not_seconds"),
    )):
        raise ValueError("Manifiesto incompatible: schema_version/dataset_kind/time_unit.")
    if not lines or len(lines) != len(csv_rows):
        raise ValueError("CSV y JSONL vacios o con cantidades diferentes.")

    expected_sensors = None
    if sensors_path is not None:
        try:
            config = _strict_json(Path(sensors_path).read_text(encoding="utf-8"))
            if config.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("Configuracion de sensores con version diferente.")
            expected_sensors = {r["sensor_id"]: r for r in config["sensors"]}
            if len(expected_sensors) != len(config["sensors"]):
                raise ValueError("Configuracion contiene IDs duplicados.")
        except (OSError, UnicodeError, KeyError, TypeError, json.JSONDecodeError) as e:
            raise ValueError(f"Configuracion de sensores no valida: {e}") from e

    rows, unique_keys, sensors, turns = [], set(), set(), set()
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id del manifiesto invalido.")
    for i, (line, csv_row) in enumerate(zip(lines, csv_rows)):
        try:
            r = _strict_json(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSONL fila {i+1}: JSON invalido") from e
        if not isinstance(r, dict) or set(r) != set(COLUMNS):
            raise ValueError(f"Fila {i+1}: campos JSONL diferentes al contrato.")
        if csv_row.get(None) is not None:
            raise ValueError(f"CSV fila {i+1}: hay columnas sobrantes.")
        if any(csv_row[k] != ("" if r[k] is None else str(r[k])) for k in COLUMNS):
            raise ValueError(f"CSV/JSONL no coinciden en fila {i+1}.")
        if (r["schema_version"] != SCHEMA_VERSION or r["run_id"] != run_id
                or type(r["turn"]) is not int or r["turn"] < 0
                or not isinstance(r["sensor_id"], str) or not r["sensor_id"]
                or type(r["x"]) is not int or type(r["y"]) is not int
                or not (0 <= r["x"] < 160 and 0 <= r["y"] < 100)
                or (r["building_id"] is not None and
                    (not isinstance(r["building_id"], str) or not r["building_id"]))
                or not _is_finite_number(r["temperature_c"])
                or not (-50 <= r["temperature_c"] <= 500)
                or not _is_finite_number(r["smoke_index"])
                or not (0 <= r["smoke_index"] <= 1)
                or type(r["alarm"]) is not bool
                or type(r["fire_within_2_cells"]) is not bool):
            raise ValueError(f"Fila {i+1}: tipo o rango no valido.")
        if expected_sensors is not None:
            spec = expected_sensors.get(r["sensor_id"])
            if spec is None or any(r[k] != spec[k] for k in ("x", "y", "building_id")):
                raise ValueError(f"Fila {i+1}: sensor no coincide con configuracion.")
        key = (r["turn"], r["sensor_id"])
        if key in unique_keys:
            raise ValueError(f"Lectura duplicada: {key}.")
        unique_keys.add(key)
        turns.add(r["turn"])
        sensors.add(r["sensor_id"])
        rows.append(r)

    if expected_sensors is not None and sensors != set(expected_sensors):
        raise ValueError("No se registraron todos los sensores configurados.")
    if turns != set(range(min(turns), max(turns)+1)):
        raise ValueError("Faltan turnos del dataset.")
    if any({r["sensor_id"] for r in rows if r["turn"] == t} != sensors for t in turns):
        raise ValueError("Faltan sensores en uno o mas turnos.")
    checks = {
        "records": len(rows), "sensor_count": len(sensors),
        "turn_count": len(turns), "first_turn": min(turns), "last_turn": max(turns),
    }
    if any(type(manifest.get(k)) is not int or manifest[k] != v for k, v in checks.items()):
        raise ValueError("Conteos o turnos del manifiesto inconsistentes.")

    # La etiqueta fire_within_2_cells NO se transmite al canal observable de IA.
    observables = [{k: r[k] for k in OBSERVABLE_FIELDS} for r in rows]
    return {"manifest": manifest, "observables": observables, "labelled_rows": rows}
