"""Segunda fase: orientaciones, seleccion por clic y entorno exterior seguro."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from dcc_app.functional_application import FunctionalDisasterApp, TURTLE_MESSAGE
from dcc_app.model import load_campus
from dcc_app.viewport import Viewport
from routing.graph import CampusGraph
from routing.meeting_areas import MeetingArea, MeetingRouter
from simulation.campus_map import CampusMap
from simulation.exterior_risk import exterior_blocked_cells
from simulation.person import Person
from simulation.person_manager import PersonManager
from tools.build_functional_scenario import build

VECTORS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}


class EntranceOrientationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doors = json.loads((ROOT / "data/functional/building_entrances.json").read_text())["accesses"]
        cls.snapshot = load_campus(ROOT / "data/functional/campus.json", ROOT / "data/functional/building_entrances.json")

    def check_directions(self, building, directions):
        doors = [a for a in self.doors if a["building"] == building and a.get("role", "primary") == "primary"]
        self.assertEqual(len(doors), 3*len(directions))
        actual = {(a["exterior_cell"]["x"]-a["interior_cell"]["x"],
                   a["exterior_cell"]["y"]-a["interior_cell"]["y"]) for a in doors}
        self.assertEqual(actual, {VECTORS[d] for d in directions})

    def test_e19_south(self): self.check_directions("E19", {"S"})
    def test_e60_south(self):
        for building in ("E60 - norte", "E60 - sureste"):
            with self.subTest(building=building): self.check_directions(building, {"S"})
    def test_e8_south(self): self.check_directions("E8", {"S"})
    def test_e6_south(self): self.check_directions("E6", {"S"})
    def test_e4_south(self): self.check_directions("E4", {"S"})
    def test_e57_south(self): self.check_directions("E57", {"S"})
    def test_e7_north(self): self.check_directions("E7", {"N"})
    def test_e32_west(self): self.check_directions("E32", {"W"})
    def test_e55_south(self): self.check_directions("E55", {"S"})
    def test_e31_north_and_south(self): self.check_directions("E31", {"N", "S"})
    def test_e28_west(self): self.check_directions("E28", {"W"})
    def test_e18_east(self): self.check_directions("E18", {"E"})
    def test_e14_east(self): self.check_directions("E14", {"E"})

    def test_all_pairs_are_adjacent_interior_exterior(self):
        self.assertEqual(sum(a.get("role", "primary") == "primary" for a in self.doors), 168)
        for a in self.doors:
            ix, iy = a["interior_cell"]["x"], a["interior_cell"]["y"]
            ox, oy = a["exterior_cell"]["x"], a["exterior_cell"]["y"]
            self.assertEqual(abs(ix-ox)+abs(iy-oy), 1)
            self.assertEqual(self.snapshot.owners[iy][ix], a["building"])
            self.assertIn(self.snapshot.terrain[oy][ox], {"floor", "road"})
            source = a["source_exterior_cell"]
            self.assertEqual((ox//3, oy//3), (source["x"], source["y"]))

    def test_regeneration_preserves_source_defined_orientations(self):
        with TemporaryDirectory(prefix="dcc_second_data_") as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "data", root / "data")
            result = build(root)
            self.assertEqual(result["accesses"], len(self.doors))
            self.assertEqual(result["people"], 1879)
            for name in ("campus.json", "building_entrances.json", "population.json", "building_properties.json", "vegetation.json"):
                self.assertEqual((root / "data/functional" / name).read_bytes(), (ROOT / "data/functional" / name).read_bytes())


class ClickAndVegetationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = load_campus(ROOT / "data/functional/campus.json", ROOT / "data/functional/building_entrances.json")
        cls.app = FunctionalDisasterApp(cls.snapshot, ROOT, mode="optimizado")
        cls.vegetation = json.loads((ROOT / "data/functional/vegetation.json").read_text())

    def setUp(self):
        self.app.scene.reset()
        self.rect = (0, 82, 1004, 697)
        self.app.camera.fit(self.rect)

    def test_valid_click_selects_correct_cell_after_zoom_and_pan(self):
        cell = self.app.scene.center.ignition_cell
        self.app.camera.zoom_at(500, 400, 3)
        self.app.camera.pan(21, -12)
        pixel = self.app.camera.project(cell[0]+.5, cell[1]+.5)
        self.assertTrue(self.app.handle_map_click(pixel, self.rect))
        self.assertEqual(self.app.scene.center.selected_ignition, cell)

    def test_click_outside_map_or_in_hud_does_not_select(self):
        for pixel in ((-10, 100), (1005, 300), (300, 20), (1, 83)):
            self.assertFalse(self.app.handle_map_click(pixel, self.rect))
        self.assertIsNone(self.app.scene.center.selected_ignition)

    def test_noncombustible_click_is_rejected_without_selection(self):
        area = self.app.scene.center.areas[0]
        x, y = area.cells[0]
        pixel = self.app.camera.project(x+.5, y+.5)
        with self.assertRaises(ValueError): self.app.handle_map_click(pixel, self.rect)
        self.assertIsNone(self.app.scene.center.selected_ignition)

    def test_selected_vegetation_really_ignites_and_produces_smoke(self):
        x, y = self.vegetation["cells_source"][0]
        cell = (x*3+1, y*3+1)
        self.app.scene.select_ignition(*cell)
        self.app.scene.start()
        self.assertEqual(set(self.app.scene.environment.fire.burning), {cell})
        self.app.scene.step()
        self.assertGreater(self.app.scene.environment.smoke.concentrations[cell[1]][cell[0]], 0)
        self.assertEqual(self.app.scene.environment.fire.terrain[cell[1]][cell[0]], "grass")

    def test_later_click_cannot_change_origin_or_add_fire(self):
        self.app.scene.start()
        old = set(self.app.scene.environment.fire.burning)
        x, y = self.vegetation["cells_source"][0]
        pixel = self.app.camera.project(x*3+1.5, y*3+1.5)
        self.assertFalse(self.app.handle_map_click(pixel, self.rect))
        with self.assertRaises(ValueError): self.app.scene.select_ignition(x*3+1, y*3+1)
        self.assertEqual(set(self.app.scene.environment.fire.burning), old)
        self.assertIsNone(self.app.scene.center.selected_ignition)

    def test_fallback_is_original_focus(self):
        self.app.scene.start()
        self.assertEqual(set(self.app.scene.environment.fire.burning), {(235, 166)})

    def test_door_crossing_also_respects_exterior_risk_mask(self):
        scene = self.app.scene
        doors = json.loads((ROOT / "data/functional/building_entrances.json").read_text())["accesses"]
        occupied = {p.position for p in scene.people}
        door = next(a for a in doors if a["building"] == "E1"
                    and (a["interior_cell"]["x"], a["interior_cell"]["y"]) not in occupied)
        person = next(p for p in scene.people if p.building_id == "E1")
        inside, outside = door["interior_cell"], door["exterior_cell"]
        person.x, person.y = inside["x"], inside["y"]
        scene.center.manager.rebuild_index()
        scene.start()
        blocked = {(outside["x"], outside["y"])}
        with patch("simulation.functional_scenario.exterior_blocked_cells", return_value=blocked):
            scene.step()
        self.assertNotEqual(person.position, (outside["x"], outside["y"]))
        self.assertLessEqual(abs(person.x-inside["x"])+abs(person.y-inside["y"]), 1)
        self.assertEqual(person.building_id, "E1")

    def test_meeting_areas_remain_noncombustible(self):
        fire = self.app.scene.environment.fire
        for area in self.app.scene.center.areas:
            for x, y in area.cells:
                self.assertIn(fire.terrain[y][x], {"floor", "road"})
                self.assertFalse(fire.combustible[y][x])

    def test_all_preserved_walkways_and_doors_are_transitable(self):
        graph = self.app.scene.center.router.graph
        for x, y in self.vegetation["protected_walkways_source"]:
            # Los sensores interiores estan protegidos pero no son andadores.
            if self.snapshot.owners[y*3+1][x*3+1] is None:
                self.assertTrue(graph.is_valid(x*3+1, y*3+1))
        for _, x, y in self.snapshot.entrances:
            self.assertTrue(graph.is_valid(x, y))

    def test_only_floor_beds_change_not_roads_or_buildings(self):
        source = load_campus(ROOT / "data/campus.json", ROOT / "data/building_entrances.json")
        changed = {tuple(p) for p in self.vegetation["cells_source"]}
        self.assertGreater(len(changed), 0)
        self.assertLess(len(changed), source.terrain_count["floor"])
        for y, row in enumerate(source.terrain):
            for x, kind in enumerate(row):
                actual = self.snapshot.terrain[y*3+1][x*3+1]
                self.assertEqual(actual, "grass" if (x, y) in changed else kind)
                if (x, y) in changed: self.assertEqual(kind, "floor")

    def test_real_pygame_events_select_then_lock_after_alarm(self):
        import pygame
        x, y = self.vegetation["cells_source"][0]
        cell = (x*3+1, y*3+1)
        pixel = self.app.camera.project(cell[0]+.5, cell[1]+.5)
        original_set_mode = pygame.display.set_mode
        def open_and_post(*args, **kwargs):
            screen = original_set_mode(*args, **kwargs)
            for event in (
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pixel),
                pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a),
                pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(pixel[0]+10, pixel[1])),
            ): pygame.event.post(event)
            return screen
        with patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"}), patch.object(pygame.display, "set_mode", open_and_post):
            self.app.run(smoke_test=True)
        self.assertEqual(self.app.scene.center.selected_ignition, cell)
        self.assertEqual(set(self.app.scene.environment.fire.burning), {cell})


class ExteriorRoutingTests(unittest.TestCase):
    def test_fire_next_to_walkway_forces_same_router_to_replan(self):
        campus = CampusMap(9, 7); campus.fill_terrain("floor")
        campus.set_terrain(4, 3, "grass")
        graph = CampusGraph(campus)
        manager = PersonManager(9, 7, graph.is_valid)
        person = Person("P", 1, 2); manager.add_person(person)
        area = MeetingArea("R", "test", "right", (7, 2, 1, 1), ((7, 2),))
        router = MeetingRouter(graph, manager, "test", [area])
        smoke = [[0.0]*9 for _ in range(7)]
        router.advance(smoke, set(), set(), {}, {"P"}, 1)
        self.assertIn((4, 2), router.paths["P"])
        terrain = [[campus.get_cell(x, y).terrain_type for x in range(9)] for y in range(7)]
        blocked = exterior_blocked_cells({(4, 3)}, smoke, terrain)
        self.assertIn((4, 2), blocked)
        router.advance(smoke, {(4, 3)}, blocked, {}, {"P"}, 2)
        self.assertEqual(router.routes_calculated, 2)
        self.assertFalse(set(router.paths["P"]) & blocked)
        self.assertFalse(graph.is_valid(4, 3))
        for turn in range(3, 12):
            router.advance(smoke, {(4, 3)}, blocked, {}, {"P"}, turn)
            self.assertNotIn(person.position, blocked)
        self.assertEqual(person.position, (7, 2))

    def test_nearby_vegetation_can_close_a_meeting_area(self):
        campus = CampusMap(5, 5); campus.fill_terrain("floor")
        campus.set_terrain(2, 2, "grass")
        graph = CampusGraph(campus); manager = PersonManager(5, 5, graph.is_valid)
        area = MeetingArea("R", "test", "left", (2, 1, 1, 1), ((2, 1),))
        router = MeetingRouter(graph, manager, "test", [area])
        smoke = [[0.0]*5 for _ in range(5)]
        terrain = [[campus.get_cell(x, y).terrain_type for x in range(5)] for y in range(5)]
        blocked = exterior_blocked_cells({(2, 2)}, smoke, terrain)
        self.assertFalse(router.assess(smoke, {(2, 2)}, blocked_cells=blocked)["R"])

    def test_smoke_threshold_still_blocks_exterior(self):
        blocked = exterior_blocked_cells(set(), [[0, .64, .65]], [["road"]*3])
        self.assertEqual(blocked, {(2, 0)})


class HudAndEntryTests(unittest.TestCase):
    def test_exact_turtle_message_is_rendered_in_footer(self):
        import pygame
        self.assertEqual(TURTLE_MESSAGE, "Ninguna tortuga saldrá lastimada durante esta simulación.")
        pygame.font.init()
        screen = pygame.Surface((1320, 830))
        font = pygame.font.SysFont("arial", 12)
        seen = []
        class FontSpy:
            def render(self, text, *args):
                seen.append(text)
                return font.render(text, *args)
        FunctionalDisasterApp._draw_footer(None, pygame, screen, (font, font, FontSpy()))
        self.assertIn(TURTLE_MESSAGE, seen)

    def test_active_and_legacy_applications_start(self):
        env = {**os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"}
        for legacy in (False, True):
            args = [sys.executable, "-B", str(ROOT / "main.py"), "--modo-original", "--smoke-test"]
            if legacy: args.append("--legacy")
            result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn("personas=100" if legacy else "personas=1879", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
