"""P2.6: pruebas sobre PostgreSQL real en esquemas temporales exclusivos."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import psycopg
from psycopg import sql
from generar_entrega_persona2_15_1 import produce
from integration.sensor_export import export_sensor_dataset
from persona2.postgres_repository import PostgresRepository
from tools.postgres_test_server import PostgresTestServer


class RepositoryConfigurationTests(unittest.TestCase):
    def test_missing_configuration_is_explicit(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "DCC_DATABASE_URL"):
                PostgresRepository()

    def test_schema_name_cannot_be_sql(self):
        with self.assertRaisesRegex(ValueError, "esquema"):
            PostgresRepository("not-used", schema="public; DROP TABLE x")


class PostgresRepositoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = PostgresTestServer().__enter__()
        cls.addClassCleanup(cls.server.__exit__, None, None, None)
        cls.workspace = TemporaryDirectory(prefix="dcc_db_fixture_")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.base = Path(cls.workspace.name) / "package"
        cls.package = produce(cls.base)
        cls.run_id = cls.package["manifest"]["run_id"]

    def setUp(self):
        self.schema = "dcc_p2_test_" + uuid.uuid4().hex
        self.repository = PostgresRepository(self.server.dsn, schema=self.schema)
        self.repository.initialize()
        self.addCleanup(self.drop_test_schema)
        self.temp = TemporaryDirectory(prefix="dcc_db_case_")
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "package"
        shutil.copytree(self.base, self.folder)

    def drop_test_schema(self):
        if not re.fullmatch(r"dcc_p2_test_[0-9a-f]{32}", self.schema):
            raise ValueError("Solo se eliminan esquemas creados por esta prueba.")
        with psycopg.connect(self.server.dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def import_base(self, **kwargs):
        return self.repository.import_package(self.folder, **kwargs)

    def prediction(self, index=0, value=True):
        row = self.package["labelled_rows"][index]
        return {
            "run_id": row["run_id"], "turn": row["turn"], "sensor_id": row["sensor_id"],
            "model_id": "unit_test_model", "predicted_fire_within_2_cells": value,
        }

    def register_model(self):
        self.repository.register_model(
            "unit_test_model", {"feature_columns": ["temperature_c", "smoke_index", "alarm"]}
        )

    def test_initialize_is_repeatable(self):
        self.repository.initialize()
        self.assertEqual(self.repository.counts(self.run_id)["readings"], 0)

    def test_import_roundtrip_and_alarm_events(self):
        result = self.import_base()
        self.assertTrue(result["inserted"])
        self.assertEqual(result["original_records"], 432)
        self.assertEqual(result["stored_readings"], 432)
        counts = self.repository.counts(self.run_id)
        self.assertEqual(counts["simulations"], 1)
        self.assertEqual(counts["sensors"], 12)
        self.assertEqual(counts["readings"], 432)
        self.assertEqual(counts["events"], sum(row["alarm"] for row in self.package["labelled_rows"]))
        stored = self.repository.readings(self.run_id)
        expected = sorted(self.package["labelled_rows"], key=lambda r: (r["turn"], r["sensor_id"]))
        for actual, original in zip(stored, expected):
            self.assertEqual(actual, {key: original[key] for key in actual})
        self.assertTrue(any(row["building_id"] is None for row in stored))

    def test_repeated_import_is_idempotent(self):
        self.import_base()
        before = self.repository.counts(self.run_id)
        repeated = self.import_base()
        self.assertFalse(repeated["inserted"])
        self.assertEqual(self.repository.counts(self.run_id), before)

    def test_conflicting_run_is_rejected_without_changes(self):
        self.import_base()
        before = self.repository.counts(self.run_id)
        rows = deepcopy(self.package["labelled_rows"])
        rows[0]["temperature_c"] += 1
        export_sensor_dataset(rows, self.folder, metadata=self.package["manifest"]["metadata"])
        with self.assertRaisesRegex(ValueError, "run_id ya existe"):
            self.import_base()
        self.assertEqual(self.repository.counts(self.run_id), before)
        stored = {(row["turn"], row["sensor_id"]): row for row in self.repository.readings(self.run_id)}
        original = self.package["labelled_rows"][0]
        self.assertEqual(
            stored[(original["turn"], original["sensor_id"])]["temperature_c"],
            original["temperature_c"],
        )

    def test_sampling_retains_alarms_and_boundaries(self):
        result = self.import_base(every_n_turns=5)
        stored = self.repository.readings(self.run_id)
        self.assertLess(len(stored), 432)
        self.assertEqual(result["stored_readings"], len(stored))
        self.assertEqual(result["original_records"], 432)
        keys = {(row["turn"], row["sensor_id"]) for row in stored}
        self.assertTrue(all(
            (row["turn"], row["sensor_id"]) in keys
            for row in self.package["labelled_rows"] if row["alarm"] or row["turn"] in (0, 35)
        ))
        self.assertTrue(all(
            row["turn"] % 5 == 0 or row["turn"] == 35 or row["alarm"] for row in stored
        ))

    def test_sampling_policy_cannot_silently_change(self):
        self.import_base(every_n_turns=5)
        before = self.repository.counts(self.run_id)
        with self.assertRaises(ValueError):
            self.import_base(every_n_turns=1)
        self.assertEqual(self.repository.counts(self.run_id), before)

    def test_invalid_package_or_sampling_writes_nothing(self):
        for interval in (0, -1, True, 1.5):
            with self.subTest(interval=interval):
                with self.assertRaises(ValueError):
                    self.import_base(every_n_turns=interval)
        (self.folder / "lecturas_sensores.jsonl").write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.import_base()
        self.assertEqual(self.repository.counts(self.run_id)["simulations"], 0)

    def test_identifiers_are_bound_parameters(self):
        hostile_id = "run'; DROP SCHEMA public; --"
        rows = [{**row, "run_id": hostile_id} for row in self.package["labelled_rows"]]
        export_sensor_dataset(rows, self.folder)
        result = self.import_base()
        self.assertEqual(result["run_id"], hostile_id)
        self.assertEqual(self.repository.counts(hostile_id)["readings"], 432)

    def test_reports_are_persisted_idempotently(self):
        self.import_base()
        report = {"source": {"run_id": self.run_id}, "metrics": {"recall": .5}}
        first = self.repository.save_report(self.run_id, "baseline", report)
        self.assertEqual(self.repository.save_report(self.run_id, "baseline", report), first)
        self.assertEqual(self.repository.counts(self.run_id)["reports"], 1)
        with self.assertRaises(ValueError):
            self.repository.save_report(self.run_id, "baseline", {"source": None})
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.repository.save_report("missing", "baseline", {"source": {"run_id": "missing"}})
        self.assertEqual(self.repository.counts(self.run_id)["reports"], 1)

    def test_model_metadata_conflict_is_rejected(self):
        self.register_model()
        self.register_model()
        with self.assertRaisesRegex(ValueError, "model_id"):
            self.repository.register_model("unit_test_model", {"different": True})

    def test_prediction_idempotency_and_atomic_conflict(self):
        self.import_base()
        self.register_model()
        initial = self.prediction()
        self.assertEqual(self.repository.save_predictions([initial])["inserted"], 1)
        self.assertEqual(self.repository.save_predictions([initial])["inserted"], 0)
        with self.assertRaisesRegex(ValueError, "otro valor"):
            self.repository.save_predictions([
                self.prediction(index=1), self.prediction(value=False)
            ])
        self.assertEqual(self.repository.counts(self.run_id)["predictions"], 1)

    def test_prediction_foreign_keys_rollback_the_whole_batch(self):
        self.import_base()
        self.register_model()
        missing = {**self.prediction(index=1), "turn": 999}
        with self.assertRaises(psycopg.errors.ForeignKeyViolation):
            self.repository.save_predictions([self.prediction(), missing])
        self.assertEqual(self.repository.counts(self.run_id)["predictions"], 0)

    def test_invalid_prediction_batch_does_not_write(self):
        self.import_base()
        self.register_model()
        for predictions in (
            [], [self.prediction(), self.prediction()],
            [{**self.prediction(), "predicted_fire_within_2_cells": 1}],
            [{**self.prediction(), "turn": True}],
            [{**self.prediction(), "sensor_id": {}}],
        ):
            with self.subTest(predictions=predictions):
                with self.assertRaises(ValueError):
                    self.repository.save_predictions(predictions)
        self.assertEqual(self.repository.counts(self.run_id)["predictions"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
