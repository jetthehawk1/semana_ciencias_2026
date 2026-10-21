"""P2.2: alineacion tabular y prevencion de leakage con paquetes sinteticos."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
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
from integration.sensor_export import COLUMNS, export_sensor_dataset
from persona2.dataset import load_sensor_dataset


class SensorDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = TemporaryDirectory(prefix="dcc_p22_")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.base = Path(cls.workspace.name) / "base"
        cls.expected = produce(cls.base)

    def setUp(self):
        self.case = TemporaryDirectory(prefix="dcc_p22_case_")
        self.addCleanup(self.case.cleanup)
        self.folder = Path(self.case.name) / "package"
        shutil.copytree(self.base, self.folder)

    def test_real_package_shapes_and_column_roles(self):
        dataset = load_sensor_dataset(self.folder)
        self.assertEqual(
            dataset.feature_columns, ("temperature_c", "smoke_index", "alarm")
        )
        self.assertEqual(dataset.target_column, "fire_within_2_cells")
        self.assertEqual(
            dataset.metadata_columns,
            ("schema_version", "run_id", "turn", "sensor_id", "x", "y", "building_id"),
        )
        self.assertEqual(len(dataset.X), 432)
        self.assertEqual(len(dataset.y), 432)
        self.assertEqual(len(dataset.metadata_rows), 432)
        self.assertTrue(all(len(row) == 3 for row in dataset.X))
        self.assertTrue(all(len(row) == 7 for row in dataset.metadata_rows))
        self.assertEqual(
            set(dataset.feature_columns) | set(dataset.metadata_columns)
            | {dataset.target_column}, set(COLUMNS)
        )
        self.assertTrue(set(dataset.feature_columns).isdisjoint(dataset.metadata_columns))
        self.assertNotIn("fire_within_2_cells", dataset.feature_columns)
        self.assertNotIn("fire_within_2_cells", dataset.metadata_columns)

    def test_values_types_and_alignment(self):
        dataset = load_sensor_dataset(self.folder)
        for i, original in enumerate(self.expected["labelled_rows"]):
            with self.subTest(row=i):
                self.assertEqual(
                    dataset.X[i],
                    (original["temperature_c"], original["smoke_index"],
                     int(original["alarm"])),
                )
                self.assertIs(type(dataset.X[i][0]), float)
                self.assertIs(type(dataset.X[i][1]), float)
                self.assertIs(type(dataset.X[i][2]), int)
                self.assertIn(dataset.X[i][2], (0, 1))
                self.assertIs(type(dataset.y[i]), bool)
                self.assertEqual(dataset.y[i], original["fire_within_2_cells"])
                context = dict(zip(dataset.metadata_columns, dataset.metadata_rows[i]))
                self.assertEqual(
                    context, {key: original[key] for key in dataset.metadata_columns}
                )

    def test_labels_do_not_influence_features(self):
        before = load_sensor_dataset(self.folder)
        changed_rows = [
            {**row, "fire_within_2_cells": not row["fire_within_2_cells"]}
            for row in self.expected["labelled_rows"]
        ]
        export_sensor_dataset(
            changed_rows, self.folder, metadata=self.expected["manifest"]["metadata"]
        )
        after = load_sensor_dataset(self.folder)
        self.assertEqual(after.X, before.X)
        self.assertEqual(after.metadata_rows, before.metadata_rows)
        self.assertEqual(after.feature_columns, before.feature_columns)
        self.assertEqual(after.y, tuple(not label for label in before.y))

    def test_target_in_feature_selection_is_rejected(self):
        for features in (
            ("temperature_c", "smoke_index", "alarm", "fire_within_2_cells"),
            COLUMNS,
        ):
            with self.subTest(features=features):
                with patch("persona2.dataset.FEATURE_COLUMNS", features):
                    with self.assertRaisesRegex(ValueError, "target.*no puede"):
                        load_sensor_dataset(self.folder)

    def test_invalid_feature_selection_is_rejected(self):
        for features in (
            (), ("temperature_c", "temperature_c"), ("temperature_c", "inventado"),
        ):
            with self.subTest(features=features):
                with patch("persona2.dataset.FEATURE_COLUMNS", features):
                    with self.assertRaisesRegex(ValueError, "observables unicos"):
                        load_sensor_dataset(self.folder)

    def test_reordered_input_stays_aligned(self):
        rows = list(reversed(self.expected["labelled_rows"]))
        export_sensor_dataset(rows, self.folder)
        dataset = load_sensor_dataset(self.folder)
        for i, row in enumerate(rows):
            context = dict(zip(dataset.metadata_columns, dataset.metadata_rows[i]))
            self.assertEqual(
                (context["run_id"], context["turn"], context["sensor_id"]),
                (row["run_id"], row["turn"], row["sensor_id"]),
            )
            self.assertEqual(dataset.y[i], row["fire_within_2_cells"])
            self.assertEqual(
                dataset.X[i],
                (row["temperature_c"], row["smoke_index"], int(row["alarm"])),
            )

    def test_short_valid_package_is_not_padded(self):
        rows = [row for row in self.expected["labelled_rows"] if row["turn"] == 0]
        export_sensor_dataset(rows, self.folder)
        dataset = load_sensor_dataset(self.folder)
        self.assertEqual(len(dataset.X), 12)
        self.assertEqual(len(dataset.y), 12)
        self.assertEqual(len(dataset.metadata_rows), 12)
        self.assertEqual(dataset.manifest["records"], 12)
        self.assertEqual(dataset.manifest["turn_count"], 1)

    def test_null_building_is_preserved_in_metadata(self):
        dataset = load_sensor_dataset(self.folder)
        contexts = [
            dict(zip(dataset.metadata_columns, row)) for row in dataset.metadata_rows
        ]
        exterior = [row for row in contexts if row["sensor_id"].startswith("S-EXT-")]
        self.assertEqual(len(exterior), 72)
        self.assertTrue(all(row["building_id"] is None for row in exterior))
        self.assertTrue(all(value is not None for row in dataset.X for value in row))

    def test_input_files_and_manifest_are_preserved(self):
        before = {path.name: path.read_bytes() for path in self.folder.iterdir()}
        dataset = load_sensor_dataset(str(self.folder))
        self.assertEqual(dataset.manifest, self.expected["manifest"])
        self.assertEqual(dataset.manifest["dataset_kind"], "synthetic_simulation")
        self.assertEqual(
            dataset.manifest["time_unit"], "simulation_turn_not_seconds"
        )
        self.assertEqual(
            {path.name: path.read_bytes() for path in self.folder.iterdir()}, before
        )

    def test_tables_cannot_be_reordered_in_place(self):
        dataset = load_sensor_dataset(self.folder)
        with self.assertRaises(TypeError):
            dataset.X[0][0] = 100
        with self.assertRaises(TypeError):
            dataset.y[0] = False
        with self.assertRaises(FrozenInstanceError):
            dataset.X = ()

    def test_invalid_package_is_rejected_before_transformation(self):
        path = self.folder / "manifiesto_sensores.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["records"] = 999
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Conteos"):
            load_sensor_dataset(self.folder)

    def test_sensor_configuration_is_forwarded(self):
        config = json.loads((ROOT / "data/sensores_paso_13.json").read_text("utf-8"))
        config["sensors"][0]["x"] = 150
        path = Path(self.case.name) / "sensors.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sensor no coincide"):
            load_sensor_dataset(self.folder, sensors_path=path)

    def test_runtime_import_is_independent_of_simulator_and_ml_libraries(self):
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from persona2.dataset import load_sensor_dataset; "
            "data = load_sensor_dataset(sys.argv[2]); "
            "assert len(data.X) == len(data.y) == 432; "
            "assert not any(k.split('.')[0] in "
            "{'pygame', 'simulation', 'dcc_app', 'pandas', 'numpy', 'sklearn'} "
            "for k in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(ROOT / "src"), str(self.folder)],
            cwd=self.case.name, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
