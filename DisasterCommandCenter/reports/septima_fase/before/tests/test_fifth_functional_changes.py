"""Predictive evacuation: decisions checked through real gateway movement."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT)]
from routing.graph import CampusGraph
from routing.meeting_areas import MeetingArea, MeetingRouter
from routing.meeting_policy import MeetingAreaPolicy
from routing.intelligent_policy import IntelligentEvacuationPolicy
from simulation.campus_map import CampusMap
from simulation.dynamic_risk import DynamicRiskField
from simulation.hazard_arrival import HazardArrivalField
from simulation.person import Person
from simulation.person_manager import PersonManager
from simulation.wind_simulation import Wind, WindSmokeSimulation
from wind_prediction.model import vector_prediction
from simulation.functional_scenario import FunctionalSimulation
from simulation.evacuation_metrics import EvacuationMetrics
from simulation.hazard_impact import ExposureTracker
from tools.compare_evacuation_modes import physical_digest, aggregate

C = json.loads((ROOT/'data/functional_scenario.json').read_text())


def fixture(*, mode='intelligent', areas=None, position=(12, 10), budget=24):
    campus = CampusMap(31, 21); campus.fill_terrain('floor')
    graph = CampusGraph(campus)
    manager = PersonManager(31, 21, graph.is_valid)
    person = Person('P', *position); manager.add_person(person)
    areas = areas or [MeetingArea('W', 'test', 'left', (1, 8, 3, 5), tuple((x, y) for x in range(1, 4) for y in range(8, 13))),
                      MeetingArea('E', 'test', 'right', (23, 8, 3, 5), tuple((x, y) for x in range(23, 26) for y in range(8, 13)))]
    risk = DynamicRiskField([['floor']*31 for _ in range(21)], {**C['risk_routing'], 'plume_stride': 1, 'fire_radius': 3})
    hazard = HazardArrivalField(risk.terrain, C['hazard_arrival'], C['fire_behavior'], C['smoke_behavior'])
    policy = IntelligentEvacuationPolicy(risk, hazard, {**C['intelligent_evacuation'], 'safety_buffer_turns': 2}, C['route_safety'], C['meeting_assignment'])
    router = MeetingRouter(graph, manager, 'test', areas, risk_field=risk,
        area_policy=MeetingAreaPolicy(areas, C['meeting_area_policy'], .3),
        decision_policy=policy if mode == 'intelligent' else None, evacuation_mode=mode, max_routes_per_turn=budget)
    router.budget_config = {**C['route_scheduling'], 'burst_pending_threshold': 999}
    update(risk, hazard)
    return router, person, policy, risk, hazard


def update(risk, hazard, *, fire=(), direction='E', speed=.75, turn=1, smoke=None):
    wind = Wind(direction, speed)
    future = vector_prediction(turn+1, wind.vector[0]*speed, wind.vector[1]*speed, 'persistence')
    smoke = np.zeros(risk.terrain.shape) if smoke is None else smoke
    risk.update(fire, smoke, wind, future, turn=turn)
    hazard.update(risk, wind, future)


def advance(router, policy, risk, turn=1, *, blocked=(), priorities=None):
    router.assess(risk.smoke, set(), blocked_cells=blocked)
    for p in router.manager.list_people():
        policy.inspect(p, router, turn)
    priorities = priorities or {p.person_id: policy.priority_score(p.person_id) for p in router.manager.list_people()}
    return router.advance(risk.smoke, set(), blocked, priorities, {p.person_id for p in router.manager.list_people()}, turn)


class PredictiveMovementTests(unittest.TestCase):
    def test_01_stationary_group_leaves_before_actual_smoke_arrives(self):
        area = MeetingArea('RESIDENT', 'test', 'right', (12, 9, 1, 3), ((12, 9), (12, 10), (12, 11)))
        safe = MeetingArea('W', 'test', 'left', (1, 8, 3, 5), tuple((x, y) for x in range(1, 4) for y in range(8, 13)))
        router, person, policy, risk, hazard = fixture(areas=[area, safe])
        # Already stationary residents; arrival is not permission to remain forever.
        advance(router, policy, risk)
        group = [person]
        for i, y in enumerate((9, 11)):
            p = Person(f'P{i}', 12, y); router.manager.add_person(p); group.append(p)
        smoke = WindSmokeSimulation(31, 21, **C['smoke_behavior']); smoke.set_wind(Wind('E', .75))
        old = {p.person_id: p.position for p in group}
        for turn in range(2, 7):
            smoke.step({(7, 10)})
            update(risk, hazard, fire={(7, 10)}, smoke=smoke.concentrations, turn=turn)
            advance(router, policy, risk, turn, blocked={(7, 10)})
        self.assertTrue(all(p.position != old[p.person_id] for p in group))
        self.assertTrue(all(smoke.concentrations[y][x] < C['route_smoke_threshold'] for x, y in old.values()))
        self.assertTrue(all(p.x < 12 or abs(p.y-10) > 1 for p in group))

    def test_02_safe_waiting_resident_does_not_move(self):
        area = MeetingArea('HOME', 'test', 'left', (12, 10, 1, 1), ((12, 10),))
        router, person, policy, risk, hazard = fixture(areas=[area])
        for turn in range(1, 8):
            advance(router, policy, risk, turn)
        self.assertEqual(person.position, (12, 10))
        self.assertEqual(policy.states['P'], 'AT_MEETING_AREA')

    def test_03_upwind_destination_beats_nearer_downwind(self):
        router, person, policy, risk, hazard = fixture(position=(18, 10))
        for turn in range(1, 26):
            update(risk, hazard, fire={(14, 10)}, turn=turn)
            advance(router, policy, risk, turn, blocked={(14, 10)})
            self.assertNotEqual(router.assignments.get('P', (None,))[0], 'E')
            if router.assignments.get('P', (None,))[0] == 'W':
                break
        self.assertEqual(router.assignments['P'][0], 'W')

    def test_04_short_temporally_unsafe_route_is_rejected(self):
        router, person, policy, risk, hazard = fixture()
        hazard.eta[10, 16:23] = 2
        path = [(x, 10) for x in range(12, 24)]
        self.assertEqual(policy.validate_route(path).state, 'UNSAFE')

    def test_05_longer_safe_route_is_accepted(self):
        router, person, policy, risk, hazard = fixture()
        hazard.eta[10, 16:23] = 2
        path = [(12, y) for y in range(10, 5, -1)]+[(x, 6) for x in range(13, 25)]+[(24, y) for y in range(7, 11)]
        self.assertEqual(policy.validate_route(path).state, 'SAFE')

    def test_06_no_full_route_gets_intermediate_and_physically_moves(self):
        area = MeetingArea('UNAVAILABLE', 'test', 'right', (24, 10, 1, 1), ((24, 10),), enabled=False)
        router, person, policy, risk, hazard = fixture(areas=[area])
        hazard.eta[:, 10:16] = 10
        risk.costs[:, 10:16] = 30
        start = person.position
        advance(router, policy, risk)
        self.assertIn('P', router.temporary)
        self.assertNotEqual(person.position, start)
        self.assertEqual(abs(person.x-start[0])+abs(person.y-start[1]), 1)

    def test_07_critical_high_id_precedes_safe_low_id(self):
        router, safe, policy, risk, hazard = fixture(budget=1, position=(2, 2))
        critical = Person('ZZZ', 12, 10); router.manager.add_person(critical)
        hazard.eta[10, 12] = 2
        advance(router, policy, risk)
        self.assertEqual(router.last_planning_order, ['ZZZ'])

    def test_negative_margin_escapes_before_expensive_full_route_search(self):
        from unittest.mock import patch
        router, person, policy, risk, hazard = fixture()
        hazard.eta[10, 12] = 1
        start = person.position
        with patch('routing.meeting_areas.calculate_congestion_route') as search:
            advance(router, policy, risk)
        self.assertFalse(search.called)
        self.assertNotEqual(person.position, start)
        self.assertIn('P', router.temporary)

    def test_08_old_safe_waiter_eventually_receives_plan(self):
        router, person, policy, risk, hazard = fixture(budget=1)
        # A continuous stream of new urgent requests must not starve the old
        # safe request. The age grows from real unchanged positions, not a mock.
        for turn in range(1, 46):
            newcomer = Person(f'NEW{turn:03}', 1+(turn % 25), 1+turn//25)
            if not any(p.position == newcomer.position for p in router.manager.list_people()):
                router.manager.add_person(newcomer)
            for p in router.manager.list_people(): policy.inspect(p, router, turn)
            priorities = {p.person_id: (policy.priority_score('P') if p.person_id == 'P' else 300)
                          for p in router.manager.list_people()}
            router.advance(risk.smoke, set(), set(), priorities,
                           {p.person_id for p in router.manager.list_people()}, turn)
            if 'P' in router.assignments: break
        self.assertIn('P', router.assignments)
        self.assertLessEqual(turn, 45)

    def test_09_destination_future_hazard_overrides_cooldown(self):
        router, person, policy, risk, hazard = fixture(position=(20, 10))
        advance(router, policy, risk)
        self.assertEqual(router.assignments['P'][0], 'E')
        hazard.eta[8:13, 23:26] = 2
        advance(router, policy, risk, 2)
        self.assertNotEqual(router.assignments.get('P', (None,))[0], 'E')
        self.assertGreater(router.preventive_reassignments, 0)

    def test_10_safe_meeting_is_sticky_without_pingpong(self):
        router, person, policy, risk, hazard = fixture()
        advance(router, policy, risk)
        first = router.assignments['P'][0]
        for turn in range(2, 12):
            advance(router, policy, risk, turn)
            self.assertEqual(router.assignments['P'][0], first)
        self.assertFalse(router.destination_changes)

    def test_routes_go_around_stationary_residents_in_both_modes(self):
        for mode in ('intelligent', 'traditional'):
            home = MeetingArea('HOME', 'test', 'right', (15, 10, 1, 1), ((15, 10),))
            far = MeetingArea('FAR', 'test', 'right', (24, 10, 1, 1), ((24, 10),))
            router, person, policy, risk, hazard = fixture(mode=mode, areas=[home, far])
            body = Person('BODY', 15, 10); router.manager.add_person(body)
            if mode == 'traditional':
                router.fixed_destinations.update(BODY='HOME', P='FAR')
            advance(router, policy, risk, 1)
            self.assertEqual(body.position, (15, 10))
            advance(router, policy, risk, 2)
            self.assertIn((15, 10), router.routing_obstacles)
            self.assertNotIn((15, 10), router.paths['P'])
            self.assertEqual(body.position, (15, 10))

    def test_11_threatened_resident_leaves_before_current_danger(self):
        home = MeetingArea('HOME', 'test', 'right', (12, 10, 1, 1), ((12, 10),))
        safe = MeetingArea('W', 'test', 'left', (1, 10, 1, 1), ((1, 10),))
        router, person, policy, risk, hazard = fixture(areas=[home, safe])
        advance(router, policy, risk)
        self.assertEqual(person.position, (12, 10))
        hazard.eta[10, 12] = 5
        advance(router, policy, risk, 2)
        self.assertNotEqual(person.position, (12, 10))
        self.assertEqual(float(risk.smoke[10, 12]), 0)

    def test_12_traditional_does_not_use_prediction_for_route_or_goal(self):
        router, person, policy, risk, hazard = fixture(mode='traditional', position=(20, 10))
        hazard.eta[8:13, 23:26] = 0
        risk.predicted_smoke[:, :] = 1
        risk.costs[:] = 10000
        advance(router, policy, risk)
        self.assertIsNone(router.decision_policy)
        self.assertIsNone(router._route_cost())
        self.assertEqual(router.assignments['P'][0], 'E')
        self.assertEqual(router.preventive_reassignments, 0)

    def test_13_intelligent_consults_forecast(self):
        router, person, policy, risk, hazard = fixture(position=(20, 10))
        hazard.eta[8:13, 23:26] = 0
        advance(router, policy, risk)
        self.assertEqual(router.assignments['P'][0], 'W')


class ArrivalFieldTests(unittest.TestCase):
    def test_astar_cost_cache_is_local_and_reads_each_cell_once(self):
        from collections import Counter
        from routing.weighted_astar import weighted_astar
        router, person, policy, risk, hazard = fixture()
        class ReadOnlyCost:
            def __init__(self): self.reads = Counter()
            def risk_cost(self, x, y):
                self.reads[x, y] += 1
                return 1.
        cost = ReadOnlyCost()
        path = weighted_astar(router.graph, (1, 1), (28, 18), risk_field=cost)
        self.assertIsNotNone(path)
        self.assertTrue(cost.reads)
        self.assertEqual(max(cost.reads.values()), 1)

    def test_astar_new_search_sees_changed_costs(self):
        from routing.weighted_astar import weighted_astar
        router, person, policy, risk, hazard = fixture()
        risk.costs[10, 13:21] = 20
        first = weighted_astar(router.graph, (12, 10), (22, 10), risk_field=risk)
        self.assertTrue(any(y != 10 for x, y in first))
        risk.costs.fill(0)
        second = weighted_astar(router.graph, (12, 10), (22, 10), risk_field=risk)
        self.assertEqual(second, [(x, 10) for x in range(12, 23)])
    def test_empty_field_is_infinite_and_zero_cost(self):
        _, _, _, _, hazard = fixture()
        self.assertTrue(np.isinf(hazard.eta).all())
        self.assertEqual(float(hazard.urgency_cost.max()), 0)

    def test_wind_reversal_changes_eta_without_changing_real_wind(self):
        _, _, _, risk, hazard = fixture()
        update(risk, hazard, fire={(15, 10)}, direction='E')
        self.assertLess(hazard.time_to_hazard(25, 10), hazard.time_to_hazard(5, 10))
        update(risk, hazard, fire={(15, 10)}, direction='W')
        self.assertGreater(hazard.time_to_hazard(25, 10), hazard.time_to_hazard(5, 10))

    def test_current_smoke_and_fire_are_immediate_hazards(self):
        _, _, _, risk, hazard = fixture()
        smoke = np.zeros((21, 31)); smoke[1, 1] = .65
        update(risk, hazard, fire={(15, 10)}, smoke=smoke)
        self.assertEqual(hazard.time_to_hazard(1, 1), 0)
        self.assertEqual(hazard.time_to_hazard(15, 10), 0)

    def test_calm_wind_is_isotropic_and_not_instantaneous_everywhere(self):
        _, _, _, risk, hazard = fixture()
        update(risk, hazard, fire={(15, 10)}, speed=0)
        self.assertGreater(hazard.time_to_hazard(20, 10), 0)
        self.assertAlmostEqual(hazard.time_to_hazard(20, 10), hazard.time_to_hazard(10, 10))
        self.assertAlmostEqual(hazard.time_to_hazard(15, 15), hazard.time_to_hazard(20, 10))

    def test_slowed_eta_is_longer_and_route_margin_smaller(self):
        from simulation.hazard_impact import Exposure
        router, person, policy, risk, hazard = fixture()
        ordinary = policy.evacuation_eta(person, router)
        self.assertGreater(policy.evacuation_eta(person, router, exposure=Exposure(level='ralentizada')), ordinary)

    def test_burst_budget_has_same_bound_in_both_modes(self):
        for mode in ('traditional', 'intelligent'):
            router, person, policy, risk, hazard = fixture(mode=mode, budget=1)
            router.budget_config['burst_pending_threshold'] = 1
            router.budget_config['emergency_route_budget'] = 2
            router.manager.add_person(Person('OTHER', 10, 2))
            advance(router, policy, risk)
            self.assertEqual(router.last_budget, 2)
            self.assertLessEqual(len(router.last_planning_order), 2)

    def test_event_notifications_are_throttled(self):
        _, _, policy, _, _ = fixture()
        for turn in range(20): policy.emit(turn, 'forecast', 'mensaje')
        self.assertEqual([x['turn'] for x in policy.events], [0, 8, 16])

    def test_component_precheck_matches_graph_and_allows_escape_from_blocked_origin(self):
        from routing.weighted_astar import weighted_astar
        router, person, policy, risk, hazard = fixture()
        router.graph.cache_static_topology()
        wall = {(15, y) for y in range(21)}
        self.assertFalse(router._can_reach_goal((12, 10), (24, 10), wall))
        self.assertIsNone(weighted_astar(router.graph, (12, 10), (24, 10), blocked_cells=wall))
        self.assertTrue(router._can_reach_goal((12, 10), (1, 10), wall))
        self.assertIsNotNone(weighted_astar(router.graph, (12, 10), (1, 10), blocked_cells=wall))
        # A critical origin may still exit through a free neighbor.
        blocks = wall | {(12, 10)}
        self.assertTrue(router._can_reach_goal((12, 10), (1, 10), blocks))
        self.assertIsNotNone(weighted_astar(router.graph, (12, 10), (1, 10), blocked_cells=blocks-{(12, 10)}))
        # Reopening a bridge invalidates the component cache.
        wall.remove((15, 10))
        self.assertTrue(router._can_reach_goal((12, 10), (24, 10), wall))

    def test_budget_caps_actual_astar_searches_not_only_people(self):
        from unittest.mock import patch
        from routing.congestion_route_adapter import calculate_congestion_route
        areas = [MeetingArea(f'E{i}', 'test', 'right', (24, y, 1, 1), ((24, y),)) for i, y in enumerate((8, 10, 12))]
        router, person, policy, risk, hazard = fixture(areas=areas, position=(3, 10), budget=2)
        router.manager.add_person(Person('SECOND', 3, 11))
        hazard.eta[:, 14:17] = 0  # Each short route is temporally unsafe.
        with patch('routing.meeting_areas.calculate_congestion_route', wraps=calculate_congestion_route) as call:
            advance(router, policy, risk)
        self.assertEqual(call.call_count, 2)
        self.assertEqual(router.last_searches, 2)
        self.assertLessEqual(router.maximum_searches_used, router.last_budget)


class PhysicalCompatibilityTests(unittest.TestCase):
    def test_paired_modes_keep_identical_fire_smoke_and_one_cell_per_turn(self):
        modes = [FunctionalSimulation(ROOT, mode='optimizado', evacuation_mode=m, seed=128) for m in ('traditional', 'intelligent')]
        for s in modes: s.start_alarm()
        for turn in range(8):
            for s in modes:
                previous = {p.person_id: p.position for p in s.people}
                s.set_wind('NE' if turn >= 4 else 'E', .7)
                s.step()
                self.assertEqual(len({p.position for p in s.people}), 1879)
                self.assertTrue(all(abs(p.x-previous[p.person_id][0])+abs(p.y-previous[p.person_id][1]) <= 1 for p in s.people))
                self.assertLessEqual(s.router.maximum_budget_used, C['route_scheduling']['emergency_route_budget'])
            self.assertEqual(physical_digest(modes[0]), physical_digest(modes[1]))


class MeasurementTests(unittest.TestCase):
    def test_departure_from_already_dangerous_cell_is_reactive_not_prevention(self):
        from types import SimpleNamespace
        router, person, policy, risk, hazard = fixture()
        s = SimpleNamespace(risk_field=risk, hazard_arrival=hazard, config=C, people=[person],
            tracker=ExposureTracker([person]), router=router, controller=None, manager=router.manager,
            decision_policy=policy, environment=SimpleNamespace(fire=SimpleNamespace(turn=1)))
        metrics = EvacuationMetrics(s)
        old = person.position
        risk.smoke[old[1], old[0]] = .65
        router.forecast_departure_candidates['P'] = dict(turn=1, point=old, reason='unsafe_wait')
        person.x += 1
        metrics.sample(s, {'P': old})
        s.environment.fire.turn = 2
        metrics.sample(s, {'P': person.position})
        self.assertEqual(len(metrics.confirmed_departures), 0)
        self.assertEqual(metrics.rejected_current_danger_departures, 1)

    def test_replan_alone_is_not_a_confirmed_forecast_departure(self):
        from types import SimpleNamespace
        router, person, policy, risk, hazard = fixture()
        s = SimpleNamespace(risk_field=risk, hazard_arrival=hazard, config=C, people=[person],
            tracker=ExposureTracker([person]), router=router, controller=None, manager=router.manager,
            decision_policy=policy, environment=SimpleNamespace(fire=SimpleNamespace(turn=1)))
        metrics = EvacuationMetrics(s)
        router.forecast_departure_candidates['P'] = dict(turn=1, point=person.position, reason='unsafe_wait')
        old = person.position
        metrics.sample(s, {'P': old})
        self.assertFalse(metrics.pending_departures)
        self.assertFalse(metrics.confirmed_departures)
        person.x += 1
        metrics.sample(s, {'P': old})
        self.assertEqual(len(metrics.pending_departures), 1)
        self.assertFalse(metrics.confirmed_departures)
        # Actual subsequent danger at the abandoned cell, with person elsewhere.
        risk.smoke[old[1], old[0]] = .65
        s.environment.fire.turn = 2
        metrics.sample(s, {'P': person.position})
        self.assertEqual(len(metrics.confirmed_departures), 1)
        self.assertEqual(metrics.result(s)['confirmed_forecast_departures'], 1)

    def test_aggregate_does_not_claim_improvement_when_traditional_wins(self):
        base = dict(people_exposed_smoke=3, accumulated_smoke_dose=4., people_close_to_fire=1, fire_contacts=0,
            incapacitated=1, unsafe_waiting_person_turns=3, destination_became_unsafe_before_arrival=1,
            people_in_cells_that_later_became_hazardous=2, safe_meeting_arrivals=10, people_ever_reached_meeting=12)
        cases = [dict(traditional=dict(metrics=base), intelligent=dict(metrics={**base, 'incapacitated': 2}))]
        result = aggregate(cases)
        self.assertFalse(result['consistent_risk_improvement'])
        self.assertEqual(result['paired_risk_comparison']['incapacitated']['traditional_wins'], 1)

    def test_arrival_field_can_be_disabled_without_touching_physics(self):
        s = FunctionalSimulation(ROOT, mode='optimizado')
        s.config['intelligent_evacuation']['hazard_eta_enabled'] = False
        s.start_alarm()
        self.assertTrue(np.isinf(s.hazard_arrival.eta).all())
        self.assertEqual(s.environment.fire.total_ignitions, 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
