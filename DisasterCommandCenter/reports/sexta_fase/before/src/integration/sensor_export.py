"""Paso 13: salida transportable de sensores simulados hacia Persona 2.

No presume tablas SQL, endpoints de IA, infraestructura ni credenciales.
Esta capa define una propuesta de contrato versionado para CSV y JSONL.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

COLUMNS = (
    "schema_version", "run_id", "turn", "sensor_id", "x", "y",
    "building_id", "temperature_c", "smoke_index", "alarm",
    "fire_within_2_cells",
)


def export_sensor_dataset(rows: list[dict], output_dir: str | Path,
                          *, metadata: dict | None = None) -> dict[str, Path]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("Se necesita una lista no vacía de lecturas.")
    for index, record in enumerate(rows):
        if not isinstance(record, dict) or set(record) != set(COLUMNS):
            raise ValueError(f"Lectura {index}: esquema de campos incorrecto.")
    seen = set()
    ids, ticks = set(), set()
    run_id = rows[0]["run_id"]
    for record in rows:
        if record["run_id"] != run_id:
            raise ValueError("Mezcla de ejecuciones en un solo dataset.")
        key = (record["turn"], record["sensor_id"])
        if key in seen:
            raise ValueError(f"Lectura duplicada por turno/sensor: {key}.")
        seen.add(key)
        ids.add(record["sensor_id"])
        ticks.add(record["turn"])
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / "lecturas_sensores.csv"
    jsonl_path = output / "lecturas_sensores.jsonl"
    manifest_path = output / "manifiesto_sensores.json"
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        for record in rows:
            row = dict(record)
            row["building_id"] = "" if row["building_id"] is None else row["building_id"]
            writer.writerow(row)
    with jsonl_path.open("w", encoding="utf-8") as file:
        for record in rows:
            file.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    manifest = {
        "schema_version": "1.0", "dataset_kind": "synthetic_simulation",
        "project": "Disaster Command Center", "step": "13",
        "run_id": run_id, "records": len(rows),
        "sensor_count": len(ids), "turn_count": len(ticks),
        "first_turn": min(ticks), "last_turn": max(ticks),
        "time_unit": "simulation_turn_not_seconds",
        "temperature_note": "Celsius ficticios generados por regla, NO termometría real",
        "smoke_index_note": "Concentración normalizada 0..1, NO ppm",
        "labels_note": "fire_within_2_cells es etiqueta de verdad-terreno, NO señal observable del sensor",
        "metadata": {} if metadata is None else metadata,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2,
                                         allow_nan=False) + "\n", encoding="utf-8")
    return {"csv": csv_path, "jsonl": jsonl_path, "manifest": manifest_path}
