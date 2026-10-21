"""Puente de Persona 2 para lecturas existentes, sin importar Pygame ni IA."""
from __future__ import annotations

from copy import deepcopy
from typing import Protocol

from integration.persona2_contract_15_1 import OBSERVABLE_FIELDS
from integration.sensor_export import COLUMNS


class PredictionProvider(Protocol):
    def predict_many(self, observations: list[dict]) -> list[dict]: ...


def _observables(readings):
    if not isinstance(readings, list) or not readings:
        raise ValueError("Se requiere una lista no vacia de lecturas.")
    rows = []
    for row in readings:
        if not isinstance(row, dict) or set(row) not in (set(COLUMNS), set(OBSERVABLE_FIELDS)):
            raise ValueError("Lectura con campos diferentes al contrato de sensores.")
        rows.append({key: row[key] for key in OBSERVABLE_FIELDS})
    return rows


def predict_sensor_readings(provider: PredictionProvider, readings: list[dict]) -> list[dict]:
    """Descarta el target del simulador antes de llamar al proveedor."""
    return provider.predict_many(_observables(readings))


class SensorPredictionAdapter:
    """Consume current_readings una vez por turno; el llamador controla la escena."""

    def __init__(self, provider: PredictionProvider):
        self.provider = provider
        self._last_key = None
        self._last_rows = None

    def update(self, scene) -> list[dict]:
        readings = scene.current_readings
        if not readings:
            return []
        rows = _observables(readings)
        run_id, turn = rows[0]["run_id"], rows[0]["turn"]
        if (not isinstance(run_id, str) or not run_id.strip() or type(turn) is not int or turn < 0
                or any(row["run_id"] != run_id or row["turn"] != turn for row in rows)):
            raise ValueError("current_readings debe representar una ejecucion y un turno.")
        key = (run_id, turn)
        if key == self._last_key:
            if rows != self._last_rows:
                raise ValueError("El mismo turno contiene observaciones modificadas.")
            return []
        if self._last_key and run_id == self._last_key[0] and turn < self._last_key[1]:
            raise ValueError("Turno retrocedido; usa un nuevo run_id o adaptador tras reinicio.")
        result = self.provider.predict_many(rows)
        self._last_key, self._last_rows = key, deepcopy(rows)
        return result
