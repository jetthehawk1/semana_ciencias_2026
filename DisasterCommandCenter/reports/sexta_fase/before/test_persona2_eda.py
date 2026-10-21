"""P2.3: calculos verificables sobre un paquete pequeno y el ejemplo real."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from generar_entrega_persona2_15_1 import produce
from integration.sensor_export import COLUMNS, export_sensor_dataset
from persona2.eda import analyze_sensor_package, render_report


class SensorEdaTests(unittest.TestCase):
    def setUp(self):
        self.workspace = TemporaryDirectory(prefix="dcc_p23_")
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.folder = self.root / "package"
        self.config = self.root / "sensors.json"
        sensors = [
            {"sensor_id": "TEST-A", "x": 0, "y": 0, "building_id": None},
            {"sensor_id": "TEST-B", "x": 1, "y": 0, "building_id": None},
        ]
        self.config.write_text(
            json.dumps({"schema_version": "1.0", "sensors": sensors}), encoding="utf-8"
        )
        self.rows = [
            {
                "schema_version": "1.0", "run_id": "synthetic_unit_test",
                "turn": i // 2, **sensors[i % 2],
                "temperature_c": 20 + i * 10, "smoke_index": i * 0.25,
                "alarm": i >= 2, "fire_within_2_cells": i == 3,
            }
            for i in range(4)
        ]
        export_sensor_dataset(self.rows, self.folder)

    def analyze(self):
        return analyze_sensor_package(self.folder, sensors_path=self.config)

    def cli(self, *args):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run(
            [sys.executable, "-B", "-m", "persona2.eda", str(self.folder),
             "--sensors-path", str(self.config), *map(str, args)],
            cwd=self.root, env=env, capture_output=True, text=True,
            encoding="utf-8", timeout=30,
        )

    def test_known_counts_and_coverage(self):
        report = self.analyze()
        self.assertEqual(
            report["summary"],
            {"records": 4, "sensor_count": 2, "turn_count": 2, "first_turn": 0,
             "last_turn": 1, "feature_count": 3, "missing_required_values": 0,
             "allowed_null_values": 4},
        )
        self.assertEqual(report["records_by_turn"], {"0": 2, "1": 2})
        self.assertEqual(report["by_sensor"]["TEST-A"]["target_counts"],
                         {"false": 2, "true": 0})
        self.assertEqual(report["by_sensor"]["TEST-B"]["target_counts"],
                         {"false": 1, "true": 1})

    def test_known_statistics(self):
        report = self.analyze()
        temperature = report["numeric_statistics"]["temperature_c"]
        self.assertEqual(temperature["count"], 4)
        self.assertEqual(temperature["min"], 20)
        self.assertEqual(temperature["max"], 50)
        self.assertEqual(temperature["mean"], 35)
        self.assertEqual(temperature["median"], 35)
        self.assertAlmostEqual(temperature["stddev_population"], math.sqrt(125))
        smoke = report["numeric_statistics"]["smoke_index"]
        self.assertEqual(smoke["min"], 0)
        self.assertEqual(smoke["max"], 0.75)
        self.assertEqual(smoke["mean"], 0.375)
        self.assertEqual(smoke["median"], 0.375)
        self.assertAlmostEqual(smoke["stddev_population"], math.sqrt(0.078125))

    def test_types_nulls_and_roles_after_p22(self):
        columns = self.analyze()["columns"]
        self.assertEqual(set(columns), set(COLUMNS))
        self.assertEqual(columns["temperature_c"]["types"], {"float": 4})
        self.assertEqual(columns["alarm"]["types"], {"int": 4})
        self.assertEqual(columns["fire_within_2_cells"]["types"], {"bool": 4})
        self.assertEqual(columns["sensor_id"]["types"], {"str": 4})
        self.assertEqual(columns["turn"]["types"], {"int": 4})
        self.assertEqual(columns["building_id"]["null_count"], 4)
        self.assertEqual(columns["building_id"]["allowed_null_count"], 4)
        self.assertEqual(columns["building_id"]["missing_required_count"], 0)
        self.assertEqual(columns["building_id"]["types"], {"NoneType": 4})
        self.assertEqual(columns["building_id"]["unique_non_null"], 0)
        self.assertEqual(columns["fire_within_2_cells"]["role"], "target")

    def test_known_class_and_alarm_distribution(self):
        report = self.analyze()
        self.assertEqual(report["target"]["counts"], {"false": 3, "true": 1})
        self.assertEqual(report["target"]["proportions"], {"false": .75, "true": .25})
        self.assertFalse(report["target"]["single_class"])
        self.assertFalse(report["target"]["imbalanced"])
        self.assertEqual(report["alarm_distribution"]["counts"], {"false": 2, "true": 2})

    def test_single_class_positive_and_negative(self):
        for label in (False, True):
            with self.subTest(label=label):
                rows = [{**row, "fire_within_2_cells": label} for row in self.rows]
                export_sensor_dataset(rows, self.folder)
                target = self.analyze()["target"]
                self.assertTrue(target["single_class"])
                self.assertTrue(target["imbalanced"])
                self.assertEqual(target["majority_fraction"], 1)
                self.assertEqual(target["counts"]["true"], 4 if label else 0)

    def test_imbalance_threshold_boundary(self):
        rows = [
            {**self.rows[0], "turn": turn, "fire_within_2_cells": turn < 4}
            for turn in range(5)
        ]
        self.config.write_text(
            json.dumps({"schema_version": "1.0", "sensors": [
                {"sensor_id": "TEST-A", "x": 0, "y": 0, "building_id": None}
            ]}), encoding="utf-8"
        )
        export_sensor_dataset(rows, self.folder)
        target = self.analyze()["target"]
        self.assertFalse(target["single_class"])
        self.assertTrue(target["imbalanced"])
        self.assertEqual(target["imbalance_threshold"], .8)
        self.assertEqual(target["majority_fraction"], .8)

    def test_one_observation_has_zero_population_stddev(self):
        rows = self.rows[:1]
        self.config.write_text(
            json.dumps({"schema_version": "1.0", "sensors": [
                {"sensor_id": "TEST-A", "x": 0, "y": 0, "building_id": None}
            ]}), encoding="utf-8"
        )
        export_sensor_dataset(rows, self.folder)
        report = self.analyze()
        self.assertEqual(report["summary"]["records"], 1)
        self.assertEqual(
            report["numeric_statistics"]["temperature_c"]["stddev_population"], 0
        )

    def test_required_missing_value_is_rejected(self):
        rows = deepcopy(self.rows)
        rows[0]["temperature_c"] = None
        export_sensor_dataset(rows, self.folder)
        with self.assertRaisesRegex(ValueError, "tipo o rango"):
            self.analyze()

    def test_analysis_is_read_only_and_deterministic(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        report = self.analyze()
        self.assertEqual(self.analyze(), report)
        self.assertEqual({p.name: p.read_bytes() for p in self.folder.iterdir()}, before)
        self.assertEqual(json.loads(json.dumps(report, allow_nan=False)), report)
        self.assertEqual(len(report["source"]["package_sha256"]), 3)

    def test_reordering_does_not_change_statistics(self):
        before = self.analyze()
        export_sensor_dataset(list(reversed(self.rows)), self.folder)
        after = self.analyze()
        for key in (
            "summary", "columns", "numeric_statistics", "target",
            "by_sensor", "records_by_turn", "alarm_distribution",
        ):
            self.assertEqual(after[key], before[key])

    def test_target_changes_do_not_change_feature_profiles_or_statistics(self):
        before = self.analyze()
        rows = [{**row, "fire_within_2_cells": False} for row in self.rows]
        export_sensor_dataset(rows, self.folder)
        after = self.analyze()
        self.assertEqual(after["feature_columns"], ["temperature_c", "smoke_index", "alarm"])
        self.assertEqual(after["numeric_statistics"], before["numeric_statistics"])
        for name in after["feature_columns"]:
            self.assertEqual(after["columns"][name], before["columns"][name])
        self.assertNotEqual(after["target"]["counts"], before["target"]["counts"])

    def test_markdown_contains_computed_results_and_notes(self):
        text = render_report(self.analyze())
        self.assertIn("| false | 3 | 75.00% |", text)
        self.assertIn("| true | 1 | 25.00% |", text)
        self.assertIn("| temperature_c | 4 | 20.000000 | 50.000000 | 35.000000 |", text)
        self.assertIn("Datos sinteticos", text)
        self.assertIn("building_id=None", text)

    def test_cli_default_does_not_write(self):
        before = sorted(p.name for p in self.root.iterdir())
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), self.analyze())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_cli_saves_matching_json_and_markdown(self):
        output = self.root / "reports"
        result = self.cli("--output-dir", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(
            json.loads((output / "informe_eda.json").read_text("utf-8")), report
        )
        self.assertEqual(
            (output / "informe_eda.md").read_text("utf-8"), render_report(report)
        )

    def test_cli_rejects_invalid_package_without_report(self):
        (self.folder / "lecturas_sensores.jsonl").write_text("", encoding="utf-8")
        output = self.root / "reports"
        result = self.cli("--output-dir", output)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(output.exists())

    def test_real_generated_package(self):
        real_folder = self.root / "real"
        original = produce(real_folder)
        report = analyze_sensor_package(real_folder)
        self.assertEqual(report["summary"]["records"], 432)
        self.assertEqual(report["summary"]["sensor_count"], 12)
        self.assertEqual(report["summary"]["turn_count"], 36)
        positives = sum(row["fire_within_2_cells"] for row in original["labelled_rows"])
        self.assertEqual(report["target"]["counts"], {"false": 432 - positives, "true": positives})
        self.assertEqual(sum(row["records"] for row in report["by_sensor"].values()), 432)
        self.assertEqual(sum(report["records_by_turn"].values()), 432)


if __name__ == "__main__":
    unittest.main(verbosity=2)
