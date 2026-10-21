"""Cuarta fase: riesgo preventivo, causalidad del viento y reloj independiente."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from dcc_app.functional_application import FunctionalDisasterApp
from dcc_app.functional_scene import FunctionalScene
from dcc_app.model import load_campus
from dcc_app.playback import PlaybackClock
from integration.persona2_contract_15_1 import read_sensor_package
from integration.sensor_export import COLUMNS
from integration.wind_telemetry import WindTelemetry, validate_wind_observation
from routing.congestion import CongestionManager
from routing.graph import CampusGraph
from routing.meeting_areas import MeetingArea, MeetingRouter
from routing.meeting_policy import MeetingAreaPolicy
from routing.weighted_astar import weighted_astar
from simulation.building_risk import BuildingRisk
from simulation.adaptive_exits import AdaptiveExitController
from simulation.hazard_impact import ExposureTracker
from simulation.indoor_people import IndoorPersonManager
from simulation.campus_map import CampusMap
from simulation.dynamic_risk import DynamicRiskField
from simulation.person import Person
from simulation.person_manager import PersonManager
from simulation.wind_history import WindHistory
from simulation.wind_simulation import Wind
from wind_prediction.dataset import features, split_sequences, temporal_examples, vector_from_degrees
from wind_prediction.model import WindPredictor, vector_prediction
from wind_prediction.synthetic import synthetic_sequences
from tools.train_wind_predictor import metrics, train

CONFIG = json.loads((ROOT / "data/functional_scenario.json").read_text())


def field_for(width, height, **changes):
    cfg = {**CONFIG["risk_routing"], "plume_stride": 1, **changes}
    return DynamicRiskField([["floor"]*width for _ in range(height)], cfg)


def update_field(field, fire=(), *, direction="E", speed=0, turn=1, smoke=None, predicted_direction=None):
    wind = Wind(direction, speed)
    future = Wind(predicted_direction or direction, speed)
    return field.update(set(fire), smoke if smoke is not None else [[0.0]*field.width for _ in range(field.height)],
                        wind, vector_prediction(turn+1, future.vector[0]*speed, future.vector[1]*speed, "test"), turn=turn)


class PreventiveRoutingTests(unittest.TestCase):
    def test_a_moderately_longer_route_avoids_fire_proximity(self):
        campus = CampusMap(31, 21); campus.fill_terrain("floor")
        graph = CampusGraph(campus)
        field = field_for(31, 21, fire_radius=6)
        update_field(field, {(15, 10)})
        short = weighted_astar(graph, (9, 10), (27, 10), blocked_cells={(15, 10)})
        safe = weighted_astar(graph, (9, 10), (27, 10), blocked_cells={(15, 10)}, risk_field=field)
        distance = lambda p: abs(p[0]-15)+abs(p[1]-10)
        self.assertGreater(len(safe), len(short))
        self.assertLess(len(safe), 2*len(short))
        self.assertGreaterEqual(min(map(distance, safe)), 6)
        self.assertEqual(min(map(distance, short)), 1)
        self.assertGreater(distance(safe[1]), distance(safe[0]))

    def test_b_only_escape_can_temporarily_approach_fire(self):
        campus = CampusMap(11, 3); campus.fill_terrain("building")
        for x in range(11): campus.set_terrain(x, 1, "floor")
        field = DynamicRiskField([[campus.get_cell(x, y).terrain_type for x in range(11)] for y in range(3)],
                                 {**CONFIG["risk_routing"], "plume_stride": 1})
        update_field(field, {(5, 0)})
        route = weighted_astar(CampusGraph(campus), (1, 1), (9, 1), blocked_cells={(5, 0)}, risk_field=field)
        self.assertEqual(route, [(x, 1) for x in range(1, 10)])
        self.assertTrue(all(abs(a[0]-b[0])+abs(a[1]-b[1]) == 1 for a, b in zip(route, route[1:])))

    def make_router(self, *, area_policy=False):
        campus = CampusMap(31, 21); campus.fill_terrain("floor")
        graph = CampusGraph(campus)
        manager = PersonManager(31, 21, graph.is_valid)
        person = Person("P", 3, 10); manager.add_person(person)
        area = MeetingArea("R", "test", "right", (27, 10, 1, 1), ((27, 10),))
        field = field_for(31, 21, fire_radius=2)
        policy = MeetingAreaPolicy([area], CONFIG["meeting_area_policy"], .3) if area_policy else None
        router = MeetingRouter(graph, manager, "test", [area], risk_field=field, area_policy=policy)
        return router, field, person

    def test_c_fire_appearing_on_route_replans_through_same_gateway(self):
        router, field, person = self.make_router()
        smoke = [[0.0]*31 for _ in range(21)]
        update_field(field)
        router.advance(smoke, set(), set(), {}, {"P"}, 1)
        self.assertIn((15, 10), router.paths["P"])
        update_field(field, {(15, 10)}, turn=2)
        router.advance(smoke, {(15, 10)}, {(15, 10)}, {}, {"P"}, 2)
        self.assertEqual(router.replanned_routes, 1)
        self.assertNotIn((15, 10), router.paths["P"])
        self.assertNotEqual(person.position, (15, 10))

    def test_wind_change_selectively_invalidates_future_exposure(self):
        router, field, _ = self.make_router()
        smoke = [[0.0]*31 for _ in range(21)]
        fire = {(15, 5)}
        update_field(field, fire, direction="N", speed=1)
        router.advance(smoke, fire, fire, {}, {"P"}, 1)
        update_field(field, fire, direction="S", speed=1, turn=2)
        router.advance(smoke, fire, fire, {}, {"P"}, 2)
        self.assertEqual(router.predictive_route_invalidations, 1)
        self.assertEqual(router.replanned_routes, 1)

    def test_field_distance_is_shared_and_smoke_below_threshold_has_cost(self):
        field = field_for(15, 11)
        smoke = [[0.0]*15 for _ in range(11)]; smoke[8][12] = .4
        update_field(field, {(5, 5), (10, 2)}, smoke=smoke)
        self.assertEqual(field.fire_distance[5, 7], 2)
        self.assertGreater(field.risk_cost(12, 8), 0)
        self.assertGreater(field.risk_cost(6, 5), field.risk_cost(0, 10))

    def test_empty_small_map_has_no_phantom_fire_proximity(self):
        field = field_for(2, 2)
        update_field(field)
        self.assertEqual(float(field.costs.max()), 0.0)
        self.assertEqual(float(field.fire_proximity.max()), 0.0)

    def test_burning_vegetation_and_critical_labs_add_cost(self):
        terrain = [["floor"]*15 for _ in range(11)]; terrain[5][5] = "grass"
        owners = [[None]*15 for _ in range(11)]; owners[5][7] = "L"
        props = {"L": {"laboratory": True, "flammable_materials": True}}
        risk = BuildingRisk(owners, props, scale=1)
        field = DynamicRiskField(terrain, CONFIG["risk_routing"], owners=owners, properties=props)
        wind = Wind("E", 0)
        field.update({(5, 5)}, [[0.0]*15 for _ in range(11)], wind, vector_prediction(1, 0, 0, "test"), building_risk=risk)
        self.assertGreater(field.vegetation_proximity[5, 6], 0)
        self.assertGreater(field.laboratory_proximity[5, 8], 0)
        self.assertEqual(risk.levels["L"], "critical")
        previous = dict(risk.levels)
        self.assertEqual(risk.update({(5, 5)}), previous)

    def test_static_topology_preserves_neighbors_and_editable_graph_stays_live(self):
        campus = CampusMap(7, 5); campus.fill_terrain("floor")
        campus.set_terrain(3, 2, "grass")
        original, cached = CampusGraph(campus), CampusGraph(campus).cache_static_topology()
        for y in range(5):
            for x in range(7):
                self.assertEqual(original.get_neighbors(x, y), cached.get_neighbors(x, y))
                self.assertEqual(original.is_valid(x, y), cached.is_valid(x, y))
        campus.set_terrain(1, 1, "building")
        self.assertFalse(original.is_valid(1, 1))

    def test_congestion_is_still_an_additive_cost(self):
        campus = CampusMap(11, 7); campus.fill_terrain("floor")
        congestion = CongestionManager(radius=1)
        congestion.update([Person("Q", 5, 3)])
        field = field_for(11, 7); update_field(field)
        route = weighted_astar(CampusGraph(campus), (1, 3), (9, 3), congestion, risk_field=field)
        self.assertNotIn((5, 3), route)

    def test_interior_prefers_farther_exit_with_safer_exterior(self):
        data = {"width": 13, "height": 7, "default_terrain": "floor", "zones": [
            {"name": "E", "x": 3, "y": 2, "width": 7, "height": 3, "terrain_type": "building"}]}
        manager = IndoorPersonManager(data)
        person = Person("P", 4, 3, building_id="E"); manager.add_person(person)
        field = field_for(13, 7, fire_radius=3)
        update_field(field, {(1, 3)})
        with TemporaryDirectory(prefix="dcc_preventive_exit_") as folder:
            path = Path(folder)/"doors.json"
            path.write_text(json.dumps({"width": 13, "height": 7, "accesses": [
                {"id": "west", "building": "E", "role": "primary", "interior_cell": {"x": 3, "y": 3}, "exterior_cell": {"x": 2, "y": 3}},
                {"id": "east", "building": "E", "role": "secondary", "interior_cell": {"x": 9, "y": 3}, "exterior_cell": {"x": 10, "y": 3}}]}))
            controller = AdaptiveExitController(manager, path, manage_exterior=False, risk_field=field)
            tracker = ExposureTracker([person])
            for _ in range(10): controller.step_with_hazards(tracker, {(1, 3)})
            self.assertEqual(person.position, (10, 3))
            self.assertEqual(controller.alternative_exits_used, 1)
            self.assertEqual(controller.blocked_exit_groups, set())


class PreventiveMeetingTests(unittest.TestCase):
    def setUp(self):
        campus = CampusMap(41, 31); campus.fill_terrain("floor")
        self.graph = CampusGraph(campus)
        self.manager = PersonManager(41, 31, self.graph.is_valid)
        self.person = Person("P", 20, 22); self.manager.add_person(self.person)
        self.areas = [MeetingArea("E", "test", "right", (25, 15, 1, 1), ((25, 15),)),
                      MeetingArea("W", "test", "left", (15, 15, 1, 1), ((15, 15),))]
        self.field = field_for(41, 31, fire_radius=2)
        self.policy = MeetingAreaPolicy(self.areas, CONFIG["meeting_area_policy"], .3)
        self.router = MeetingRouter(self.graph, self.manager, "test", self.areas,
                                    risk_field=self.field, area_policy=self.policy)
        self.smoke = [[0.0]*41 for _ in range(31)]

    def advance(self, turn):
        return self.router.advance(self.smoke, {(20, 15)}, {(20, 15)}, {}, {"P"}, turn)

    def test_downwind_area_loses_to_upwind_area_and_wind_reverses_evaluation(self):
        update_field(self.field, {(20, 15)}, direction="E", speed=1)
        self.advance(1)
        self.assertEqual(self.policy.states["E"], "AVOID")
        self.assertEqual(self.router.assignments["P"][0], "W")
        update_field(self.field, {(20, 15)}, direction="W", speed=1, turn=2)
        self.advance(2)
        self.assertGreater(self.policy.diagnostics["W"]["predicted_smoke"], self.policy.diagnostics["E"]["predicted_smoke"])
        # No se exige reapertura instantanea: la zona E debe recuperarse.
        update_field(self.field, {(20, 15)}, direction="W", speed=1, turn=10)
        self.advance(10)
        self.assertEqual(self.router.assignments["P"][0], "E")

    def test_predicted_wind_has_effect_even_before_actual_wind_changes(self):
        update_field(self.field, {(20, 15)}, direction="E", predicted_direction="W", speed=1)
        # El 60% previsto al oeste supera el componente actual del este.
        self.router.assess(self.smoke, {(20, 15)})
        self.assertGreater(self.policy.diagnostics["W"]["predicted_smoke"], self.policy.diagnostics["E"]["predicted_smoke"])

    def set_score(self, area, score, turn):
        self.field.turn = turn
        self.field.predicted_smoke.fill(0)
        x, y = self.areas[0 if area == "E" else 1].cells[0]
        self.field.predicted_smoke[y, x] = score/CONFIG["meeting_area_policy"]["predicted_risk_weight"]
        self.router.assess(self.smoke, set())

    def test_hysteresis_does_not_toggle_at_avoid_boundary(self):
        update_field(self.field)
        self.set_score("E", .51, 1)
        self.assertEqual(self.policy.states["E"], "AVOID")
        for turn in range(2, 18):
            self.set_score("E", .49 if turn % 2 else .51, turn)
            self.assertEqual(self.policy.states["E"], "AVOID")
        self.set_score("E", .3, 20)
        self.assertEqual(self.policy.states["E"], "CAUTION")

    def test_safe_assignment_is_kept_despite_small_score_changes(self):
        update_field(self.field)
        self.advance(1)
        original = self.router.assignments["P"][0]
        for turn in range(2, 20):
            self.set_score(original, .2 if turn % 2 else .3, turn)
            self.advance(turn)
        self.assertEqual(self.router.assignments["P"][0], original)
        self.assertEqual(self.router.destination_changes, [])

    def test_congestion_replanning_does_not_switch_a_safe_destination(self):
        update_field(self.field)
        self.advance(1)
        original = self.router.assignments["P"][0]
        self.person.x, self.person.y = (5, 15) if original == "E" else (35, 15)
        for turn in range(2, 6):
            self.router._release("P")
            self.router.pending_reasons["P"] = "congestion"
            self.assertTrue(self.router._plan(self.person, {(20, 15)}, {self.person.position}, turn))
            self.assertEqual(self.router.assignments["P"][0], original)
        self.assertEqual(self.router.destination_changes, [])

    def test_actual_danger_forces_reassignment_despite_cooldown(self):
        update_field(self.field)
        self.advance(1)
        original, goal = self.router.assignments["P"]
        self.person.x, self.person.y = goal
        self.smoke[goal[1]][goal[0]] = .4
        self.field.turn = 2
        self.advance(2)
        self.assertEqual(self.policy.states[original], "CLOSED")
        self.assertNotEqual(self.router.assignments["P"][0], original)

    def test_resident_is_reassigned_on_strong_predicted_threat(self):
        update_field(self.field)
        self.advance(1)
        original, goal = self.router.assignments["P"]
        self.person.x, self.person.y = goal
        self.set_score(original, .9, 2)
        self.advance(2)
        self.assertNotEqual(self.router.assignments["P"][0], original)
        self.assertEqual(self.router.preventive_reassignments, 1)

    def test_plume_decreases_downwind_and_is_clipped_to_map(self):
        update_field(self.field, {(20, 15)}, direction="E", speed=1)
        plume = self.field.predicted_smoke
        self.assertGreater(plume[15, 23], plume[15, 35])
        self.assertLess(plume[15, 15], plume[15, 23])
        self.assertEqual(plume.shape, (31, 41))
        self.assertTrue(np.isfinite(plume).all())


class WindTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.telemetry = WindTelemetry([{"sensor_id": "S-EXT-01", "x": 244, "y": 166},
                                        {"sensor_id": "S-EXT-02", "x": 250, "y": 169}], "run")

    def test_separate_schema_preserves_global_vector_and_positions(self):
        rows = self.telemetry.sample(0, Wind("NE", .7))
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(validate_wind_observation(row), row)
            self.assertEqual(row["wind_direction"], "NE")
            self.assertEqual(row["wind_speed"], .7)
            self.assertNotIn("fire_within_2_cells", row)
        self.assertNotIn("wind_direction", COLUMNS)

    def test_duplicate_turn_does_not_rewrite_and_reverse_turn_is_rejected(self):
        self.telemetry.sample(2, Wind("E", .75))
        self.assertEqual(self.telemetry.sample(2, Wind("N", .5)), [])
        self.assertEqual(len(self.telemetry.observations), 2)
        with self.assertRaises(ValueError): self.telemetry.sample(1, Wind())

    def test_invalid_telemetry_types_and_source_are_rejected(self):
        row = self.telemetry.sample(0, Wind("E", .75))[0]
        for changes in ({"wind_speed": True}, {"wind_speed": 1.1}, {"x": -1}, {"turn": True},
                        {"data_source": "real_weather"}, {"wind_direction": "BAD"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_wind_observation({**row, **changes})

    def test_history_counts_one_time_sample_not_two_sensor_rows(self):
        history = WindHistory()
        for turn, direction in enumerate(("N", "NE", "E", "SE")):
            rows = self.telemetry.sample(turn, Wind(direction, .6))
            history.observe(rows); history.observe(rows)
        self.assertEqual([r["turn"] for r in history.measurements], [0, 1, 2, 3])
        self.assertEqual(len(self.telemetry.observations), 8)

    def test_scene_pause_manual_reset_and_old_export_are_compatible(self):
        scene = FunctionalScene(ROOT, mode="optimizado")
        self.assertEqual(scene.center.wind_telemetry.observations, [])
        scene.start()
        self.assertEqual(len(scene.center.wind_telemetry.observations), 2)
        scene.toggle_pause()
        scene.step(); scene.step()
        self.assertEqual(len(scene.center.wind_telemetry.observations), 2)
        scene.configure_wind(direction="N", speed=.5)
        scene.step(manual=True)
        self.assertEqual(len(scene.center.wind_telemetry.observations), 4)
        self.assertEqual(scene.center.wind_telemetry.current[0]["wind_direction"], "N")
        with TemporaryDirectory(prefix="dcc_wind_export_") as folder:
            paths = scene.export_readings(folder)
            self.assertIn("wind_jsonl", paths)
            old = read_sensor_package(folder)
            self.assertEqual(len(old["observables"]), 24)
            self.assertNotIn("wind_direction", old["observables"][0])
            manifest = json.loads(Path(paths["wind_manifest"]).read_text())
            self.assertEqual(manifest["data_source"], "synthetic_simulation")
        previous = scene.run_id; scene.reset()
        self.assertNotEqual(scene.run_id, previous)
        self.assertEqual(scene.run_id, scene.center.run_id)
        self.assertEqual(scene.center.wind_telemetry.observations, [])
        self.assertEqual(list(scene.center.wind_history.measurements), [])


class WindLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sequences = synthetic_sequences(seed=12, count=12, length=40)

    def test_dataset_is_causal_and_sequence_splits_do_not_overlap(self):
        groups = split_sequences(self.sequences)
        ids = [{r["sequence_id"] for r in g} for g in groups]
        self.assertFalse(ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])
        for row in temporal_examples(self.sequences, 4):
            self.assertEqual(len(row.X), 15)
            self.assertLess(max(row.feature_turns), row.target_turn)
            self.assertEqual(row.feature_turns[-1]+1, row.target_turn)

    def test_future_changes_do_not_modify_features_for_current_prediction(self):
        original = temporal_examples(self.sequences[:1], 4)[0]
        changed = deepcopy(self.sequences[:1]); changed[0]["samples"][4].update(u=.1, v=.2)
        alternative = temporal_examples(changed, 4)[0]
        self.assertEqual(original.X, alternative.X)
        self.assertNotEqual(original.y, alternative.y)

    def test_circular_350_355_0_5_is_a_small_continuous_change(self):
        vectors = [vector_from_degrees(d, .8) for d in (350, 355, 0, 5)]
        row = features(vectors, 4)
        self.assertLess(max(abs(row[-3]), abs(row[-2])), .1)
        result = metrics([vectors[2]], [vectors[1]])
        self.assertAlmostEqual(result["angular_mae_degrees"], 5, places=7)

    def test_synthetic_sequences_are_varied_and_reproducible(self):
        self.assertEqual(self.sequences, synthetic_sequences(seed=12, count=12, length=40))
        self.assertGreater(len({r["wind_direction"] for s in self.sequences for r in s["samples"]}), 4)
        self.assertTrue(all(s["data_source"] == "synthetic_simulation" for s in self.sequences))

    def test_missing_or_untrained_model_uses_persistence(self):
        provider = WindPredictor(CONFIG["wind_prediction"], ROOT / "data/nonexistent_wind_model.json")
        prediction = provider.predict([{"turn": 2, "u": .75, "v": 0}])
        self.assertEqual((prediction.u, prediction.v, prediction.turn), (.75, 0, 3))
        self.assertEqual(prediction.method, "persistence")

    def test_inference_error_cannot_stop_the_simulation(self):
        provider = WindPredictor(CONFIG["wind_prediction"], ROOT / CONFIG["wind_prediction"]["model_path"])
        rows = [{"turn": i, "u": .3+i*.1, "v": .1} for i in range(4)]
        with patch.object(provider, "_ridge", side_effect=RuntimeError("controlled failure")):
            result = provider.predict(rows)
        self.assertEqual(result.method, "persistence")
        self.assertEqual(result.fallback_reason, "inference_error")

    def test_serialized_model_matches_vectorized_sklearn_result(self):
        artifact = json.loads((ROOT / "data/wind_prediction/model.json").read_text())
        provider = WindPredictor(CONFIG["wind_prediction"], ROOT / "data/wind_prediction/model.json")
        rows = [{"turn": i, "u": .3+i*.1, "v": .2-i*.02} for i in range(4)]
        result = provider.predict(rows)
        raw = np.asarray(features([(r["u"], r["v"]) for r in rows], 4))
        expected = np.asarray(artifact["coefficients"]) @ ((raw-artifact["mean"])/artifact["scale"])+artifact["intercept"]
        if np.linalg.norm(expected) > 1: expected /= np.linalg.norm(expected)
        np.testing.assert_allclose([result.u, result.v], expected, rtol=1e-12)
        self.assertEqual(result.method, "ridge")

    def test_train_metrics_baseline_and_selection_use_validation_only(self):
        config = {**CONFIG["wind_prediction"], "minimum_training_samples": 10}
        artifact, report, _ = train(config, seed=15, count=16, length=48)
        for section in ("validation", "test"):
            for model in ("persistence", "ridge", "selected_with_fallback"):
                self.assertGreater(report[section][model]["samples"], 0)
                for metric in ("uv_rmse", "speed_mae", "angular_mae_degrees"):
                    self.assertTrue(math.isfinite(report[section][model][metric]))
        self.assertEqual(artifact["selected_model"], min(("persistence", "ridge"), key=lambda name: report["validation"][name]["uv_rmse"]))
        again, _, _ = train(config, seed=15, count=16, length=48)
        self.assertEqual(artifact, again)

    def test_prediction_does_not_modify_actual_wind(self):
        scene = FunctionalScene(ROOT, mode="optimizado"); scene.start()
        scene.configure_wind(direction="SW", speed=.6)
        scene.step()
        self.assertEqual(scene.environment.wind, Wind("SW", .6))
        self.assertEqual(scene.center.predicted_wind.turn, 2)


class PlaybackTests(unittest.TestCase):
    def test_default_is_1_75_times_faster_without_physics_parameters(self):
        clock = PlaybackClock(CONFIG["simulation_playback"])
        self.assertAlmostEqual(clock.interval_seconds, .4/1.75)
        self.assertFalse(hasattr(clock, "fire"))
        self.assertAlmostEqual(clock.set_speed(2), .2)
        with self.assertRaises(ValueError): clock.set_speed(0)

    def test_same_turns_at_1x_and_2x_have_identical_fire_smoke_and_positions(self):
        snapshot = load_campus(ROOT / "data/functional/campus.json", ROOT / "data/functional/building_entrances.json")
        outcomes, elapsed = [], []
        for speed in (1, 2):
            app = FunctionalDisasterApp(snapshot, ROOT, mode="optimizado")
            app.set_simulation_speed(speed); app.scene.start()
            wall = 0.0
            while app.scene.environment.fire.turn < 12:
                before = {p.person_id: p.position for p in app.scene.people}
                app.advance_playback(.05); wall += .05
                self.assertTrue(all(abs(p.x-before[p.person_id][0])+abs(p.y-before[p.person_id][1]) <= 1 for p in app.scene.people))
            outcomes.append((dict(app.scene.environment.fire.burning), set(app.scene.environment.fire.burned),
                np.array(app.scene.environment.smoke.concentrations), {p.person_id: p.position for p in app.scene.people}))
            elapsed.append(wall)
        self.assertEqual(outcomes[0][0:2], outcomes[1][0:2])
        np.testing.assert_array_equal(outcomes[0][2], outcomes[1][2])
        self.assertEqual(outcomes[0][3], outcomes[1][3])
        self.assertAlmostEqual(elapsed[0], elapsed[1]*2)

    def test_paused_playback_does_not_sample_or_advance(self):
        snapshot = load_campus(ROOT / "data/functional/campus.json", ROOT / "data/functional/building_entrances.json")
        app = FunctionalDisasterApp(snapshot, ROOT, mode="optimizado")
        app.scene.start(); app.scene.toggle_pause()
        self.assertEqual(app.advance_playback(10), 0)
        self.assertEqual(app.scene.environment.fire.turn, 0)
        self.assertEqual(len(app.scene.center.wind_telemetry.observations), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
