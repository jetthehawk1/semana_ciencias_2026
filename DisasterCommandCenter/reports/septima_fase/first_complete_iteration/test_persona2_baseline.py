"""P2.4: separacion por grupos, fit solo en train y metricas auditables."""
from __future__ import annotations

from dataclasses import replace
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
from integration.sensor_export import export_sensor_dataset
from persona2.baseline import (
    DecisionTreeClassifier, binary_metrics, evaluate_baseline, render_report,
    split_by_sensor,
)
from persona2.dataset import load_sensor_dataset


class BaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = TemporaryDirectory(prefix="dcc_p24_")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.base = Path(cls.workspace.name) / "base"
        produce(cls.base)
        cls.dataset = load_sensor_dataset(cls.base)

    def setUp(self):
        self.case = TemporaryDirectory(prefix="dcc_p24_case_")
        self.addCleanup(self.case.cleanup)
        self.root = Path(self.case.name)
        self.folder = self.root / "package"
        shutil.copytree(self.base, self.folder)

    def cli(self, *args):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-B", "-m", "persona2.baseline", str(self.folder),
             *map(str, args)], cwd=self.root, env=env, capture_output=True,
            text=True, encoding="utf-8", timeout=60,
        )

    def test_sensors_and_readings_are_disjoint_and_complete(self):
        split = split_by_sensor(self.dataset)
        self.assertEqual(len(split.train_sensors), 9)
        self.assertEqual(len(split.test_sensors), 3)
        self.assertFalse(set(split.train_sensors) & set(split.test_sensors))
        self.assertFalse(set(split.train_indices) & set(split.test_indices))
        self.assertEqual(
            set(split.train_indices) | set(split.test_indices), set(range(432))
        )
        sensor_index = self.dataset.metadata_columns.index("sensor_id")
        for indices, sensors in (
            (split.train_indices, split.train_sensors),
            (split.test_indices, split.test_sensors),
        ):
            self.assertEqual(
                {self.dataset.metadata_rows[i][sensor_index] for i in indices}, set(sensors)
            )
        self.assertEqual(len(split.train_indices), 324)
        self.assertEqual(len(split.test_indices), 108)

    def test_both_partitions_contain_both_classes(self):
        split = split_by_sensor(self.dataset)
        for indices in (split.train_indices, split.test_indices):
            self.assertEqual({self.dataset.y[i] for i in indices}, {False, True})

    def test_split_is_reproducible_and_independent_of_input_order(self):
        first = split_by_sensor(self.dataset)
        self.assertEqual(first, split_by_sensor(self.dataset))
        from persona2.ingestion import read_sensor_package
        rows = read_sensor_package(self.folder)["labelled_rows"]
        export_sensor_dataset(list(reversed(rows)), self.folder)
        reversed_split = split_by_sensor(load_sensor_dataset(self.folder))
        self.assertEqual(reversed_split.train_sensors, first.train_sensors)
        self.assertEqual(reversed_split.test_sensors, first.test_sensors)

    def test_known_metrics_and_matrix_order(self):
        metrics = binary_metrics(
            [False, False, True, True], [False, True, False, True]
        )
        for name in ("accuracy", "precision", "recall", "f1"):
            self.assertEqual(metrics[name], .5)
        self.assertEqual(metrics["confusion_matrix"], [[1, 1], [1, 1]])
        self.assertEqual(metrics["confusion_matrix_labels"], [False, True])
        self.assertEqual(metrics["undefined_metrics"], [])

    def test_majority_accuracy_does_not_hide_zero_recall(self):
        metrics = binary_metrics([False, False, False, True], [False] * 4)
        self.assertEqual(metrics["accuracy"], .75)
        self.assertEqual(metrics["precision"], 0)
        self.assertEqual(metrics["recall"], 0)
        self.assertEqual(metrics["f1"], 0)
        self.assertEqual(metrics["confusion_matrix"], [[3, 0], [1, 0]])
        self.assertEqual(metrics["undefined_metrics"], ["precision"])

    def test_absent_positive_class_is_reported_explicitly(self):
        metrics = binary_metrics([False, False], [False, False])
        self.assertEqual(metrics["confusion_matrix"], [[2, 0], [0, 0]])
        self.assertEqual(metrics["undefined_metrics"], ["precision", "recall", "f1"])

    def test_invalid_metric_inputs_are_rejected(self):
        for actual, predicted in (([], []), ([True], []), ([1], [True]), ([True], ["True"])):
            with self.subTest(actual=actual, predicted=predicted):
                with self.assertRaises(ValueError):
                    binary_metrics(actual, predicted)

    def test_fit_receives_only_training_features_and_labels(self):
        seen = []
        original_fit = DecisionTreeClassifier.fit

        def spy(model, X, y, *args, **kwargs):
            seen.append((tuple(X), tuple(y), model.get_params()))
            return original_fit(model, X, y, *args, **kwargs)

        with patch("persona2.baseline.DecisionTreeClassifier.fit", new=spy):
            report = evaluate_baseline(self.folder)
        split = split_by_sensor(self.dataset)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], tuple(self.dataset.X[i] for i in split.train_indices))
        self.assertEqual(seen[0][1], tuple(self.dataset.y[i] for i in split.train_indices))
        self.assertEqual(report["feature_columns"], ["temperature_c", "smoke_index", "alarm"])
        self.assertNotIn("fire_within_2_cells", report["feature_columns"])
        self.assertTrue(all(len(row) == 3 for row in seen[0][0]))
        self.assertEqual(seen[0][2]["class_weight"], "balanced")
        self.assertEqual(seen[0][2]["max_depth"], 3)
        self.assertEqual(seen[0][2]["min_samples_leaf"], 2)
        self.assertEqual(seen[0][2]["random_state"], 2026)

    def test_report_is_reproducible_and_input_unchanged(self):
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        report = evaluate_baseline(self.folder)
        self.assertEqual(evaluate_baseline(self.folder), report)
        self.assertEqual({path.name: path.read_bytes() for path in self.folder.iterdir()}, before)
        self.assertEqual(json.loads(json.dumps(report, allow_nan=False)), report)

    def test_audited_predictions_match_held_out_rows_and_metrics(self):
        report = evaluate_baseline(self.folder)
        split = split_by_sensor(self.dataset)
        self.assertEqual(len(report["test_predictions"]), len(split.test_indices))
        pairs = []
        for row, i in zip(report["test_predictions"], split.test_indices):
            context = dict(zip(self.dataset.metadata_columns, self.dataset.metadata_rows[i]))
            self.assertEqual(
                (row["run_id"], row["turn"], row["sensor_id"]),
                (context["run_id"], context["turn"], context["sensor_id"]),
            )
            self.assertEqual(row["actual"], self.dataset.y[i])
            self.assertIn(row["sensor_id"], report["split"]["test_sensors"])
            pairs.append((row["actual"], row["predicted"]))
        matrix = [[sum(a == actual and p == pred for a, p in pairs)
                   for pred in (False, True)] for actual in (False, True)]
        self.assertEqual(report["metrics"]["confusion_matrix"], matrix)
        self.assertEqual(sum(sum(row) for row in matrix), report["split"]["test_records"])

    def test_reference_uses_training_majority(self):
        report = evaluate_baseline(self.folder)
        counts = report["split"]["class_distribution"]["train"]
        self.assertGreater(counts["false"], counts["true"])
        self.assertFalse(report["majority_reference"]["predicted_class"])
        self.assertEqual(report["majority_reference"]["metrics"]["recall"], 0)
        self.assertEqual(report["majority_reference"]["metrics"]["f1"], 0)

    def test_single_class_dataset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "ambas clases"):
            split_by_sensor(replace(self.dataset, y=(False,) * len(self.dataset.y)))

    def test_insufficient_sensor_strata_are_rejected_without_row_fallback(self):
        sensor_index = self.dataset.metadata_columns.index("sensor_id")
        indices = [i for i, row in enumerate(self.dataset.metadata_rows)
                   if row[sensor_index] in {"S-E30-01", "S-E1-01"}]
        small = replace(
            self.dataset, X=tuple(self.dataset.X[i] for i in indices),
            y=tuple(self.dataset.y[i] for i in indices),
            metadata_rows=tuple(self.dataset.metadata_rows[i] for i in indices),
        )
        with self.assertRaisesRegex(ValueError, "al menos dos sensores"):
            split_by_sensor(small)

    def test_invalid_partition_parameters_are_rejected(self):
        for test_size in (0, 1, -1, True, float("nan"), "0.25"):
            with self.subTest(test_size=test_size):
                with self.assertRaises(ValueError):
                    split_by_sensor(self.dataset, test_size=test_size)
        with self.assertRaisesRegex(ValueError, "random_state"):
            split_by_sensor(self.dataset, random_state=True)
        with self.assertRaisesRegex(ValueError, "No se puede reservar grupos"):
            split_by_sensor(self.dataset, test_size=.01)

    def test_misaligned_dataset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "alineados"):
            split_by_sensor(replace(self.dataset, y=self.dataset.y[:-1]))

    def test_target_or_unapproved_features_are_rejected(self):
        for features in (
            (*self.dataset.feature_columns, "fire_within_2_cells"),
            ("temperature_c", "turn", "sensor_id"),
        ):
            with self.subTest(features=features):
                with self.assertRaisesRegex(ValueError, "sin target"):
                    split_by_sensor(replace(self.dataset, feature_columns=features))

    def test_sensor_configuration_is_forwarded(self):
        config = json.loads((ROOT / "data/sensores_paso_13.json").read_text("utf-8"))
        config["sensors"][0]["x"] = 150
        path = self.root / "sensors.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sensor no coincide"):
            evaluate_baseline(self.folder, sensors_path=path)

    def test_cli_writes_matching_reports(self):
        output = self.root / "reports"
        result = self.cli("--output-dir", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            json.loads((output / "informe_baseline.json").read_text("utf-8")), report
        )
        markdown = (output / "informe_baseline.md").read_text("utf-8")
        self.assertEqual(markdown, render_report(report))
        self.assertIn("Precision", markdown)
        self.assertIn("No se ha medido generalizacion", markdown)

    def test_invalid_package_produces_no_report(self):
        path = self.folder / "manifiesto_sensores.json"
        manifest = json.loads(path.read_text("utf-8"))
        manifest["records"] = 999
        path.write_text(json.dumps(manifest), encoding="utf-8")
        output = self.root / "reports"
        result = self.cli("--output-dir", output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
