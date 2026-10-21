"""P2.7: servicio de prediccion reemplazable, sin Pygame ni PostgreSQL."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

import numpy as np
from sklearn.tree import DecisionTreeClassifier

from .baseline import MODEL_PARAMETERS, RANDOM_STATE, split_by_sensor
from .dataset import FEATURE_COLUMNS, TARGET_COLUMN, load_sensor_dataset
from .ingestion import DEFAULT_SENSORS_PATH
from .observations import ObservationProcessor


class PredictionService:
    """Acepta un predictor ajustado que devuelve bool y consume las 3 features.

    El consumidor solo necesita predict(observation) o predict_many(list).
    Un predictor alternativo puede sustituir el arbol sin cambiar el gateway.
    """

    def __init__(
        self, predictor, *, model_id: str, metadata: dict,
        sensors_path: str | Path = DEFAULT_SENSORS_PATH,
    ):
        if (not callable(getattr(predictor, "predict", None))
                or not isinstance(model_id, str) or not model_id.strip()
                or not isinstance(metadata, dict)
                or metadata.get("feature_columns") != list(FEATURE_COLUMNS)
                or metadata.get("dataset_kind") != "synthetic_simulation"
                or metadata.get("model_id") != model_id):
            raise ValueError("Predictor o metadatos incompatibles con la interfaz.")
        self._predictor = predictor
        self.model_id = model_id
        self._metadata = deepcopy(metadata)
        self._processor = ObservationProcessor(sensors_path)

    @property
    def metadata(self):
        return deepcopy(self._metadata)

    def predict(self, observation: dict) -> dict:
        return self.predict_many([observation])[0]

    def predict_many(self, observations: list[dict]) -> list[dict]:
        if not isinstance(observations, list) or not observations:
            raise ValueError("Se requiere una lista no vacia de observaciones.")
        prepared = [self._processor.prepare(row) for row in observations]
        keys = [(row["run_id"], row["turn"], row["sensor_id"]) for row, _ in prepared]
        if len(set(keys)) != len(keys):
            raise ValueError("Observacion duplicada en el lote.")
        values = list(self._predictor.predict(tuple(features for _, features in prepared)))
        if len(values) != len(prepared) or any(
            not isinstance(value, (bool, np.bool_)) for value in values
        ):
            raise ValueError("El predictor debe devolver un bool por observacion.")
        return [
            {
                "schema_version": "1.0", "dataset_kind": "synthetic_simulation",
                **{key: row[key] for key in (
                    "run_id", "turn", "sensor_id", "x", "y", "building_id"
                )},
                "model_id": self.model_id,
                "target_name": TARGET_COLUMN,
                "predicted_fire_within_2_cells": bool(value),
            }
            for (row, _), value in zip(prepared, values)
        ]


def train_prediction_service(
    folder: str | Path, *, sensors_path: str | Path = DEFAULT_SENSORS_PATH
) -> PredictionService:
    """Referencia experimental explicita, entrenada solo con train de P2.4.

    No selecciona modelo segun test, no reajusta sobre todos los datos y no
    atribuye calidad predictiva a esta demostracion de integracion.
    """
    dataset = load_sensor_dataset(folder, sensors_path=sensors_path)
    split = split_by_sensor(dataset)
    X = tuple(dataset.X[i] for i in split.train_indices)
    y = tuple(dataset.y[i] for i in split.train_indices)
    parameters = {**MODEL_PARAMETERS, "random_state": RANDOM_STATE}
    training_content = {
        "features": dataset.feature_columns, "X": X, "y": y,
        "keys": tuple(dataset.metadata_rows[i] for i in split.train_indices),
        "parameters": parameters, "sklearn": version("scikit-learn"),
    }
    digest = hashlib.sha256(json.dumps(
        training_content, sort_keys=True, allow_nan=False
    ).encode("utf-8")).hexdigest()
    model_id = "synthetic-dt-" + digest
    model = DecisionTreeClassifier(**parameters).fit(X, y)
    metadata = {
        "model_id": model_id, "algorithm": "DecisionTreeClassifier",
        "status": "experimental_synthetic_baseline", "dataset_kind": "synthetic_simulation",
        "feature_columns": list(FEATURE_COLUMNS), "target_name": TARGET_COLUMN,
        "parameters": parameters, "sklearn_version": version("scikit-learn"),
        "training": {
            "run_id": dataset.manifest["run_id"], "records": len(X),
            "sensors": list(split.train_sensors), "sha256": digest,
        },
    }
    return PredictionService(model, model_id=model_id, metadata=metadata, sensors_path=sensors_path)
