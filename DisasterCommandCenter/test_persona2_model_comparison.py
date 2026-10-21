"""P2.5: comparacion comparable, escalado sin test y resultados auditables."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
from statistics import mean
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import warnings

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from generar_entrega_persona2_15_1 import produce
from integration.sensor_export import export_sensor_dataset
from persona2 import model_comparison as comparison
from persona2.baseline import evaluate_baseline, split_by_sensor
from persona2.dataset import load_sensor_dataset
from persona2.ingestion import read_sensor_package


class ModelComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = TemporaryDirectory(prefix="dcc_p25_")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.base = Path(cls.workspace.name) / "base"
        produce(cls.base)
        cls.dataset = load_sensor_dataset(cls.base)

    def setUp(self):
        self.case = TemporaryDirectory(prefix="dcc_p25_case_")
        self.addCleanup(self.case.cleanup)
        self.root = Path(self.case.name)
        self.folder = self.root / "package"
        shutil.copytree(self.base, self.folder)

    def cli(self, *args):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-B", "-m", "persona2.model_comparison", str(self.folder),
             *map(str, args)], cwd=self.root, env=env, capture_output=True,
            text=True, encoding="utf-8", timeout=60,
        )

    def test_same_split_features_and_target_for_all_models(self):
        report = comparison.compare_models(self.folder)
        self.assertEqual(
            list(report["models"]), ["logistic_regression", "decision_tree", "random_forest"]
        )
        self.assertEqual(report["split"]["train_records"], 324)
        self.assertEqual(report["split"]["test_records"], 108)
        self.assertFalse(
            set(report["split"]["train_sensors"]) & set(report["split"]["test_sensors"])
        )
        self.assertEqual(report["feature_columns"], ["temperature_c", "smoke_index", "alarm"])
        self.assertEqual(report["target_column"], "fire_within_2_cells")
        expected_rows = [
            {k: row[k] for k in ("run_id", "turn", "sensor_id", "actual")}
            for row in report["models"]["decision_tree"]["test_predictions"]
        ]
        for model in report["models"].values():
            self.assertEqual(
                [{k: row[k] for k in ("run_id", "turn", "sensor_id", "actual")}
                 for row in model["test_predictions"]], expected_rows
            )

    def test_additional_models_fit_train_and_predict_same_test_rows(self):
        models = comparison._additional_models(2026)
        lr, rf = models["logistic_regression"], models["random_forest"]
        split = split_by_sensor(self.dataset)
        X_train = tuple(self.dataset.X[i] for i in split.train_indices)
        y_train = tuple(self.dataset.y[i] for i in split.train_indices)
        X_test = tuple(self.dataset.X[i] for i in split.test_indices)
        with (
            patch.object(lr, "fit", wraps=lr.fit) as lr_fit,
            patch.object(rf, "fit", wraps=rf.fit) as rf_fit,
            patch.object(lr, "predict", wraps=lr.predict) as lr_predict,
            patch.object(rf, "predict", wraps=rf.predict) as rf_predict,
            patch.object(comparison, "_additional_models", return_value=models),
        ):
            comparison.compare_models(self.folder)
        for fit in (lr_fit, rf_fit):
            fit.assert_called_once_with(X_train, y_train)
        for predict in (lr_predict, rf_predict):
            predict.assert_called_once_with(X_test)

    def test_scaler_statistics_come_from_training_only(self):
        models = comparison._additional_models(2026)
        with patch.object(comparison, "_additional_models", return_value=models):
            report = comparison.compare_models(self.folder)
        scaler = models["logistic_regression"].named_steps["scaler"]
        split = split_by_sensor(self.dataset)
        for column in range(3):
            expected_mean = mean(self.dataset.X[i][column] for i in split.train_indices)
            self.assertAlmostEqual(float(scaler.mean_[column]), expected_mean)
        self.assertEqual(int(scaler.n_samples_seen_), len(split.train_indices))
        self.assertNotAlmostEqual(float(scaler.mean_[0]), mean(row[0] for row in self.dataset.X))
        self.assertEqual(
            report["models"]["logistic_regression"]["diagnostics"]["scaler_mean"],
            scaler.mean_.tolist(),
        )

    def test_changing_test_features_does_not_change_fitted_diagnostics(self):
        before = comparison.compare_models(self.folder)
        test_sensors = set(before["split"]["test_sensors"])
        rows = read_sensor_package(self.folder)["labelled_rows"]
        changed = [
            {**row, "temperature_c": 500.0, "smoke_index": 1.0, "alarm": True}
            if row["sensor_id"] in test_sensors else row
            for row in rows
        ]
        export_sensor_dataset(changed, self.folder)
        after = comparison.compare_models(self.folder)
        self.assertEqual(after["split"], before["split"])
        for name in before["models"]:
            self.assertEqual(
                after["models"][name]["diagnostics"], before["models"][name]["diagnostics"]
            )
            self.assertEqual(
                after["models"][name]["parameters"], before["models"][name]["parameters"]
            )

    def test_decision_tree_and_reference_match_p24(self):
        report = comparison.compare_models(self.folder)
        baseline = evaluate_baseline(self.folder)
        self.assertEqual(report["split"], baseline["split"])
        self.assertEqual(report["models"]["decision_tree"]["metrics"], baseline["metrics"])
        self.assertEqual(
            report["models"]["decision_tree"]["test_predictions"], baseline["test_predictions"]
        )
        self.assertEqual(report["majority_reference"], baseline["majority_reference"])
        self.assertEqual(report["source"], baseline["source"])
        self.assertEqual(report["environment"], baseline["environment"])

    def test_every_confusion_matrix_matches_saved_predictions(self):
        report = comparison.compare_models(self.folder)
        for name, model in report["models"].items():
            with self.subTest(model=name):
                rows = model["test_predictions"]
                matrix = [
                    [sum(row["actual"] == actual and row["predicted"] == predicted
                         for row in rows) for predicted in (False, True)]
                    for actual in (False, True)
                ]
                self.assertEqual(model["metrics"]["confusion_matrix"], matrix)
                self.assertEqual(sum(sum(row) for row in matrix), 108)
                for metric in ("accuracy", "precision", "recall", "f1"):
                    self.assertGreaterEqual(model["metrics"][metric], 0)
                    self.assertLessEqual(model["metrics"][metric], 1)

    def test_parameters_are_fixed_and_no_winner_is_selected(self):
        report = comparison.compare_models(self.folder)
        lr, rf = report["models"]["logistic_regression"], report["models"]["random_forest"]
        self.assertEqual(lr["parameters"]["max_iter"], 2000)
        self.assertEqual(lr["parameters"]["solver"], "lbfgs")
        self.assertEqual(lr["parameters"]["C"], 1.0)
        self.assertEqual(rf["parameters"]["n_estimators"], 100)
        self.assertEqual(rf["parameters"]["max_depth"], 3)
        self.assertEqual(rf["parameters"]["n_jobs"], 1)
        self.assertEqual(rf["diagnostics"]["fitted_tree_count"], 100)
        for model in report["models"].values():
            self.assertEqual(model["parameters"]["random_state"], 2026)
            self.assertEqual(model["parameters"]["class_weight"], "balanced")
        self.assertIsNone(report["selection"]["selected_model"])
        self.assertIn("P2.4", report["selection"]["reason"])

    def test_fit_warnings_are_preserved(self):
        original_fit = LogisticRegression.fit

        def fit_with_warning(model, X, y, *args, **kwargs):
            warnings.warn("Aviso inyectado por prueba", ConvergenceWarning)
            return original_fit(model, X, y, *args, **kwargs)

        with patch.object(LogisticRegression, "fit", new=fit_with_warning):
            report = comparison.compare_models(self.folder)
        logistic = report["models"]["logistic_regression"]
        self.assertFalse(logistic["diagnostics"]["converged"])
        self.assertTrue(any(
            notice["category"] == "ConvergenceWarning"
            and "inyectado" in notice["message"] for notice in logistic["fit_warnings"]
        ))

    def test_reproducible_and_read_only(self):
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        report = comparison.compare_models(self.folder)
        self.assertEqual(comparison.compare_models(self.folder), report)
        self.assertEqual({path.name: path.read_bytes() for path in self.folder.iterdir()}, before)
        self.assertEqual(json.loads(json.dumps(report, allow_nan=False)), report)

    def test_invalid_package_is_rejected_before_additional_training(self):
        (self.folder / "lecturas_sensores.jsonl").write_text("", encoding="utf-8")
        with patch.object(comparison, "_additional_models") as factory:
            with self.assertRaises(ValueError):
                comparison.compare_models(self.folder)
            factory.assert_not_called()

    def test_target_cannot_be_added_as_feature(self):
        with patch(
            "persona2.dataset.FEATURE_COLUMNS",
            ("temperature_c", "smoke_index", "alarm", "fire_within_2_cells"),
        ):
            with self.assertRaisesRegex(ValueError, "target.*no puede"):
                comparison.compare_models(self.folder)

    def test_changed_package_between_reads_is_rejected(self):
        original_load = comparison.load_sensor_dataset

        def load_and_change(*args, **kwargs):
            dataset = original_load(*args, **kwargs)
            path = self.folder / "manifiesto_sensores.json"
            path.write_bytes(path.read_bytes() + b"\n")
            return dataset

        with patch.object(comparison, "load_sensor_dataset", side_effect=load_and_change):
            with self.assertRaisesRegex(ValueError, "paquete cambio"):
                comparison.compare_models(self.folder)

    def test_sensor_configuration_is_forwarded(self):
        config = json.loads((ROOT / "data/sensores_paso_13.json").read_text("utf-8"))
        config["sensors"][0]["x"] = 150
        path = self.root / "sensors.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sensor no coincide"):
            comparison.compare_models(self.folder, sensors_path=path)

    def test_cli_default_does_not_write(self):
        before = sorted(path.name for path in self.root.iterdir())
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), comparison.compare_models(self.folder))
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), before)

    def test_cli_writes_matching_reports(self):
        output = self.root / "reports"
        result = self.cli("--output-dir", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            json.loads((output / "informe_comparacion.json").read_text("utf-8")), report
        )
        markdown = (output / "informe_comparacion.md").read_text("utf-8")
        self.assertEqual(markdown, comparison.render_report(report))
        for name in ("LogisticRegression", "DecisionTreeClassifier", "RandomForestClassifier"):
            self.assertIn(name, markdown)
        self.assertIn("holdout ya observado", markdown)

    def test_invalid_package_produces_no_reports(self):
        (self.folder / "lecturas_sensores.jsonl").write_text("", encoding="utf-8")
        output = self.root / "reports"
        result = self.cli("--output-dir", output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
