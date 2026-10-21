"""Tercera fase: progresion, persistencia, brasas y redundancia de salidas."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from routing.graph import CampusGraph
from routing.meeting_areas import MeetingArea, MeetingRouter
from simulation.adaptive_exits import AdaptiveExitController
from simulation.campus_map import CampusMap
from simulation.exterior_risk import exterior_blocked_cells
from simulation.fire_simulation import FireSimulation
from simulation.hazard_impact import ExposureTracker
from simulation.indoor_people import IndoorPersonManager
from simulation.person import Person
from simulation.person_manager import PersonManager
from simulation.scenario_fire import ScenarioFireSimulation
from simulation.wind_simulation import Wind, WindFireSimulation, WindSmokeSimulation
from tools.functional_geometry import area_percentile, orient_entrances, vegetation_layout

CONFIG = json.loads((ROOT / "data/functional_scenario.json").read_text())


def fire_for(terrain, *, seed=2026, laboratory=False, **changes):
    behavior = {**deepcopy(CONFIG["fire_behavior"]), "spotting_enabled": False, **changes}
    owners = [["E" if t == "building" else None for t in row] for row in terrain]
    return ScenarioFireSimulation(terrain, None, behavior=behavior, owners=owners,
        properties={"E": {"laboratory": laboratory, "flammable_materials": laboratory}}, seed=seed)


class FireProgressionTests(unittest.TestCase):
    def test_actual_configuration_spreads_more_slowly_than_legacy(self):
        terrain = [["building"]*41 for _ in range(41)]
        new_total = old_total = 0
        for seed in range(30):
            new, old = fire_for(terrain, seed=seed), WindFireSimulation(terrain, seed=seed)
            for fire in (new, old):
                fire.set_wind(Wind("E", .75)); fire.ignite(20, 20)
                for _ in range(30): fire.step()
            new_total += new.total_ignitions; old_total += old.total_ignitions
        self.assertLess(new_total, old_total*.25)

    def test_laboratory_increases_real_spread_without_instant_cascade(self):
        terrain = [["building"]*31 for _ in range(31)]
        totals = []
        for laboratory in (False, True):
            total = 0
            for seed in range(20):
                fire = fire_for(terrain, seed=seed, laboratory=laboratory)
                fire.ignite(15, 15)
                for _ in range(20): fire.step()
                total += fire.total_ignitions
            totals.append(total)
        self.assertGreater(totals[1], totals[0])
        self.assertLess(totals[1], 20*31*31//4)
        normal = fire_for(terrain); lab = fire_for(terrain, laboratory=True)
        self.assertAlmostEqual(lab.spread_probability((1, 1), (2, 1), Wind()),
            normal.spread_probability((1, 1), (2, 1), Wind())*CONFIG["fire_behavior"]["laboratory_multiplier"])

    def test_actual_configuration_crosses_building_vegetation_building(self):
        fire = fire_for([["building", "grass", "grass", "building"]], seed=1)
        fire.ignite(0, 0)
        reached = []
        for turn in range(1, 101):
            fire.step()
            for x in range(4):
                if fire.state_at(x, 0) != "unburned" and x not in reached:
                    reached.append(x)
        self.assertEqual(reached, [0, 1, 2, 3])
        self.assertEqual(fire.total_ignitions, 4)
        self.assertEqual(fire.spotting_events, [])

    def test_no_same_turn_cascade_even_with_certain_transmission(self):
        fire = fire_for([["grass"]*12], base_spread_rate=1, vegetation_multiplier=1)
        fire.ignite(0, 0); fire.step()
        self.assertEqual(set(fire.burning), {(0, 0), (1, 0)})

    def test_legacy_windless_engine_remains_identical_to_original(self):
        terrain = [["grass"]*15 for _ in range(15)]
        a, b = FireSimulation(terrain, seed=41), WindFireSimulation(terrain, seed=41)
        for fire in (a, b): fire.ignite(7, 7)
        for _ in range(25):
            self.assertEqual(a.step(), b.step())
            self.assertEqual(a.burning, b.burning)
            self.assertEqual(a.burned, b.burned)

    def test_invalid_fire_configuration_is_rejected(self):
        for changes in ({"base_spread_rate": float("nan")}, {"spotting_max_distance": 1},
                        {"spotting_min_alignment": 2}, {"laboratory_multiplier": .5}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                fire_for([["grass"]], **changes)


class SpottingTests(unittest.TestCase):
    def make_spotter(self, seed=17, **changes):
        options = {"base_spread_rate": 0, "spotting_enabled": True, "spotting_probability": 1,
                   "burn_durations": {"building": 100, "grass": 100}, **changes}
        return fire_for([["grass"]*41 for _ in range(41)], seed=seed,
                        **options)

    def test_spotting_generates_valid_bounded_downwind_focus(self):
        for direction in ("N", "NE", "E", "SE", "S", "SW", "W", "NW"):
            fire = self.make_spotter(); wind = Wind(direction, 1)
            fire.set_wind(wind); fire.ignite(20, 20); fire.step()
            self.assertEqual(len(fire.last_spots), 1)
            event = fire.last_spots[0]
            sx, sy = event["source"]; tx, ty = event["target"]
            distance = math.hypot(tx-sx, ty-sy)
            self.assertLessEqual(distance, CONFIG["fire_behavior"]["spotting_max_distance"])
            self.assertGreaterEqual(distance, CONFIG["fire_behavior"]["spotting_min_distance"])
            self.assertGreaterEqual((tx-sx)*wind.vector[0]+(ty-sy)*wind.vector[1],
                                    CONFIG["fire_behavior"]["spotting_min_alignment"]*distance)
            self.assertTrue(fire.combustible[ty][tx])
            self.assertIn((tx, ty), fire.burning)

    def test_same_seed_reproduces_secondary_events_and_fire(self):
        fires = [self.make_spotter(seed=91) for _ in range(2)]
        for fire in fires:
            fire.set_wind(Wind("E", .8)); fire.ignite(10, 20)
            for _ in range(20):
                fire.step()
                self.assertLessEqual(len(fire.last_spots), CONFIG["fire_behavior"]["spotting_max_per_turn"])
        self.assertGreater(len(fires[0].spotting_events), 0)
        self.assertEqual(fires[0].spotting_events, fires[1].spotting_events)
        self.assertEqual(fires[0].burning, fires[1].burning)

    def test_disabled_or_insufficient_wind_never_produces_spots(self):
        for enabled, speed in ((False, 1), (True, 0), (True, .39)):
            fire = self.make_spotter(spotting_enabled=enabled)
            fire.set_wind(Wind("E", speed)); fire.ignite(20, 20)
            for _ in range(10): fire.step()
            self.assertEqual(fire.spotting_events, [])

    def test_roads_walkways_and_meeting_floor_cannot_ignite(self):
        for ground in ("road", "floor"):
            terrain = [[ground]*41 for _ in range(41)]
            terrain[20][20] = "building"
            fire = fire_for(terrain, base_spread_rate=0, spotting_enabled=True, spotting_probability=1)
            fire.set_wind(Wind("E", 1)); fire.ignite(20, 20)
            for _ in range(18): fire.step()
            self.assertEqual(fire.total_ignitions, 1)
            self.assertEqual(fire.spotting_events, [])

    def test_brasas_can_cross_a_short_noncombustible_gap(self):
        terrain = [["road" if x in (21, 22) else "grass" for x in range(41)] for _ in range(41)]
        fire = fire_for(terrain, base_spread_rate=0, spotting_enabled=True, spotting_probability=1)
        fire.set_wind(Wind("E", 1)); fire.ignite(20, 20)
        # Un sorteo controlado elige un destino valido a tres celdas.
        from unittest.mock import patch
        with patch.object(fire.spot_rng, "choice", return_value=(3, 0)):
            fire.step()
        self.assertIn((23, 20), fire.burning)
        self.assertNotIn((21, 20), fire.burning)
        self.assertNotIn((22, 20), fire.burning)


class PersistentSmokeTests(unittest.TestCase):
    def test_smoke_lasts_longer_and_decays_gradually_without_sources(self):
        old = WindSmokeSimulation(1, 1)
        new = WindSmokeSimulation(1, 1, **CONFIG["smoke_behavior"])
        old.concentrations[0][0] = new.concentrations[0][0] = 1
        previous = 1
        for _ in range(40):
            old.step(); new.step()
            amount = new.concentrations[0][0]
            self.assertTrue(0 < amount < previous)
            self.assertAlmostEqual(amount/previous, 1-CONFIG["smoke_behavior"]["decay_rate"])
            previous = amount
        self.assertGreater(previous, .7)
        self.assertGreater(previous, old.concentrations[0][0]*10)
        for _ in range(1500): new.step()
        self.assertEqual(new.concentrations[0][0], 0)

    def test_wind_still_transports_persistent_smoke(self):
        smoke = WindSmokeSimulation(21, 5, **CONFIG["smoke_behavior"])
        smoke.concentrations[2][3] = 1
        smoke.set_wind(Wind("E", .75))
        for _ in range(6): smoke.step()
        mass = sum(map(sum, smoke.concentrations))
        centroid = sum(x*c for row in smoke.concentrations for x, c in enumerate(row))/mass
        self.assertGreater(centroid, 5)
        self.assertGreater(mass, .9)

    def test_long_emission_stays_in_valid_range(self):
        smoke = WindSmokeSimulation(5, 5, **CONFIG["smoke_behavior"])
        smoke.set_wind(Wind("SE", .75))
        for _ in range(200): smoke.step({(2, 2)})
        self.assertTrue(all(0 <= c <= 1 for row in smoke.concentrations for c in row))
        self.assertGreater(smoke.concentrations[2][2], .6)

    def test_meeting_remains_closed_after_fire_leaves_then_reopens(self):
        campus = CampusMap(3, 3); campus.fill_terrain("floor")
        graph = CampusGraph(campus); manager = PersonManager(3, 3, graph.is_valid)
        area = MeetingArea("R", "E", "left", (1, 1, 1, 1), ((1, 1),))
        router = MeetingRouter(graph, manager, "smoke-test", [area],
                               smoke_threshold=CONFIG["meeting_smoke_threshold"])
        smoke = WindSmokeSimulation(3, 3, **{**CONFIG["smoke_behavior"], "diffusion_rate": 0})
        smoke.concentrations[1][1] = .8
        for _ in range(40): smoke.step()
        self.assertFalse(router.assess(smoke.concentrations, {(0, 0)})["R"])
        for _ in range(100): smoke.step()
        self.assertTrue(router.assess(smoke.concentrations, set())["R"])

    def test_route_threshold_is_preserved_and_distinct_from_meeting_threshold(self):
        blocked = exterior_blocked_cells(set(), [[.30, .64, .65, 1.0]], [["floor"]*4],
                                         smoke_threshold=CONFIG["route_smoke_threshold"])
        self.assertEqual(blocked, {(2, 0), (3, 0)})
        self.assertEqual(CONFIG["meeting_smoke_threshold"], .30)
        self.assertEqual(CONFIG["route_smoke_threshold"], .65)


class GeneratedGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = IndoorPersonManager.from_json(ROOT / "data/functional/campus.json")
        cls.source = IndoorPersonManager.from_json(ROOT / "data/campus.json")
        cls.vegetation = json.loads((ROOT / "data/functional/vegetation.json").read_text())
        cls.doors = json.loads((ROOT / "data/functional/building_entrances.json").read_text())
        cls.population = json.loads((ROOT / "data/functional/population.json").read_text())

    def test_distributed_vegetation_is_substantially_more_abundant(self):
        cells = {tuple(p) for p in self.vegetation["cells_source"]}
        self.assertGreater(len(cells)*9, 2943*4)
        # Distribucion en sectores del campus, no solo los cuatro parches previos.
        sectors = {(x//20, y//20) for x, y in cells}
        self.assertGreater(len(sectors), 20)
        self.assertLess(len(cells), sum(row.count("floor") for row in self.source.terrain))

    def test_buildings_roads_meetings_and_protected_walkways_are_excluded(self):
        cells = {tuple(p) for p in self.vegetation["cells_source"]}
        for x, y in cells:
            self.assertEqual(self.source.terrain[y][x], "floor")
        for area in CONFIG["meeting_areas"]:
            x, y, w, h = area["bounds_source"]
            self.assertFalse(cells & {(xx, yy) for yy in range(y, y+h) for xx in range(x, x+w)})
        self.assertFalse(cells & {tuple(p) for p in self.vegetation["protected_walkways_source"]})

    def test_large_buildings_derive_from_area_percentiles_and_small_keep_one(self):
        sizes = self.population["source_cell_areas"]
        policy = CONFIG["multiple_exit_policy"]
        large = area_percentile(sizes.values(), policy["large_percentile"])
        very_large = area_percentile(sizes.values(), policy["very_large_percentile"])
        for name, area in sizes.items():
            groups = {a["id"].rsplit("-sub", 1)[0] for a in self.doors["accesses"] if a["building"] == name}
            wanted = policy["very_large_min_exits"] if area >= very_large else policy["large_min_exits"] if area >= large else 1
            self.assertEqual(len(groups), wanted, name)

    def test_required_manual_source_doors_and_coordinates_are_preserved(self):
        original = json.loads((ROOT / "data/building_entrances.json").read_text())["accesses"]
        expected = orient_entrances(self.source, original, CONFIG["entrance_orientations"])
        for old in expected:
            doors = [a for a in self.doors["accesses"] if a["id"].startswith(old["id"]+"-sub")]
            self.assertEqual(len(doors), 3)
            for new in doors:
                self.assertEqual(new["source_interior_cell"], old["interior_cell"])
                self.assertEqual(new["source_exterior_cell"], old["exterior_cell"])
                self.assertEqual(new["role"], "primary")

    def test_alternative_facades_are_distinct_and_all_pairs_reach_meetings(self):
        root = (CONFIG["meeting_areas"][0]["bounds_source"][0]*3,
                CONFIG["meeting_areas"][0]["bounds_source"][1]*3)
        reached, queue = {root}, deque([root])
        while queue:
            x, y = queue.popleft()
            for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1)):
                point = (x+dx, y+dy)
                if point not in reached and self.manager.is_transitable(*point):
                    reached.add(point); queue.append(point)
        directions = {}
        for a in self.doors["accesses"]:
            i, o = a["interior_cell"], a["exterior_cell"]
            self.assertEqual(abs(i["x"]-o["x"])+abs(i["y"]-o["y"]), 1)
            self.assertEqual(self.manager.building_at(i["x"], i["y"]), a["building"])
            self.assertIn((o["x"], o["y"]), reached)
            if a["id"].endswith("-sub1"):
                previous = directions.setdefault(a["building"], set())
                self.assertNotIn(a["orientation"], previous)
                previous.add(a["orientation"])

    def test_mask_regeneration_is_seeded_and_exactly_reproducible(self):
        accesses = []
        for a in self.doors["accesses"]:
            if a["id"].endswith("-sub1"):
                accesses.append({"id": a["id"], "exterior_cell": a["source_exterior_cell"]})
        sensors = json.loads((ROOT / "data/sensores_paso_13.json").read_text())["sensors"]
        self.assertEqual(vegetation_layout(self.source, accesses, CONFIG, sensors), self.vegetation)


class AdaptiveExitTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="dcc_exits_")
        self.addCleanup(self.temp.cleanup)
        data = {"width": 13, "height": 7, "default_terrain": "floor", "zones": [
            {"name": "E", "x": 3, "y": 2, "width": 7, "height": 3, "terrain_type": "building"}]}
        self.manager = IndoorPersonManager(data)
        self.person = Person("P", 4, 3, building_id="E"); self.manager.add_person(self.person)
        self.path = Path(self.temp.name) / "doors.json"
        self.path.write_text(json.dumps({"width": 13, "height": 7, "accesses": [
            {"id": "west", "building": "E", "role": "primary", "interior_cell": {"x": 3, "y": 3}, "exterior_cell": {"x": 2, "y": 3}},
            {"id": "east", "building": "E", "role": "secondary", "interior_cell": {"x": 9, "y": 3}, "exterior_cell": {"x": 10, "y": 3}}]}))
        self.controller = AdaptiveExitController(self.manager, self.path, manage_exterior=False)
        self.tracker = ExposureTracker([self.person])

    def test_blocked_primary_exit_really_uses_alternative(self):
        for _ in range(7): self.controller.step_with_hazards(self.tracker, {(2, 3)})
        self.assertEqual(self.person.position, (10, 3))
        self.assertIsNone(self.person.building_id)
        self.assertEqual(self.controller.alternative_exits_used, 1)
        self.assertEqual(self.controller.alternative_exits_under_blockage, 1)
        self.assertEqual(self.controller.crossings, {"east": 1})

    def test_hazard_on_indoor_path_is_avoided_without_second_engine(self):
        blocked = {(2, 3), (6, 3)}
        for _ in range(12):
            self.controller.step_with_hazards(self.tracker, blocked)
            self.assertNotIn(self.person.position, blocked)
        self.assertIsNone(self.person.building_id)

    def test_all_exits_blocked_waits_and_recovers_when_one_reopens(self):
        old = self.person.position
        self.controller.step_with_hazards(self.tracker, {(2, 3), (10, 3)})
        self.assertEqual(self.person.position, old)
        self.assertEqual(len(self.controller.blocked_exit_groups), 2)
        for _ in range(7): self.controller.step_with_hazards(self.tracker, {(2, 3)})
        self.assertIsNone(self.person.building_id)

    def test_static_hazard_signature_reuses_distance_fields(self):
        self.controller.hazard_routes({(2, 3)})
        rebuilds = self.controller.distance_rebuilds
        for _ in range(10): self.controller.hazard_routes({(2, 3)})
        self.assertEqual(self.controller.distance_rebuilds, rebuilds)
        self.controller.hazard_routes({(10, 3)})
        self.assertEqual(self.controller.distance_rebuilds, rebuilds+1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
