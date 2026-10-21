"""P2.2: tablas numericas y contexto separados de la etiqueta sintetica."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from integration.persona2_contract_15_1 import OBSERVABLE_FIELDS
from .ingestion import DEFAULT_SENSORS_PATH, read_sensor_package

FEATURE_COLUMNS = ("temperature_c", "smoke_index", "alarm")
TARGET_COLUMN = "fire_within_2_cells"
METADATA_COLUMNS = tuple(k for k in OBSERVABLE_FIELDS if k not in FEATURE_COLUMNS)


@dataclass(frozen=True)
class SensorDataset:
    """Tablas por filas: X[i], y[i] y metadata_rows[i] son la misma lectura.

    Las matrices son tuplas para mantener su alineacion tras la carga.
    metadata_rows conserva identidad, turno y ubicacion, fuera de X.
    manifest conserva la procedencia sintetica y los conteos del paquete.
    """

    feature_columns: tuple[str, ...]
    X: tuple[tuple[float | int, ...], ...]
    target_column: str
    y: tuple[bool, ...]
    metadata_columns: tuple[str, ...]
    metadata_rows: tuple[tuple[object, ...], ...]
    manifest: dict


def load_sensor_dataset(
    folder: str | Path, *, sensors_path: str | Path = DEFAULT_SENSORS_PATH
) -> SensorDataset:
    """Valida con P2.1 y prepara X/y sin entrenar ni escribir archivos.

    X usa una seleccion explicita de campos observables, nunca se construye
    eliminando solo el target de la fila completa. No imputa ni escala datos.
    Conserva el orden recibido. alarm pasa a 0/1 y las mediciones a float.
    """
    if TARGET_COLUMN in FEATURE_COLUMNS:
        raise ValueError("El target fire_within_2_cells no puede incluirse en X.")
    if (not FEATURE_COLUMNS or len(set(FEATURE_COLUMNS)) != len(FEATURE_COLUMNS)
            or not set(FEATURE_COLUMNS).issubset(OBSERVABLE_FIELDS)):
        raise ValueError("Las features deben ser campos observables unicos.")

    package = read_sensor_package(folder, sensors_path=sensors_path)
    observables = package["observables"]
    return SensorDataset(
        feature_columns=FEATURE_COLUMNS,
        X=tuple(
            tuple(int(row[k]) if k == "alarm" else float(row[k])
                  for k in FEATURE_COLUMNS)
            for row in observables
        ),
        target_column=TARGET_COLUMN,
        y=tuple(row[TARGET_COLUMN] for row in package["labelled_rows"]),
        metadata_columns=METADATA_COLUMNS,
        metadata_rows=tuple(
            tuple(row[k] for k in METADATA_COLUMNS) for row in observables
        ),
        manifest=package["manifest"],
    )
