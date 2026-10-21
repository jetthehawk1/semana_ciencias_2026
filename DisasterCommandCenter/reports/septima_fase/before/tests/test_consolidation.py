"""Regresiones de integracion estructural; no cambian las politicas de simulacion."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from integration.route_gateway import ExternalRouteFollower, build_route_request
from routing.astar import astar
from routing.congestion import CongestionManager
from routing.evacuation_optimizer import EvacuationOptimizer
from routing.evacuation_priority import EvacuationPriority
from routing.graph import CampusGraph
from routing.weighted_astar import weighted_astar
from simulation.campus_map import CampusMap
from simulation.person import Person
from simulation.person_manager import PersonManager
from tools.run_tests import run_suite


class RoutingCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.campus = CampusMap(5, 5)
        self.campus.fill_terrain("floor")
        self.graph = CampusGraph(self.campus)

    def test_both_astar_algorithms_accept_the_real_campus_graph(self):
        for algorithm in (astar, weighted_astar):
            with self.subTest(algorithm=algorithm.__name__):
                path = algorithm(self.graph, (0, 2), (4, 2))
                self.assertEqual(path[0], (0, 2))
                self.assertEqual(path[-1], (4, 2))
                self.assertEqual(len(path), 5)

    def test_graph_alias_keeps_terrain_and_cardinal_restrictions(self):
        self.campus.set_terrain(1, 2, "grass")
        self.campus.set_terrain(2, 1, "building")
        self.campus.set_terrain(3, 2, "road")
        self.assertEqual(self.graph.neighbors(2, 2), [(3, 2), (2, 3)])
        self.assertEqual(self.graph.neighbors(2, 2), self.graph.get_neighbors(2, 2))

    def test_weighted_route_avoids_congestion_without_changing_weights(self):
        congestion = CongestionManager()
        person = Person("crowd", 2, 2)
        congestion.update([person])
        path = weighted_astar(self.graph, (0, 2), (4, 2), congestion)
        direct = [(x, 2) for x in range(5)]
        cost = lambda route: sum(1 + congestion.get_cost(*cell) for cell in route[1:])
        self.assertLess(cost(path), cost(direct))
        self.assertEqual(person.position, (2, 2))

    def test_weighted_route_respects_obstacles_and_reports_no_route(self):
        blocked = [{"x": 2, "y": y} for y in range(5)]
        self.assertIsNone(weighted_astar(self.graph, (0, 2), (4, 2), blocked_cells=blocked))
        path = weighted_astar(self.graph, (0, 2), (4, 2), blocked_cells=[(2, 2)])
        self.assertNotIn((2, 2), path)

    def test_priority_preserves_existing_scores_and_order(self):
        priority = EvacuationPriority()
        ranked = priority.rank_people([
            {"person_id": "ordinary", "risk_level": "low"},
            {"person_id": "assisted", "needs_assistance": True},
            {"person_id": "critical", "risk_level": "critical"},
        ])
        self.assertEqual([item["person_id"] for item in ranked], ["critical", "assisted", "ordinary"])
        self.assertEqual(priority.get_priority("assisted"), 30)
        self.assertEqual(priority.get_priority("critical"), 60)

    def test_optimizer_routes_are_consumed_only_by_persona1_gateway(self):
        manager = PersonManager(5, 5, self.graph.is_valid)
        person = Person("P1", 0, 2)
        manager.add_person(person)
        request = build_route_request(manager, "test", {
            "P1": {"destination_id": "test-goal", "goal": {"x": 4, "y": 2}},
        }, blocked_cells=[(2, 2)])
        optimizer = EvacuationOptimizer(self.graph)
        result = optimizer.optimize(request, [person])
        self.assertEqual(result["failed"], [])
        self.assertEqual(person.position, (0, 2), "El optimizador no debe mover personas")
        self.assertEqual(request["people"][0]["start"], {"x": 0, "y": 2})
        follower = ExternalRouteFollower(manager, "test")
        follower.set_request(request)
        follower.set_blocked_cells(request["blocked_cells"])
        follower.submit_route(result["routes"][0])
        for point in result["routes"][0]["path"][1:]:
            self.assertEqual(follower.step(), 1)
            self.assertEqual(person.position, (point["x"], point["y"]))
            self.assertNotEqual(person.position, (2, 2))
        self.assertEqual(follower.route_status("P1"), "en_destino")
        self.assertNotEqual(person.status, "a_salvo")


class EntryPointTests(unittest.TestCase):
    def test_new_and_legacy_entry_points_work_outside_project_directory(self):
        env = {**os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy",
               "PYTHONDONTWRITEBYTECODE": "1"}
        with TemporaryDirectory(prefix="dcc_entry_") as temp:
            for name in ("main.py", "main_unificado_14_4_4.py"):
                with self.subTest(entry=name):
                    result = subprocess.run(
                        [sys.executable, "-B", str(ROOT / name), "--modo-original", "--smoke-test"],
                        cwd=temp, env=env, capture_output=True, text=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    expected = (sum(json.loads((ROOT / "data/functional/population.json").read_text())["building_counts"].values())
                                if name == "main.py" else 100)
                    self.assertIn(f"personas={expected}", result.stdout)
                    self.assertIn("sensores=12", result.stdout)


class TestRunnerTests(unittest.TestCase):
    def test_failing_script_does_not_hide_later_tests_or_modify_source(self):
        with TemporaryDirectory(prefix="dcc_runner_") as temp:
            root = Path(temp) / "app"
            root.mkdir()
            (root / "test_a_fail.py").write_text("raise AssertionError('visible failure')\n")
            (root / "test_b_write.py").write_text(
                "from pathlib import Path\nPath('generated.txt').write_text('copy only')\n"
            )
            captured = io.StringIO()
            with redirect_stdout(captured):
                report = run_suite(root, Path(temp) / "logs")
            self.assertEqual(report["summary"]["failed_scripts"], 1)
            self.assertEqual(report["summary"]["passed_scripts"], 1)
            self.assertFalse((root / "generated.txt").exists())
            log = Path(temp) / "logs" / report["scripts"][0]["log"]
            self.assertIn("visible failure", log.read_text())
            self.assertIn("[FAILED] test_a_fail.py", captured.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
