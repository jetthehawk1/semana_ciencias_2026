"""Cadena completa: simulador -> contrato observable -> IA -> PostgreSQL real."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
import uuid

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import psycopg
from psycopg import sql

from demo_persona2_integracion import run_demo
from generar_entrega_persona2_15_1 import produce
from integration.persona2_gateway import predict_sensor_readings
from integration.sensor_export import COLUMNS
from persona2.inference import train_prediction_service
from persona2.postgres_repository import PostgresRepository
from tools.postgres_test_server import PostgresTestServer
from tools.verify_persona2 import verify


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = PostgresTestServer().__enter__()
        cls.addClassCleanup(cls.server.__exit__, None, None, None)

    def setUp(self):
        self.schema = "dcc_p2_test_" + uuid.uuid4().hex
        self.repository = PostgresRepository(self.server.dsn, schema=self.schema)
        self.addCleanup(self.drop_schema)

    def drop_schema(self):
        if not re.fullmatch(r"dcc_p2_test_[0-9a-f]{32}", self.schema):
            raise ValueError("Esquema ajeno a la prueba.")
        with psycopg.connect(self.server.dsn) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema)))

    def test_live_simulation_predictions_and_postgres(self):
        report = run_demo(repository=self.repository)
        self.assertEqual(report["summary"]["predictions"], 432)
        self.assertEqual(report["summary"]["turn_count"], 36)
        self.assertEqual(report["summary"]["sensor_count"], 12)
        self.assertEqual(report["summary"]["predictions_while_paused"], 0)
        self.assertEqual(
            report["database"]["counts"],
            {"simulations": 1, "sensors": 12, "readings": 432,
             "events": 126, "predictions": 432, "reports": 1},
        )
        self.assertTrue(all("fire_within_2_cells" not in row for row in report["predictions"]))
        stored = self.repository.readings(report["source"]["run_id"])
        self.assertTrue(all(set(row) == set(COLUMNS) for row in stored))
        with TemporaryDirectory(prefix="dcc_db_inference_") as temp:
            package = Path(temp) / "training"
            produce(package)
            service = train_prediction_service(package)
            roundtrip = predict_sensor_readings(service, stored)
        expected = {
            (row["run_id"], row["turn"], row["sensor_id"]): row
            for row in report["predictions"]
        }
        self.assertEqual(
            {(row["run_id"], row["turn"], row["sensor_id"]): row for row in roundtrip},
            expected,
        )
        with self.repository._connect() as conn:
            self.assertEqual(conn.execute(self.repository._query(
                "SELECT count(*) FROM {schema}.models"
            )).fetchone()[0], 1)

    def test_repeated_demo_does_not_duplicate_data(self):
        first = run_demo(repository=self.repository)
        second = run_demo(repository=self.repository)
        self.assertFalse(second["database"]["import"]["inserted"])
        self.assertEqual(second["database"]["prediction_write"]["inserted"], 0)
        self.assertEqual(second["database"]["counts"], first["database"]["counts"])
        self.assertEqual(second["model"], first["model"])

    def test_complete_verification_saves_reports_and_metrics(self):
        with TemporaryDirectory(prefix="dcc_p27_verified_") as temp:
            result = verify(self.repository, temp)
            persisted = json.loads((Path(temp) / "informe_persistencia.json").read_text("utf-8"))
            integrated = json.loads((Path(temp) / "informe_integracion.json").read_text("utf-8"))
        self.assertEqual(persisted, result["persistence"])
        self.assertEqual(persisted["counts"]["reports"], 4)
        self.assertEqual(persisted["counts"]["predictions"], 432)
        self.assertEqual(len(integrated["predictions"]), 432)
        with self.repository._connect() as conn:
            report = conn.execute(self.repository._query(
                "SELECT report FROM {schema}.reports WHERE kind = 'comparison'"
            )).fetchone()[0]
        self.assertEqual(set(report["models"]), {"logistic_regression", "decision_tree", "random_forest"})

    def test_demo_preserves_original_source_and_data(self):
        paths = list((ROOT / "src/simulation").glob("*.py")) + list((ROOT / "data").glob("*.json"))
        before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
        run_demo()
        self.assertEqual(
            {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}, before
        )

    def test_cli_without_database_never_imports_database_driver(self):
        code = (
            "import sys; sys.path.insert(0,sys.argv[1]); sys.modules['psycopg']=None; "
            "from demo_persona2_integracion import run_demo; "
            "report=run_demo(); assert report['summary']['predictions']==432; "
            "assert 'database' not in report; assert 'pygame' not in sys.modules"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(ROOT)],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_persist_cli_requires_configuration_explicitly(self):
        env = os.environ.copy()
        env.pop("DCC_DATABASE_URL", None)
        result = subprocess.run(
            [sys.executable, "-B", str(ROOT / "demo_persona2_integracion.py"), "--persist"],
            env=env, capture_output=True, text=True, timeout=45,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DCC_DATABASE_URL", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
