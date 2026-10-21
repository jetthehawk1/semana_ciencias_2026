"""Entrada de Persona 2 para paquetes CSV/JSONL/manifiesto del contrato 1.0."""
from __future__ import annotations

from pathlib import Path

from integration.persona2_contract_15_1 import (
    read_sensor_package as _read_sensor_package,
)

DEFAULT_SENSORS_PATH = Path(__file__).resolve().parents[2] / "data" / "sensores_paso_13.json"


def read_sensor_package(
    folder: str | Path, *, sensors_path: str | Path = DEFAULT_SENSORS_PATH
) -> dict:
    """Recibe un paquete sintetico y verifica tambien identidad y ubicacion.

    Conserva manifest, observables y labelled_rows del lector de Persona 1.
    observables excluye fire_within_2_cells; labelled_rows conserva el target.
    No escribe archivos ni convierte, imputa o corrige valores.
    Propaga los ValueError del contrato. sensors_path debe apuntar a una
    configuracion confiable; por defecto usa la del proyecto, sin depender
    del directorio desde el que se ejecute el consumidor.
    """
    return _read_sensor_package(folder, sensors_path=Path(sensors_path))
