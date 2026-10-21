"""P2.1: pruebas de recepcion con paquetes reales y copias temporales."""
from __future__ import annotations

from copy import deepcopy
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from generar_entrega_persona2_15_1 import produce
from integration.persona2_contract_15_1 import OBSERVABLE_FIELDS
from integration.sensor_export import COLUMNS
from persona2.ingestion import read_sensor_package


class SensorIngestionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = TemporaryDirectory(prefix="dcc_p21_")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.base = Path(cls.workspace.name) / "base"
        cls.expected = produce(cls.base)

    def setUp(self):
        self.case = TemporaryDirectory(prefix="dcc_p21_case_")
        self.addCleanup(self.case.cleanup)
        self.folder = Path(self.case.name) / "package"
        shutil.copytree(self.base, self.folder)

    def rewrite_rows(self, rows):
        """Altera ambos formatos para alcanzar la validacion de contenido.

        Permite NaN/Infinity deliberadamente para probar su rechazo. Esta
        funcion solo escribe paquetes de prueba dentro de carpetas temporales.
        """
        (self.folder / "lecturas_sensores.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        with (self.folder / "lecturas_sensores.csv").open(
            "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.DictWriter(file, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(
                {key: "" if value is None else value for key, value in row.items()}
                for row in rows
            )

    def test_real_package_and_input_files_unchanged(self):
        before = {p.name: p.read_bytes() for p in self.folder.iterdir()}
        info = read_sensor_package(str(self.folder))
        self.assertEqual(info, self.expected)
        self.assertEqual(len(info["observables"]), 432)
        self.assertEqual(info["manifest"]["sensor_count"], 12)
        self.assertEqual(info["manifest"]["turn_count"], 36)
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.folder.iterdir()}, before
        )

    def test_target_is_separate_and_rows_do_not_alias(self):
        info = read_sensor_package(self.folder)
        self.assertEqual(set(info), {"manifest", "observables", "labelled_rows"})
        for observable, labelled in zip(info["observables"], info["labelled_rows"]):
            self.assertEqual(set(observable), set(OBSERVABLE_FIELDS))
            self.assertNotIn("fire_within_2_cells", observable)
            self.assertIs(type(labelled["fire_within_2_cells"]), bool)
        info["observables"][0]["temperature_c"] = 999
        self.assertNotEqual(info["labelled_rows"][0]["temperature_c"], 999)

    def test_each_field_is_required(self):
        for field in COLUMNS:
            with self.subTest(field=field):
                rows = deepcopy(self.expected["labelled_rows"])
                del rows[0][field]
                self.rewrite_rows(rows)
                with self.assertRaisesRegex(ValueError, "campos JSONL"):
                    read_sensor_package(self.folder)

    def test_unexpected_field_is_rejected(self):
        path = self.folder / "lecturas_sensores.jsonl"
        rows = deepcopy(self.expected["labelled_rows"])
        rows[0]["extra"] = 1
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "campos JSONL"):
            read_sensor_package(self.folder)

    def test_null_is_rejected_except_building_id(self):
        for field in COLUMNS:
            if field == "building_id":
                continue
            with self.subTest(field=field):
                rows = deepcopy(self.expected["labelled_rows"])
                rows[0][field] = None
                self.rewrite_rows(rows)
                with self.assertRaisesRegex(ValueError, "tipo o rango"):
                    read_sensor_package(self.folder)

    def test_exterior_building_id_remains_none(self):
        info = read_sensor_package(self.folder)
        exterior = [
            row for row in info["observables"] if row["sensor_id"].startswith("S-EXT-")
        ]
        self.assertEqual(len(exterior), 72)
        self.assertTrue(all(row["building_id"] is None for row in exterior))

    def test_types_and_ranges(self):
        cases = {
            "schema_version": ["2.0", 1],
            "run_id": ["", "otro_ensayo"],
            "sensor_id": ["", 12],
            "turn": [True, "0", 0.5, -1],
            "x": [True, "1", -1, 160],
            "y": [False, 1.5, -1, 100],
            "building_id": ["", 12],
            "temperature_c": [True, "24", -50.01, 500.01],
            "smoke_index": [False, "0.3", -0.001, 1.001],
            "alarm": [0, 1, "False"],
            "fire_within_2_cells": [0, 1, "True"],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    rows = deepcopy(self.expected["labelled_rows"])
                    rows[0][field] = value
                    self.rewrite_rows(rows)
                    with self.assertRaisesRegex(ValueError, "tipo o rango"):
                        read_sensor_package(self.folder)

    def test_nonfinite_measurements(self):
        for field in ("temperature_c", "smoke_index"):
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(field=field, value=value):
                    rows = deepcopy(self.expected["labelled_rows"])
                    rows[0][field] = value
                    self.rewrite_rows(rows)
                    with self.assertRaisesRegex(ValueError, "Valor numerico no JSON"):
                        read_sensor_package(self.folder)

    def test_finite_numeric_limits_are_accepted(self):
        for temperature, smoke in ((-50, 0), (500, 1)):
            with self.subTest(temperature=temperature, smoke=smoke):
                rows = deepcopy(self.expected["labelled_rows"])
                rows[0].update(temperature_c=temperature, smoke_index=smoke)
                self.rewrite_rows(rows)
                info = read_sensor_package(self.folder)
                self.assertEqual(info["observables"][0]["temperature_c"], temperature)
                self.assertEqual(info["observables"][0]["smoke_index"], smoke)

    def test_identity_and_location_checked_by_default(self):
        for field, value in (
            ("sensor_id", "INVENTADO"), ("x", 150), ("y", 8),
            ("building_id", "E30"), ("building_id", None),
        ):
            with self.subTest(field=field, value=value):
                rows = deepcopy(self.expected["labelled_rows"])
                rows[0][field] = value
                self.rewrite_rows(rows)
                with self.assertRaisesRegex(ValueError, "sensor no coincide"):
                    read_sensor_package(self.folder)

    def test_explicit_sensor_configuration(self):
        config = json.loads((ROOT / "data/sensores_paso_13.json").read_text("utf-8"))
        config["sensors"][0]["x"] = 150
        path = Path(self.case.name) / "sensors.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "sensor no coincide"):
            read_sensor_package(self.folder, sensors_path=path)

    def test_duplicate_turn_sensor(self):
        rows = deepcopy(self.expected["labelled_rows"])
        rows[1] = dict(rows[0])
        self.rewrite_rows(rows)
        with self.assertRaisesRegex(ValueError, "Lectura duplicada"):
            read_sensor_package(self.folder)

    def test_missing_sensor_in_one_turn(self):
        rows = deepcopy(self.expected["labelled_rows"])
        del rows[0]
        self.rewrite_rows(rows)
        with self.assertRaisesRegex(ValueError, "Faltan sensores"):
            read_sensor_package(self.folder)

    def test_missing_turn(self):
        rows = [
            row for row in self.expected["labelled_rows"] if row["turn"] != 1
        ]
        self.rewrite_rows(rows)
        with self.assertRaisesRegex(ValueError, "Faltan turnos"):
            read_sensor_package(self.folder)

    def test_manifest_counts_and_provenance(self):
        for field, value in (
            ("records", 999), ("sensor_count", 11), ("turn_count", 35),
            ("first_turn", 1), ("last_turn", 36), ("records", True),
            ("dataset_kind", "real"), ("schema_version", "2.0"),
            ("time_unit", "seconds"), ("run_id", ""),
        ):
            with self.subTest(field=field):
                manifest = deepcopy(self.expected["manifest"])
                manifest[field] = value
                (self.folder / "manifiesto_sensores.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
                with self.assertRaises(ValueError):
                    read_sensor_package(self.folder)

    def test_divergent_csv_and_jsonl(self):
        path = self.folder / "lecturas_sensores.jsonl"
        rows = deepcopy(self.expected["labelled_rows"])
        rows[0]["temperature_c"] += 1
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "CSV/JSONL no coinciden"):
            read_sensor_package(self.folder)

    def test_missing_package_file(self):
        for filename in (
            "lecturas_sensores.csv", "lecturas_sensores.jsonl", "manifiesto_sensores.json"
        ):
            with self.subTest(filename=filename):
                path = self.folder / filename
                content = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(ValueError, "No se pudo abrir"):
                    read_sensor_package(self.folder)
                path.write_bytes(content)

    def test_empty_package(self):
        (self.folder / "lecturas_sensores.jsonl").write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "vacios o con cantidades"):
            read_sensor_package(self.folder)

    def test_import_and_default_configuration_from_another_directory(self):
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "from persona2.ingestion import read_sensor_package; "
            "assert not any(k.split('.')[0] in "
            "{'pygame', 'simulation', 'dcc_app'} for k in sys.modules); "
            "assert len(read_sensor_package(sys.argv[2])['observables']) == 432"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(ROOT / "src"), str(self.folder)],
            cwd=self.case.name, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
