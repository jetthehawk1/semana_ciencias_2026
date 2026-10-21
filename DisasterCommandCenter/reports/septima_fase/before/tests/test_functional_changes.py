"""Escenario detallado y controles de seguridad de su integracion real."""
from __future__ import annotations

from collections import Counter, deque
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from dcc_app.functional_application import FunctionalDisasterApp
from dcc_app.functional_scene import FunctionalScene
from dcc_app.model import load_campus
from integration.refined_sensor_view import source_sensor_environment
from persona2.ingestion import read_sensor_package
from routing.graph import CampusGraph
from routing.meeting_areas import MeetingArea, MeetingRouter
from simulation.building_risk import BuildingRisk
from simulation.campus_map import CampusMap
from simulation.indoor_people import IndoorPersonManager
from simulation.indoor_population import IndoorPopulationDistributor
from simulation.person import Person
from simulation.person_manager import PersonManager
from simulation.wind_history import WindHistory
from simulation.wind_simulation import Wind, WindSmokeSimulation
from tools.build_functional_scenario import build


class ScenarioDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = ROOT / "data/functional"
        cls.snapshot = load_campus(cls.data / "campus.json", cls.data / "building_entrances.json")
        cls.manager = IndoorPersonManager.from_json(cls.data / "campus.json")
        cls.distributor = IndoorPopulationDistributor(cls.manager, cls.data / "building_entrances.json")

    def test_real_grid_has_nine_times_more_cells(self):
        self.assertEqual((self.snapshot.width, self.snapshot.height), (480, 300))
        self.assertEqual(self.snapshot.building_count, 55)
        source = load_campus(ROOT / "data/campus.json", ROOT / "data/building_entrances.json")
        vegetation = {tuple(p) for p in json.loads((self.data / "vegetation.json").read_text())["cells_source"]}
        expected_counts = {key: count*9 for key, count in source.terrain_count.items()}
        expected_counts["floor"] -= len(vegetation)*9
        expected_counts["grass"] += len(vegetation)*9
        self.assertEqual(self.snapshot.terrain_count, expected_counts)
        for y, row in enumerate(source.terrain):
            for x, kind in enumerate(row):
                self.assertEqual(self.snapshot.terrain[3*y+1][3*x+1], "grass" if (x, y) in vegetation else kind)

    def test_population_30_to_50_fits_every_building(self):
        population = json.loads((self.data / "population.json").read_text())
        counts, areas = population["building_counts"], population["source_cell_areas"]
        self.assertEqual(set(counts), set(self.manager.building_ids))
        self.assertEqual(sum(counts.values()), 1879)
        for name, count in counts.items():
            self.assertTrue(30 <= count <= 50)
            self.assertLessEqual(count, self.distributor.capacity(name))
        ordered = sorted(counts, key=areas.get)
        self.assertEqual([counts[n] for n in ordered], sorted(counts.values()))

    def test_scaled_accesses_remain_cardinal_and_owned(self):
        document = json.loads((self.data / "building_entrances.json").read_text())
        doors = document["accesses"]
        self.assertEqual(len(doors), 3*sum(b["actual"] for b in document["exit_policy"]["buildings"].values()))
        for door in doors:
            inside, outside = door["interior_cell"], door["exterior_cell"]
            self.assertEqual(abs(inside["x"]-outside["x"])+abs(inside["y"]-outside["y"]), 1)
            self.assertEqual(self.manager.building_at(inside["x"], inside["y"]), door["building"])
            self.assertTrue(self.manager.is_transitable(outside["x"], outside["y"]))

    def test_generated_assets_are_reproducible_without_changing_source(self):
        with TemporaryDirectory(prefix="dcc_data_") as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "data", root / "data")
            before = (root / "data/campus.json").read_bytes()
            result = build(root)
            self.assertEqual(result["people"], 1879)
            self.assertEqual(before, (root / "data/campus.json").read_bytes())
            for path in self.data.glob("*.json"):
                self.assertEqual(path.read_bytes(), (root / "data/functional" / path.name).read_bytes())

    def test_exact_eleven_laboratories_are_structured(self):
        properties = json.loads((self.data / "building_properties.json").read_text())
        expected = {"E19", "E16", "E15", "E8", "E6", "E7", "E9", "E45", "E35", "E36", "E51"}
        self.assertEqual({name for name, p in properties.items() if p["laboratory"]}, expected)
        self.assertEqual({name for name, p in properties.items() if p["flammable_materials"]}, expected)

    def test_all_accesses_connect_to_the_meeting_network(self):
        start = (85*3, 36*3)
        reached, queue = {start}, deque([start])
        while queue:
            x, y = queue.popleft()
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                point = (x+dx, y+dy)
                if point not in reached and self.manager.is_transitable(*point):
                    reached.add(point)
                    queue.append(point)
        for name, x, y in self.snapshot.entrances:
            self.assertIn((x, y), reached, name)


class WindAndRiskTests(unittest.TestCase):
    def test_laboratory_escalates_before_comparable_normal_building(self):
        owners = [["E" if x == 0 and y == 0 else None for x in range(8)] for y in range(3)]
        lab = BuildingRisk(owners, {"E": {"laboratory": True, "flammable_materials": True}}, scale=1)
        normal = BuildingRisk(owners, {"E": {"laboratory": False, "flammable_materials": False}}, scale=1)
        self.assertEqual(lab.update({(4, 0)})["E"], "critical")
        self.assertEqual(normal.update({(4, 0)})["E"], "low")
        self.assertGreater(lab.scores({"P": "E"})["P"], normal.scores({"P": "E"})["P"])
        self.assertEqual(normal.update({(2, 0)})["E"], "high")

    def test_risk_clears_when_fire_is_no_longer_near(self):
        risk = BuildingRisk([["E"]], {"E": {"laboratory": True, "flammable_materials": True}}, scale=1)
        self.assertEqual(risk.update({(0, 0)})["E"], "critical")
        self.assertEqual(risk.update(set())["E"], "low")

    def test_wind_history_prediction_and_invalid_change_are_explicit(self):
        history = WindHistory("E", .75, history_limit=3)
        history.configure("N", .4, turn=1)
        history.record(2)
        self.assertEqual((history.predict_next().direction, history.predict_next().speed), ("N", .4))
        self.assertEqual(history.predict_next().turn, 3)
        before = list(history.history)
        with self.assertRaises(ValueError):
            history.configure("BAD", 1.2, turn=3)
        self.assertEqual(before, list(history.history))
        history.record(3)
        self.assertEqual(len(history.history), 3)

    def test_smoke_moves_with_wind_and_changes_direction(self):
        smoke = WindSmokeSimulation(7, 7, diffusion_rate=0, decay_rate=0, emission_rate=.1)
        smoke.concentrations[3][3] = 1
        smoke.set_wind(Wind("E", 1))
        smoke.step()
        self.assertGreater(smoke.concentrations[3][4], smoke.concentrations[3][3])
        smoke.set_wind(Wind("N", 1))
        smoke.step()
        self.assertGreater(smoke.concentrations[2][4], smoke.concentrations[3][4])
        self.assertAlmostEqual(sum(map(sum, smoke.concentrations)), 1)

    def test_more_concentration_produces_more_visual_darkening(self):
        import pygame
        scene = SimpleNamespace(environment=SimpleNamespace(smoke=SimpleNamespace(concentrations=[[0, .2, .8]])))
        layer = FunctionalDisasterApp._smoke_layer(pygame, scene, 3, 1)
        alpha = [layer.get_at((x, 0)).a for x in range(3)]
        self.assertEqual(alpha[0], 0)
        self.assertTrue(alpha[0] < alpha[1] < alpha[2])
        base = pygame.Surface((3, 1))
        base.fill((210, 210, 210))
        base.blit(layer, (0, 0))
        self.assertGreater(base.get_at((1, 0)).r, base.get_at((2, 0)).r)

    def test_subcell_smoke_is_not_just_cosmetic(self):
        smoke = WindSmokeSimulation(6, 3, diffusion_rate=0, decay_rate=0, emission_rate=.1)
        smoke.concentrations[1][0] = 1
        smoke.set_wind(Wind("E", 1))
        smoke.step()
        self.assertNotEqual(smoke.concentrations[1][0], smoke.concentrations[1][1])
        self.assertEqual(smoke.concentrations[1][2], 0)


class MeetingRouterTests(unittest.TestCase):
    def setUp(self):
        campus = CampusMap(9, 5)
        campus.fill_terrain("floor")
        self.campus = campus
        self.graph = CampusGraph(campus)
        self.manager = PersonManager(9, 5, self.graph.is_valid)
        self.person = Person("P", 1, 2)
        self.manager.add_person(self.person)
        self.areas = [MeetingArea("A", "test", "left", (3, 2, 1, 1), ((3, 2),)),
                      MeetingArea("B", "test", "right", (7, 2, 1, 1), ((7, 2),))]
        self.router = MeetingRouter(self.graph, self.manager, "test", self.areas)
        self.smoke = [[0.0]*9 for _ in range(5)]

    def advance(self, turn=1, blocked=()):
        eligible = {p.person_id for p in self.manager.list_people()}
        return self.router.advance(self.smoke, set(), set(blocked), {}, eligible, turn)

    def test_reassigns_even_after_arrival_when_meeting_area_smokes(self):
        self.advance(1); self.advance(2)
        self.assertEqual(self.person.position, (3, 2))
        self.assertEqual(self.router.gathered_count(), 1)
        self.smoke[2][3] = .4
        self.advance(3)
        self.assertEqual(self.router.assignments["P"][0], "B")
        self.assertEqual(self.person.position, (4, 2))
        for turn in range(4, 7):
            self.advance(turn)
        self.assertEqual(self.person.position, (7, 2))
        self.assertEqual(self.router.reassignments, 1)
        self.assertNotEqual(self.person.status, "a_salvo")

    def test_no_safe_area_means_wait_without_teleporting(self):
        self.smoke[2][3], self.smoke[2][7] = .4, .4
        self.assertEqual(self.advance(), 0)
        self.assertEqual(self.person.position, (1, 2))
        self.assertEqual(self.router.waiting, 1)

    def test_disabled_area_is_not_assigned(self):
        self.areas[0].enabled = False
        self.advance()
        self.assertEqual(self.router.assignments["P"][0], "B")

    def test_full_area_is_not_double_booked(self):
        self.manager.add_person(Person("Q", 1, 3))
        self.advance()
        goals = [goal for _, goal in self.router.assignments.values()]
        self.assertEqual(len(set(goals)), 2)

    def test_priority_changes_real_assignment_order_with_limited_budget(self):
        self.manager.add_person(Person("Z-lab", 1, 3))
        self.router.max_routes_per_turn = 1
        self.router.advance(self.smoke, set(), set(), {"Z-lab": 60}, {"P", "Z-lab"}, 1)
        self.assertEqual(self.router.last_planning_order, ["Z-lab"])
        self.assertIn("Z-lab", self.router.assignments)
        self.assertNotIn("P", self.router.assignments)

    def test_unreachable_closest_area_falls_back_to_reachable_area(self):
        self.person.x = 3
        self.areas[0].cells, self.areas[0].bounds = ((5, 2),), (5, 2, 1, 1)
        self.areas[1].cells, self.areas[1].bounds = ((0, 2),), (0, 2, 1, 1)
        for y in range(5):
            self.campus.set_terrain(4, y, "building")
        self.advance()
        self.assertEqual(self.router.assignments["P"][0], "B")

    def test_dynamic_blockage_replans_through_gateway(self):
        self.advance(1)
        self.assertEqual(self.person.position, (2, 2))
        self.advance(2, blocked={(3, 2)})
        self.assertEqual(self.router.assignments["P"][0], "B")
        self.assertNotEqual(self.person.position, (3, 2))


class FunctionalSceneIntegrationTests(unittest.TestCase):
    def test_population_routes_wind_pause_and_sensor_export_together(self):
        scene = FunctionalScene(ROOT, mode="optimizado")
        self.assertEqual(len(scene.people), 1879)
        self.assertEqual(len(scene.center.areas), 8)
        for area in scene.center.areas:
            self.assertTrue(all(scene.center.manager.is_transitable(*p) for p in area.cells))
        scene.start()
        self.assertEqual(len(scene.reading_history), 12)
        scene.toggle_pause()
        scene.step()
        self.assertEqual(scene.info["turnos"], 0)
        scene.step(manual=True)
        self.assertEqual(scene.info["turnos"], 1)
        scene.toggle_pause()
        scene.configure_wind(direction="NW", speed=.6)
        for _ in range(19):
            before = {p.person_id: p.position for p in scene.people}
            scene.step()
            self.assertEqual(len({p.position for p in scene.people}), 1879)
            self.assertTrue(all(abs(p.x-before[p.person_id][0])+abs(p.y-before[p.person_id][1]) <= 1 for p in scene.people))
            scene.center.manager.assert_index_consistent()
        self.assertGreater(scene.info["salieron"], 100)
        self.assertGreater(scene.center.router.routes_calculated, 0)
        self.assertGreater(scene.center.router.gathered_count(), 0)
        self.assertEqual(scene.center.wind_history.predict_next().direction, "NW")
        self.assertEqual(len(scene.reading_history), 21*12)
        with TemporaryDirectory(prefix="dcc_functional_export_") as temp:
            scene.export_readings(temp)
            package = read_sensor_package(temp)
            self.assertEqual(len(package["observables"]), 252)
            self.assertTrue(all("fire_within_2_cells" not in row for row in package["observables"]))
            self.assertTrue(all(0 <= r["x"] < 160 and 0 <= r["y"] < 100 for r in package["observables"]))
        old_run = scene.run_id
        scene.reset()
        self.assertNotEqual(old_run, scene.run_id)
        self.assertEqual(scene.info["fase"], "preparado")
        self.assertEqual(scene.reading_history, [])

    def test_projection_keeps_source_grid_and_conservative_smoke(self):
        fire = SimpleNamespace(turn=2, burning={(2, 1)})
        smoke = SimpleNamespace(turn=2, concentrations=[[0, .4, .7], [0, 0, 0], [0, 0, 0]])
        env = source_sensor_environment(SimpleNamespace(fire=fire, smoke=smoke), [["floor"]], 3)
        self.assertEqual(env.fire.burning, {(0, 0)})
        self.assertEqual(env.smoke.concentrations, [[.7]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
