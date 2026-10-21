"""Puente de integracion: target descartado, pausa, reinicio y errores."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from generar_entrega_persona2_15_1 import produce
from integration.persona2_contract_15_1 import OBSERVABLE_FIELDS
from integration.persona2_gateway import SensorPredictionAdapter, predict_sensor_readings


class Provider:
    def __init__(self):
        self.calls = []
        self.fail = False

    def predict_many(self, rows):
        if self.fail:
            raise ValueError("Fallo de prueba")
        self.calls.append(deepcopy(rows))
        return [{"sensor_id": row["sensor_id"], "turn": row["turn"]} for row in rows]


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory(prefix="dcc_p27_gateway_")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.rows = produce(Path(cls.temp.name) / "package")["labelled_rows"][:12]

    def setUp(self):
        self.provider = Provider()
        self.adapter = SensorPredictionAdapter(self.provider)
        self.scene = SimpleNamespace(current_readings=deepcopy(self.rows))

    def test_label_is_removed_and_cannot_influence_provider(self):
        original = deepcopy(self.scene.current_readings)
        first = predict_sensor_readings(self.provider, self.scene.current_readings)
        changed = [{**row, "fire_within_2_cells": not row["fire_within_2_cells"]} for row in self.rows]
        second = predict_sensor_readings(self.provider, changed)
        self.assertEqual(first, second)
        self.assertEqual(self.provider.calls[0], self.provider.calls[1])
        self.assertEqual(self.scene.current_readings, original)
        self.assertTrue(all(set(row) == set(OBSERVABLE_FIELDS) for row in self.provider.calls[0]))

    def test_observable_only_rows_are_accepted(self):
        rows = [{k: row[k] for k in OBSERVABLE_FIELDS} for row in self.rows]
        self.assertEqual(len(predict_sensor_readings(self.provider, rows)), 12)

    def test_unknown_or_missing_fields_are_rejected(self):
        for rows in ([], [{}], [{**self.rows[0], "co": 10}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                predict_sensor_readings(self.provider, rows)

    def test_empty_scene_does_not_call_provider(self):
        self.scene.current_readings = []
        self.assertEqual(self.adapter.update(self.scene), [])
        self.assertEqual(self.provider.calls, [])

    def test_same_turn_is_not_processed_twice(self):
        self.assertEqual(len(self.adapter.update(self.scene)), 12)
        self.assertEqual(self.adapter.update(self.scene), [])
        self.scene.current_readings = [{**row, "turn": 1} for row in self.rows]
        self.assertEqual(len(self.adapter.update(self.scene)), 12)
        self.assertEqual(len(self.provider.calls), 2)

    def test_modified_same_turn_and_retrograde_turn_are_rejected(self):
        self.adapter.update(self.scene)
        self.scene.current_readings[0]["temperature_c"] += 1
        with self.assertRaisesRegex(ValueError, "modificadas"):
            self.adapter.update(self.scene)
        self.scene.current_readings = [{**row, "turn": 2} for row in self.rows]
        self.adapter.update(self.scene)
        self.scene.current_readings = [{**row, "turn": 1} for row in self.rows]
        with self.assertRaisesRegex(ValueError, "retrocedido"):
            self.adapter.update(self.scene)

    def test_new_run_can_start_at_turn_zero(self):
        self.adapter.update(self.scene)
        self.scene.current_readings = [{**row, "run_id": "new_run"} for row in self.rows]
        self.assertEqual(len(self.adapter.update(self.scene)), 12)

    def test_mixed_turns_are_rejected(self):
        self.scene.current_readings[1]["turn"] = 1
        with self.assertRaisesRegex(ValueError, "una ejecucion y un turno"):
            self.adapter.update(self.scene)

    def test_failure_does_not_mark_turn_processed(self):
        self.provider.fail = True
        with self.assertRaises(ValueError):
            self.adapter.update(self.scene)
        self.provider.fail = False
        self.assertEqual(len(self.adapter.update(self.scene)), 12)

    def test_gateway_import_needs_no_ml_db_or_pygame(self):
        code = (
            "import sys; sys.path.insert(0,sys.argv[1]); import integration.persona2_gateway; "
            "assert not any(k.split('.')[0] in "
            "{'pygame','sklearn','psycopg','simulation','dcc_app'} for k in sys.modules)"
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(ROOT / "src")],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
