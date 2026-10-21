"""Interior precautions and presentation, using the real movement controller."""
from __future__ import annotations

from copy import deepcopy
import json
import hashlib
import inspect
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT), str(ROOT/'tests')]
from simulation.next_turn_fire import NextTurnFireThreat
from simulation.interior_prediction import PredictiveInteriorPolicy
from simulation.functional_scenario import FunctionalSimulation
from simulation.adaptive_exits import AdaptiveExitController
from simulation.indoor_people import IndoorPersonManager
from simulation.hazard_impact import ExposureTracker
from simulation.person import Person
from simulation.wind_simulation import Wind
from test_third_functional_changes import fire_for
from dcc_app.presentation_view import presentation_data, student_lines, debug_student_data, level, ZONE_LABELS, PresentationMessages, TURTLE_MESSAGE
from tools.compare_evacuation_modes import physical_digest

C = json.loads((ROOT/'data/functional_scenario.json').read_text())


class ThreatTests(unittest.TestCase):
    def make(self, laboratory=False, **options):
        fire = fire_for([['building']*25 for _ in range(25)], laboratory=laboratory, **options)
        fire.ignite(12, 12)
        threat = NextTurnFireThreat(fire, C['interior_prediction'])
        return fire, threat

    def test_now_frontier_safe_are_separate(self):
        fire, t = self.make(); t.update(Wind('E', .75))
        self.assertEqual(t.classify((12, 12)), 'FIRE_NOW')
        self.assertEqual(t.classify((13, 12)), 'FIRE_FRONTIER')
        self.assertEqual(t.classify((24, 24)), 'SAFE')

    def test_observation_never_consumes_either_rng(self):
        fire, t = self.make(spotting_enabled=True)
        before = fire.rng.getstate(), fire.spot_rng.getstate(), dict(fire.burning)
        for _ in range(3): t.update(Wind('E', .75))
        self.assertEqual(before, (fire.rng.getstate(), fire.spot_rng.getstate(), dict(fire.burning)))

    def test_real_lab_probability_increases_precaution(self):
        a, t = self.make(); b, u = self.make(laboratory=True)
        t.update(Wind('E', .75)); u.update(Wind('E', .75))
        self.assertGreater(u.probability[12, 13], t.probability[12, 13])

    def test_wind_changes_front_direction(self):
        _, t = self.make(); t.update(Wind('E', 1))
        self.assertGreater(t.probability[12, 13], t.probability[12, 11])

    def test_roads_and_burned_cells_are_not_frontier(self):
        f = fire_for([['building', 'road', 'building', 'building']]); f.ignite(0, 0)
        t = NextTurnFireThreat(f, C['interior_prediction']); t.update(Wind())
        self.assertFalse(t.frontier[0, 1]); self.assertFalse(t.frontier[0, 2])

    def test_spotting_is_directional_bounded_and_does_not_ignite(self):
        f, t = self.make(spotting_enabled=True); t.update(Wind('E', 1))
        self.assertGreater(t.spot_probability[12, 18], 0)
        self.assertEqual(t.spot_probability[12, 6], 0)
        self.assertEqual(len(f.burning), 1)


class InteriorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.manager = IndoorPersonManager(dict(width=13, height=7, default_terrain='floor', zones=[
            dict(name='E', x=3, y=1, width=7, height=5, terrain_type='building')]))
        self.person = Person('P', 4, 3, building_id='E'); self.manager.add_person(self.person)
        path = Path(self.tmp.name)/'doors.json'
        path.write_text(json.dumps(dict(width=13, height=7, accesses=[
            dict(id='west-sub1', building='E', interior_cell=dict(x=3, y=3), exterior_cell=dict(x=2, y=3)),
            dict(id='east-sub1', building='E', role='secondary', interior_cell=dict(x=9, y=3), exterior_cell=dict(x=10, y=3))])))
        self.controller = AdaptiveExitController(self.manager, path, manage_exterior=False)
        self.fire = fire_for(self.manager.terrain)
        self.threat = NextTurnFireThreat(self.fire, C['interior_prediction'])
        shape = (7, 13)
        self.risk = SimpleNamespace(fire_distance=np.full(shape, 30.), smoke=np.zeros(shape), predicted_smoke=np.zeros(shape))
        self.hazard = SimpleNamespace(fire_eta=np.full(shape, 60.), smoke_eta=np.full(shape, np.inf))
        self.hazard.time_to_fire = lambda x, y: float(self.hazard.fire_eta[y, x])
        self.hazard.time_to_smoke = lambda x, y: float(self.hazard.smoke_eta[y, x])
        self.policy = SimpleNamespace(risk=self.risk, hazard=self.hazard, fire_safety=C['fire_safety'], diagnostics={},
                                    step_safe=lambda person, p: self.hazard.fire_eta[p[1], p[0]] > 3)
        self.controller.safety_policy = self.policy
        self.interior = PredictiveInteriorPolicy(self.controller, self.threat, C['interior_prediction'])
        self.controller.predictive = self.interior
        self.tracker = ExposureTracker([self.person])

    def prepare(self, fire=()):
        for p in fire: self.fire.ignite(*p)
        self.threat.update(Wind('E', .75))
        self.interior.affected = {'E'}; self.interior.tracker = self.tracker
        blocked = set(fire) | {(int(x), int(y)) for y, x in zip(*np.nonzero(self.threat.frontier))}
        return blocked

    def test_frontier_person_moves_towards_available_safe_exit(self):
        blocked = self.prepare({(3, 3)})
        self.assertTrue(self.threat.frontier[self.person.y, self.person.x])
        old = self.person.position
        self.controller.step_with_hazards(self.tracker, blocked, priority_by_person={'P': self.interior.priority(self.person)})
        self.assertNotEqual(self.person.position, old)
        self.assertFalse(self.threat.frontier[self.person.y, self.person.x])
        self.assertGreaterEqual(self.person.x, old[0])

    def test_threatened_nearest_exit_uses_alternative(self):
        blocked = self.prepare({(3, 3)})
        for _ in range(14): self.controller.step_with_hazards(self.tracker, blocked)
        self.assertIsNone(self.person.building_id)
        self.assertEqual(self.controller.crossings['east'], 1)

    def test_preventive_move_precedes_observed_next_ignition(self):
        blocked = self.prepare({(3, 3)})
        old = self.person.position
        self.controller.step_with_hazards(self.tracker, blocked)
        # A controlled draw is only a TEST fixture; the predictor itself never
        # samples it. No same-turn cascade: the vacated neighbor burns next.
        with patch.object(self.fire.rng, 'random', return_value=0.):
            self.fire.step()
        self.assertIn(old, self.fire.burning)
        self.assertNotIn(self.person.position, self.fire.burning)

    def test_closed_exits_selects_safer_refuge(self):
        self.prepare(); self.risk.fire_distance[:, :] = np.arange(13)[None, :]
        blocked = {(2, 3), (10, 3)}
        old = self.person.position
        self.controller.step_with_hazards(self.tracker, blocked)
        self.assertGreater(self.person.x, old[0])
        self.assertEqual(self.interior.actions['interior_refuge'], 1)

    def test_refuge_prefers_branching_cells_over_avoidable_dead_end(self):
        self.prepare(); self.risk.fire_distance[:, :] = np.arange(13)[None, :]
        fields = self.interior._refuge_fields('E', {(9, 2), (9, 4)})
        goals = set().union(*(v.cells for v in fields.values()))
        self.assertNotIn((9, 3), goals)
        self.assertTrue(all(len(self.interior.neighbors[p]) >= 2 for p in goals))

    def test_fire_now_is_never_entered_when_exit_unavailable(self):
        blocked = self.prepare({(5, 3)}) | {(2, 3), (10, 3)}
        self.controller.step_with_hazards(self.tracker, blocked)
        self.assertNotIn(self.person.position, self.fire.burning)

    def test_same_component_reuses_refuge_field(self):
        self.prepare()
        a = self.interior._refuge_fields('E', set()); b = self.interior._refuge_fields('E', set())
        self.assertIs(a, b)

    def test_refuge_tier_does_not_funnel_to_an_occupied_maximum(self):
        self.prepare(); self.risk.fire_distance[:, :] = np.arange(13)[None, :]
        self.person.x, self.person.y = 9, 3
        fields = self.interior._refuge_fields('E', set())
        goals = set().union(*(v.cells for v in fields.values()))
        self.assertNotIn(self.person.position, goals)
        self.assertGreater(len(goals), 1)

    def test_refuge_offers_free_space_for_pending_building_population(self):
        self.prepare(); self.risk.fire_distance[:, :] = np.arange(13)[None, :]
        points = [p for p in self.controller._building_cells['E'] if p != self.person.position]
        for i, point in enumerate(points[:10]):
            self.manager.add_person(Person(f'Q{i}', *point, building_id='E'))
        self.interior.tracker = ExposureTracker(self.manager.people.values())
        fields = self.interior._refuge_fields('E', set())
        goals = set().union(*(v.cells for v in fields.values()))
        self.assertGreaterEqual(len(goals), 11)
        self.assertTrue(goals.isdisjoint(self.controller._occupied()))

    def test_no_threat_does_not_add_redundancy_priority(self):
        self.interior.affected.clear()
        self.assertEqual(self.interior.priority(self.person), 0)

    def dependency_queue(self):
        self.person.x, self.person.y = 5, 3
        for pid, x in [('B', 4), ('C', 3)]:
            self.manager.add_person(Person(pid, x, 3, building_id='E'))
        self.controller = AdaptiveExitController(self.manager, Path(self.tmp.name)/'doors.json', manage_exterior=False)
        self.controller.safety_policy = self.policy
        self.interior = PredictiveInteriorPolicy(self.controller, self.threat, C['interior_prediction'])
        self.controller.predictive = self.interior
        self.tracker = ExposureTracker(self.manager.people.values())
        blocked = self.prepare({(6, 3)}) | {(5, 2), (5, 4)}
        return blocked, {'P': 5000, 'B': 4000, 'C': 0}

    def test_dependency_chain_rescues_frontier_without_a_second_step(self):
        blocked, priorities = self.dependency_queue()
        before = {p.person_id:p.position for p in self.manager.people.values()}
        moved = self.controller.step_with_hazards(self.tracker, blocked, priority_by_person=priorities)
        self.assertEqual(self.person.position, (4, 3))
        self.assertEqual(self.manager.people['B'].position, (3, 3))
        self.assertEqual(self.manager.people['C'].position, (2, 3))
        self.assertEqual(moved, 3); self.assertEqual(self.controller.dependency_moves, 2)
        self.assertEqual(self.controller.waiting_last_step, 0)
        self.assertEqual(len(self.controller._occupied()), 3)
        self.assertTrue(all(abs(p.x-before[p.person_id][0])+abs(p.y-before[p.person_id][1]) == 1
                            for p in self.manager.people.values()))
        with patch.object(self.fire.rng, 'random', return_value=0.):
            self.fire.step()
        self.assertIn((5, 3), self.fire.burning)
        self.assertNotIn(self.person.position, self.fire.burning)

    def test_dependency_retry_respects_slowdown_eligibility(self):
        blocked, priorities = self.dependency_queue()
        self.tracker.records['P'].level = 'ralentizada'; self.controller.steps = 1
        self.controller.step_with_hazards(self.tracker, blocked, priority_by_person=priorities)
        self.assertEqual(self.person.position, (5, 3))

    def test_disabled_dependency_resolution_preserves_original_one_pass(self):
        blocked, priorities = self.dependency_queue()
        self.interior.config = {**self.interior.config, 'resolve_priority_dependencies': False}
        self.controller.step_with_hazards(self.tracker, blocked, priority_by_person=priorities)
        self.assertEqual(self.person.position, (5, 3))
        self.assertEqual(self.manager.people['B'].position, (4, 3))
        self.assertEqual(self.manager.people['C'].position, (2, 3))
        self.assertEqual(self.controller.dependency_moves, 0)

    def test_freed_but_dangerous_cell_is_still_forbidden_in_retry(self):
        blocked, priorities = self.dependency_queue(); blocked.add((4, 3))
        self.controller.step_with_hazards(self.tracker, blocked, priority_by_person=priorities)
        self.assertEqual(self.person.position, (5, 3))


class IntegrationAndPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = FunctionalSimulation(ROOT, mode='optimizado'); cls.s.start_alarm()

    def test_e16_single_group_diagnosis_and_preventive_priority(self):
        s = self.s; policy = s.controller.predictive
        self.assertIn('E16', policy.single_exit_buildings)
        p = next(p for p in s.people if p.building_id == 'E16')
        policy.affected = {'E16'}
        self.assertGreaterEqual(policy.priority(p), C['interior_prediction']['single_exit_threat_priority'])

    def test_e16_priority_reaches_actual_controller_before_next_fire_update(self):
        s = FunctionalSimulation(ROOT, mode='optimizado', seed=2043)
        s.select_ignition(139, 18); s.start_alarm()
        method = s.controller.step_with_hazards
        with patch.object(s.controller, 'step_with_hazards', wraps=method) as movement:
            s.step()
        priorities = movement.call_args.kwargs['priority_by_person']
        pupils = [p for p in s.people if s.origin[p.person_id] == 'E16'
                  and s.tracker.records[p.person_id].level != 'incapacitada']
        self.assertTrue(pupils)
        for p in pupils:
            d = s.controller.predictive.diagnostics[p.person_id]
            self.assertEqual(d['exit_groups'], 1)
            self.assertGreaterEqual(d['exit_redundancy_risk'], C['interior_prediction']['single_exit_threat_priority'])
            self.assertGreater(priorities[p.person_id], s.decision_policy.diagnostics[p.person_id]['priority'])

    def test_counts_are_disjoint_and_total_population_is_preserved(self):
        d = presentation_data(self.s)
        self.assertEqual(sum(d[k] for k in ('safe', 'inside', 'evacuating', 'incapacitated')), 1879)

    def test_levels_and_wind_thresholds_are_defined(self):
        self.assertEqual(level(0, [20, 100]), 'BAJO'); self.assertEqual(level(20, [20, 100]), 'MEDIO')
        self.assertEqual(level(100, [20, 100]), 'ALTO')

    def test_student_presentation_hides_technical_fields(self):
        text = '\n'.join(student_lines(self.s, self.s.people[0].person_id))
        for forbidden in ('ETA', 'margin', 'Ridge', 'WAITING', 'score', 'prioridad'):
            self.assertNotIn(forbidden, text)

    def test_traditional_debug_reads_observed_eta_without_inventing_personal_margin(self):
        s = FunctionalSimulation(ROOT, mode='optimizado', evacuation_mode='traditional')
        p = s.people[0]; x, y = p.position
        s.hazard_arrival.fire_eta[y, x] = 2; s.hazard_arrival.smoke_eta[y, x] = 7
        s.risk_field.smoke[y, x] = .1; s.tracker.records[p.person_id].dose = 2.
        data = debug_student_data(s, p.person_id)
        self.assertEqual(data['fire_eta'], 2); self.assertEqual(data['smoke_eta'], 7)
        # Smoke is stored as float32: 0.1 is not exactly representable.
        self.assertAlmostEqual(data['toxic_dose_eta'], 7.5, delta=1e-6)
        self.assertIsNone(data['safety_margin']); self.assertIsNone(data['priority'])
        self.assertEqual(s.tracker.records[p.person_id].dose, 2.)

    def test_zone_states_are_spanish(self):
        self.assertEqual(set(ZONE_LABELS.values()), {'SEGURA', 'PRECAUCIÓN', 'EVITAR', 'CERRADA'})

    def test_avoided_zone_is_not_presented_as_safe_even_in_traditional(self):
        p = Person('P', 0, 0)
        center = SimpleNamespace(people=[p], tracker=ExposureTracker([p]), config=C,
            router=SimpleNamespace(at_meeting=lambda p: True, safe={'R': True}, assignments={'P': ('R', (0, 0))},
                                   area_policy=SimpleNamespace(states={'R': 'AVOID'})),
            environment=SimpleNamespace(fire=SimpleNamespace(burning={}), smoke=SimpleNamespace(concentrations=[[0.]])),
            areas=[SimpleNamespace(area_id='R', enabled=True)], direction='E', intensity=.75, decision_policy=None)
        data = presentation_data(center)
        self.assertEqual(data['safe'], 0); self.assertEqual(data['evacuating'], 1)
        self.assertEqual(data['available'], 0)

    def test_message_queue_aggregates_limits_expires_and_resets(self):
        s = self.s; q = PresentationMessages(C['presentation']); q.observe(s, 0)
        old = s.router.replanned_routes; turn = s.environment.fire.turn
        try:
            s.router.replanned_routes += 18; s.environment.fire.turn += 1
            messages = q.observe(s, 1)
            self.assertEqual(sum('18 alumnos' in t for t in messages), 1)
            self.assertLessEqual(len(messages), 3); self.assertEqual(q.observe(s, 10), [])
        finally:
            s.router.replanned_routes = old; s.environment.fire.turn = turn

    def test_presentation_render_and_double_debug_are_visual_only(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy'); os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
        import pygame
        from dcc_app.functional_application import FunctionalDisasterApp
        from dcc_app.model import load_campus
        assets = ROOT/'data/functional'
        app = FunctionalDisasterApp(load_campus(assets/'campus.json', assets/'building_entrances.json'), ROOT, mode='optimizado')
        app.scene.start(); app.scene.center.toggle_pause()
        before = physical_digest(app.scene.center), [p.position for p in app.scene.people]
        modes = []
        debug_text = []
        original_speed = app.playback.speed_multiplier
        original_flip = pygame.display.flip
        def flip_and_toggle():
            original_flip()
            modes.append(app.debug_risk)
            if app.debug_risk:
                debug_text.extend(app.visible_debug_text)
            if len(modes) < 3:
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_d))
                key = pygame.K_PLUS if len(modes) == 1 else pygame.K_MINUS
                pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key))
        # Keep one SDL lifetime: run() intentionally quits pygame on return.
        with patch.object(pygame.display, 'flip', side_effect=flip_and_toggle):
            app.run(smoke_test=True)
        self.assertEqual(modes, [False, True, False])
        self.assertTrue(any('SafetyScore' in line for line in debug_text))
        self.assertEqual(app.playback.speed_multiplier, original_speed)
        text = '\n'.join(app.visible_presentation_text)
        for word in ('ETA', 'margin', 'Ridge', 'persistencia', 'SafetyScore', 'schema', 'cache', 'SAFE'):
            self.assertNotIn(word, text)
        for word in ('VIENTO', 'Velocidad', 'EN ZONA SEGURA', 'INCAPACITADOS', 'INCENDIO', 'HUMO', 'Zonas', 'MODO', TURTLE_MESSAGE):
            self.assertIn(word, text)
        self.assertFalse(app.debug_risk)
        self.assertEqual(before, (physical_digest(app.scene.center), [p.position for p in app.scene.people]))

    def test_new_split_preserves_original_fire_contact_metric(self):
        result = self.s.metrics.result(self.s)
        self.assertEqual(result['fire_contacts'], result['interior_fire_contacts']+result['exterior_fire_contacts'])

    def test_escape_counter_requires_observed_later_fire_not_just_a_forecast(self):
        s = self.s; metrics = s.metrics
        person = s.people[0]
        point = s.ignition_cell
        event = dict(person_id=person.person_id, point=point, departure_turn=-1)
        old_pending = metrics.pending_frontier_escapes[:]
        old_confirmed = metrics.confirmed_frontier_escapes[:]
        try:
            # The pending departure is confirmed only because that point is
            # actually burning now and the person is no longer there.
            metrics.pending_frontier_escapes.append(event)
            metrics.sample(s, {p.person_id:p.position for p in s.people})
            self.assertIn({**event, 'confirmed_turn': 0}, metrics.confirmed_frontier_escapes)
            self.assertNotIn(event, metrics.pending_frontier_escapes)
            clean = dict(person_id=person.person_id, point=person.position, departure_turn=0)
            metrics.pending_frontier_escapes.append(clean)
            metrics.sample(s, {p.person_id:p.position for p in s.people})
            self.assertIn(clean, metrics.pending_frontier_escapes)
            late = dict(person_id=person.person_id, point=point, departure_turn=-4)
            metrics.pending_frontier_escapes.append(late)
            count = len(metrics.confirmed_frontier_escapes)
            metrics.sample(s, {p.person_id:p.position for p in s.people})
            self.assertEqual(len(metrics.confirmed_frontier_escapes), count)
            self.assertNotIn(late, metrics.pending_frontier_escapes)
        finally:
            metrics.pending_frontier_escapes = old_pending
            metrics.confirmed_frontier_escapes = old_confirmed


class GeometryCacheTests(unittest.TestCase):
    def test_cached_geometry_equals_full_validation_at_every_remaining_step(self):
        from test_sixth_functional_changes import configured
        _, _, policy, _, hazard = configured()
        path = [(x, 10) for x in range(12, 25)]
        hazard.fire_eta[10, 20] = 15
        for factor in (1., 2.):
            for step in range(len(path)):
                self.assertEqual(policy.route_fire_margin('P', path, step, factor),
                                 policy.minimum_fire_margin(path[step:], factor))

    def test_new_hazard_is_not_hidden_by_coordinate_cache(self):
        from test_sixth_functional_changes import configured
        _, _, policy, _, hazard = configured()
        path = [(12, 10), (13, 10), (14, 10)]
        policy.route_fire_margin('P', path, 0)
        hazard.fire_eta[10, 13] = 0
        self.assertEqual(policy.route_fire_margin('P', path, 0), policy.minimum_fire_margin(path))
        self.assertLess(policy.route_fire_margin('P', path, 0), 0)

    def test_in_place_path_edit_invalidates_geometry(self):
        from test_sixth_functional_changes import configured
        _, _, policy, _, hazard = configured()
        path = [(12, 10), (13, 10), (14, 10)]
        policy.route_fire_margin('P', path, 0)
        path[1] = (12, 11); hazard.fire_eta[11, 12] = 1
        self.assertEqual(policy.route_fire_margin('P', path, 0), policy.minimum_fire_margin(path))


class ReportProvenanceTests(unittest.TestCase):
    def fixture(self, root):
        import tools.compare_evacuation_modes_v3 as v3
        contents = {'src/dcc_app/presentation_view.py': 'display version one',
                    'src/simulation/core.py': 'unchanged backend', 'data/campus.json': '{}'}
        for name, text in contents.items():
            path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        manifest = dict(benchmark_source_hash='execution',
            files={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in contents},
            allowed_ui_files=['src/dcc_app/presentation_view.py'], headless_backend_imports_no_dcc_app=True,
            run_case_source_sha256=hashlib.sha256(inspect.getsource(v3.run_case).encode()).hexdigest(),
            physical_digest_source_sha256=hashlib.sha256(inspect.getsource(v3.physical_digest).encode()).hexdigest())
        directory = root/'reports/septima_fase'; directory.mkdir(parents=True)
        (directory/'ui_revision_manifest.json').write_text(json.dumps(manifest))
        (directory/'performance_after.json').write_text(json.dumps(dict(source_hash='final', turns=240, seconds_per_turn=.7)))
        output = root/'output'; output.mkdir()
        report = dict(source_hash='execution', metrics={'fire_contacts': 7}, readiness_checks={})
        return v3, output, report

    def test_ui_revision_preserves_execution_hash_and_actual_metrics(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); v3, output, report = self.fixture(root)
            (root/'src/dcc_app/presentation_view.py').write_text('display version two')
            with patch.object(v3, 'ROOT', root), patch.object(v3, 'input_fingerprint', return_value='final'):
                result = v3.finalize(report, output)
            self.assertEqual(result['source_hash'], 'execution')
            self.assertEqual(result['final_source_hash'], 'final')
            self.assertEqual(result['metrics']['fire_contacts'], 7)
            self.assertTrue(result['validated_ui_only_revision']['backend_and_all_data_unchanged'])

    def test_backend_change_cannot_be_relabelled_as_visual(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); v3, output, report = self.fixture(root)
            (root/'src/simulation/core.py').write_text('changed backend')
            with patch.object(v3, 'ROOT', root), patch.object(v3, 'input_fingerprint', return_value='final'):
                with self.assertRaises(AssertionError):
                    v3.finalize(report, output)

    def test_data_change_cannot_be_relabelled_as_visual(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); v3, output, report = self.fixture(root)
            (root/'data/campus.json').write_text('{"changed": true}')
            with patch.object(v3, 'ROOT', root), patch.object(v3, 'input_fingerprint', return_value='final'):
                with self.assertRaises(AssertionError):
                    v3.finalize(report, output)



if __name__ == '__main__':
    unittest.main(verbosity=2)
