"""P2.7: observaciones, anti-leakage y servicio intercambiable."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from generar_entrega_persona2_15_1 import produce
from integration.persona2_contract_15_1 import OBSERVABLE_FIELDS
from integration.sensor_export import export_sensor_dataset
from persona2.baseline import split_by_sensor
from persona2.dataset import load_sensor_dataset
from persona2.inference import DecisionTreeClassifier, PredictionService, train_prediction_service
from persona2.observations import ObservationProcessor


class RecordingPredictor:
    def __init__(self, values=None):
        self.calls = []
        self.values = values

    def predict(self, features):
        self.calls.append(features)
        return [False] * len(features) if self.values is None else self.values


class InferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = TemporaryDirectory(prefix="dcc_p27_inference_")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.base = Path(cls.workspace.name) / "package"
        cls.package = produce(cls.base)
        cls.observations = cls.package["observables"]
        cls.service = train_prediction_service(cls.base)

    def fake_service(self, predictor):
        metadata = {
            "model_id": "fake", "feature_columns": ["temperature_c", "smoke_index", "alarm"],
            "dataset_kind": "synthetic_simulation",
        }
        return PredictionService(predictor, model_id="fake", metadata=metadata)

    def test_all_real_observations_prepare_without_target(self):
        processor = ObservationProcessor()
        for row in self.observations:
            clean, features = processor.prepare(row)
            self.assertEqual(set(clean), set(OBSERVABLE_FIELDS))
            self.assertEqual(
                features, (row["temperature_c"], row["smoke_index"], int(row["alarm"]))
            )
            self.assertNotIn("fire_within_2_cells", clean)

    def test_each_observable_field_is_required(self):
        processor = ObservationProcessor()
        for field in OBSERVABLE_FIELDS:
            row = dict(self.observations[0])
            del row[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                processor.prepare(row)

    def test_target_and_unknown_fields_are_rejected(self):
        processor = ObservationProcessor()
        for extra in ("fire_within_2_cells", "co"):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                processor.prepare({**self.observations[0], extra: True})

    def test_invalid_types_ranges_and_nulls(self):
        processor = ObservationProcessor()
        cases = {
            "schema_version": ["2.0", None], "run_id": ["", " ", None],
            "turn": [True, -1, "0", None], "sensor_id": ["", "INVENTADO", None],
            "x": [True, -1, 160, None], "y": [-1, 100, 1.5, None],
            "building_id": ["", 12, None],
            "temperature_c": [True, "24", None, float("nan"), float("inf"), -51, 501],
            "smoke_index": [False, "0", None, float("nan"), float("inf"), -.01, 1.01],
            "alarm": [1, "False", None],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    processor.prepare({**self.observations[0], field: value})

    def test_numeric_boundaries_and_exterior_null_are_valid(self):
        processor = ObservationProcessor()
        row = next(row for row in self.observations if row["building_id"] is None)
        for temperature, smoke in ((-50, 0), (500, 1)):
            clean, features = processor.prepare({
                **row, "temperature_c": temperature, "smoke_index": smoke
            })
            self.assertIsNone(clean["building_id"])
            self.assertEqual(features[:2], (temperature, smoke))

    def test_bad_sensor_configuration_is_rejected(self):
        with TemporaryDirectory(prefix="dcc_p27_config_") as temp:
            path = Path(temp) / "sensors.json"
            for config in ({}, [], {"schema_version": "1.0", "sensors": []}):
                path.write_text(json.dumps(config), encoding="utf-8")
                with self.subTest(config=config), self.assertRaises(ValueError):
                    ObservationProcessor(path)

    def test_predictions_are_versioned_and_json_serializable(self):
        before = deepcopy(self.observations)
        predictions = self.service.predict_many(self.observations)
        self.assertEqual(len(predictions), 432)
        self.assertEqual(before, self.observations)
        self.assertEqual(json.loads(json.dumps(predictions, allow_nan=False)), predictions)
        for original, result in zip(self.observations, predictions):
            self.assertIs(type(result["predicted_fire_within_2_cells"]), bool)
            self.assertEqual(result["model_id"], self.service.model_id)
            self.assertEqual(result["dataset_kind"], "synthetic_simulation")
            self.assertNotIn("fire_within_2_cells", result)
            for key in ("run_id", "turn", "sensor_id", "x", "y", "building_id"):
                self.assertEqual(result[key], original[key])

    def test_predictor_receives_only_features(self):
        predictor = RecordingPredictor()
        service = self.fake_service(predictor)
        row = self.observations[0]
        self.assertFalse(service.predict(row)["predicted_fire_within_2_cells"])
        self.assertEqual(
            predictor.calls, [((row["temperature_c"], row["smoke_index"], int(row["alarm"])),)]
        )

    def test_predictor_can_be_replaced_without_changing_observations(self):
        predictor = RecordingPredictor([True])
        result = self.fake_service(predictor).predict(self.observations[0])
        self.assertTrue(result["predicted_fire_within_2_cells"])
        self.assertEqual(result["model_id"], "fake")

    def test_invalid_batch_is_rejected_before_model_call(self):
        predictor = RecordingPredictor()
        service = self.fake_service(predictor)
        for rows in (
            [], [self.observations[0], self.observations[0]],
            [self.observations[0], {**self.observations[1], "smoke_index": 2}],
            [self.package["labelled_rows"][0]],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                service.predict_many(rows)
        self.assertEqual(predictor.calls, [])

    def test_invalid_predictor_outputs_are_rejected(self):
        for values in ([], [1], ["False"], [0.0], [True, False]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.fake_service(RecordingPredictor(values)).predict(self.observations[0])

    def test_metadata_is_isolated_and_target_features_rejected(self):
        metadata = self.service.metadata
        metadata["feature_columns"].append("fire_within_2_cells")
        self.assertNotIn("fire_within_2_cells", self.service.metadata["feature_columns"])
        with self.assertRaises(ValueError):
            PredictionService(
                RecordingPredictor(), model_id=self.service.model_id, metadata=metadata
            )

    def test_training_uses_only_p24_training_rows(self):
        dataset = load_sensor_dataset(self.base)
        split = split_by_sensor(dataset)
        original_fit = DecisionTreeClassifier.fit
        seen = []

        def spy(model, X, y, *args, **kwargs):
            seen.append((X, y))
            return original_fit(model, X, y, *args, **kwargs)

        with patch.object(DecisionTreeClassifier, "fit", new=spy):
            service = train_prediction_service(self.base)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], tuple(dataset.X[i] for i in split.train_indices))
        self.assertEqual(seen[0][1], tuple(dataset.y[i] for i in split.train_indices))
        self.assertEqual(service.metadata["training"]["records"], 324)

    def test_model_id_and_predictions_are_reproducible(self):
        service = train_prediction_service(self.base)
        self.assertEqual(service.model_id, self.service.model_id)
        self.assertEqual(service.metadata, self.service.metadata)
        self.assertEqual(
            service.predict_many(self.observations[:12]),
            self.service.predict_many(self.observations[:12]),
        )

    def test_test_features_do_not_change_training_identity(self):
        dataset = load_sensor_dataset(self.base)
        split = split_by_sensor(dataset)
        held_out = set(split.test_sensors)
        rows = [
            {**row, "temperature_c": 500.0} if row["sensor_id"] in held_out else row
            for row in self.package["labelled_rows"]
        ]
        with TemporaryDirectory(prefix="dcc_p27_identity_") as temp:
            export_sensor_dataset(rows, temp)
            service = train_prediction_service(temp)
        self.assertEqual(service.model_id, self.service.model_id)

    def test_runtime_does_not_import_simulator_pygame_or_postgres(self):
        code = (
            "import sys; sys.path.insert(0,sys.argv[1]); "
            "from persona2.inference import train_prediction_service; "
            "service=train_prediction_service(sys.argv[2]); "
            "assert not any(k.split('.')[0] in "
            "{'pygame','dcc_app','simulation','psycopg'} for k in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(ROOT / "src"), str(self.base)],
            capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
