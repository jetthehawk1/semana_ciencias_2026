"""Safety decisions tested through the actual gateway, without changing physics."""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'tests')]
from test_fifth_functional_changes import fixture,update,advance,C
from simulation.hazard_impact import Exposure
from simulation.personal_safety import toxic_dose_eta,personal_hazard_eta
from simulation.safety_score import safety_score
from simulation.person import Person
from routing.meeting_areas import MeetingArea
from routing.meeting_flow import MeetingFlowField
from routing.safe_routing import UNASSIGNED_REASONS,improves_route,scheduling_order
from simulation.functional_scenario import FunctionalSimulation
from tools.compare_evacuation_modes import physical_digest
from tools.compare_evacuation_modes_v2 import benchmark_scenarios,report_json


def configured(**kwargs):
    router,person,policy,risk,hazard=fixture(**kwargs)
    router.sixth_config=deepcopy(C)
    policy.fire_safety=C['fire_safety'];hazard.fire_safety=C['fire_safety']
    policy.personal_config=C['personal_safety'];policy.escape_config=C['escape_policy'];policy.stability_config=C['route_stability']
    return router,person,policy,risk,hazard


class FireSafetyTests(unittest.TestCase):
    def test_fire_1_all_points_reject_between_smoke_samples(self):
        r,p,policy,risk,h=configured()
        path=[(x,10) for x in range(12,25)]
        h.fire_eta[10,14]=2  # skipped by the old stride-three validation
        self.assertEqual(policy.validate_route(path).state,'UNSAFE')

    def test_fire_2_gateway_watchdog_stops_new_fire_after_planning(self):
        r,p,policy,risk,h=configured();advance(r,policy,risk)
        before=p.position; status=r.follower.route_snapshot('P')
        target=r.paths['P'][status['steps_done']+1]
        risk.fire_distance[target[1],target[0]]=0
        moved=r.follower.step(eligible_person_ids={'P'},before_step=lambda person,point:policy.step_safe(person,point))
        self.assertEqual(moved,0);self.assertEqual(p.position,before)
        self.assertEqual(r.follower.route_status('P'),'bloqueada_por_riesgo')

    def test_fire_3_marginal_fire_margin_is_hard_not_cost(self):
        r,p,policy,risk,h=configured()
        h.fire_eta[10,13]=C['fire_safety']['route_margin_turns']+1
        self.assertEqual(policy.validate_route([(12,10),(13,10)]).state,'UNSAFE')

    def test_fire_4_no_alternative_never_steps_into_fire(self):
        r,p,policy,risk,h=configured();start=p.position
        h.fire_eta.fill(0);risk.fire_distance.fill(0)
        advance(r,policy,risk,blocked={(x,y) for y in range(21) for x in range(31) if (x,y)!=start})
        self.assertEqual(p.position,start);self.assertNotIn('P',r.assignments)

    def test_components_are_exposed_separately(self):
        r,p,policy,risk,h=configured();update(risk,h,fire={(12,10)})
        self.assertEqual(h.time_to_fire(12,10),0)
        self.assertTrue(math.isfinite(h.time_to_smoke(12,10)))
        self.assertLessEqual(h.time_to_hazard(12,10),h.time_to_fire(12,10))

    def test_fire_has_no_escape_grace_exception(self):
        _,_,policy,_,h=configured();h.eta[10,12]=0;h.fire_eta[10,13]=1
        self.assertEqual(policy.validate_route([(12,10),(13,10)]).state,'UNSAFE')

    def test_extreme_prediction_blocks_next_step(self):
        _,p,policy,risk,_=configured();risk.predicted_smoke[10,13]=.95
        self.assertFalse(policy.step_safe(p,(13,10)))

    def test_critical_smoke_blocks_next_step(self):
        _,p,policy,risk,_=configured();risk.smoke[10,13]=C['route_smoke_threshold']
        self.assertFalse(policy.step_safe(p,(13,10)))


class DoseTests(unittest.TestCase):
    def test_high_dose_in_moderate_smoke_is_critical(self):
        r,p,policy,risk,h=configured();risk.smoke[10,12]=.1
        exposure=Exposure(dose=2.7,level='ralentizada')
        d=policy.inspect(p,r,1,exposure=exposure)
        self.assertLess(d['toxic_dose_eta'],1)
        self.assertLess(d['personal_safety_margin'],0)
        self.assertGreaterEqual(policy.priority_score('P',exposure=exposure),C['personal_safety']['critical_dose_priority'])

    def test_high_dose_precedes_low_dose_same_location(self):
        r,p,policy,risk,h=configured();risk.smoke[10,12]=.1
        low=Exposure(dose=0);high=Exposure(dose=2.7)
        policy.inspect(p,r,1,exposure=low);a=policy.priority_score('P',exposure=low)
        policy.inspect(p,r,1,exposure=high);b=policy.priority_score('P',exposure=high)
        self.assertGreater(b,a)

    def test_personal_hazard_uses_lower_toxic_eta(self):
        self.assertEqual(personal_hazard_eta(50,3),3)

    def test_dose_eta_uses_remaining_budget_not_full_budget(self):
        c=C['personal_safety'];eta=toxic_dose_eta(Exposure(dose=2.5),.05,0,c)
        self.assertAlmostEqual(eta,5)

    def test_clean_air_without_predicted_dose_is_infinite(self):
        self.assertTrue(math.isinf(toxic_dose_eta(Exposure(),0,0,C['personal_safety'])))

    def test_prediction_does_not_change_accumulated_dose(self):
        e=Exposure(dose=1);eta=toxic_dose_eta(e,0,.8,C['personal_safety'])
        self.assertTrue(math.isfinite(eta));self.assertEqual(e.dose,1)

    def test_incapacitated_has_zero_remaining_eta(self):
        self.assertEqual(toxic_dose_eta(Exposure(level='incapacitada'),0,0,C['personal_safety']),0)

    def test_urgent_resident_really_leaves_instead_of_only_getting_priority(self):
        home=MeetingArea('HOME','test','left',(12,10,1,1),((12,10),))
        safe=MeetingArea('W','test','left',(1,8,3,5),tuple((x,y) for x in range(1,4) for y in range(8,13)))
        r,p,policy,risk,h=configured(areas=[home,safe]);advance(r,policy,risk)
        self.assertTrue(r.at_meeting(p))
        r.exposures['P']=Exposure(dose=2.7,level='ralentizada');risk.smoke[10,12]=.1
        h.eta[10,12]=7;policy.inspect(p,r,2,exposure=r.exposures['P'])
        r.advance(risk.smoke,set(),set(),{'P':policy.priority_score('P',exposure=r.exposures['P'])},{'P'},2)
        self.assertGreater(r.hard_invalidations['toxic_dose'],0)
        self.assertNotEqual(p.position,(12,10))

    def test_urgent_person_already_escaping_keeps_safe_route(self):
        r,p,policy,risk,h=configured();advance(r,policy,risk)
        r.exposures['P']=Exposure(dose=2.7);risk.smoke[p.y,p.x]=.1
        policy.inspect(p,r,2,exposure=r.exposures['P'])
        reason=policy.replan_reason(p,r,r.follower.route_snapshot('P'),2)
        self.assertIsNone(reason)


class SchedulingAndStabilityTests(unittest.TestCase):
    def test_small_route_improvement_is_rejected(self):
        self.assertFalse(improves_route(10,9.8,100,98,C['route_stability']))

    def test_clear_risk_improvement_is_accepted(self):
        self.assertTrue(improves_route(10,6,100,110,C['route_stability']))

    def test_cost_improvement_cannot_allow_risk_increase(self):
        self.assertFalse(improves_route(10,12,100,40,C['route_stability']))

    def test_small_field_changes_keep_actual_route(self):
        r,p,policy,risk,h=configured();advance(r,policy,risk)
        initial=r.routes_calculated
        for turn in range(2,8):
            risk.costs[5,5]+=0.01;advance(r,policy,risk,turn)
        self.assertEqual(r.routes_calculated,initial)

    def test_strong_avoid_for_resident_overrides_soft_cooldown(self):
        home=MeetingArea('HOME','test','left',(12,10,1,1),((12,10),))
        safe=MeetingArea('W','test','left',(1,8,3,5),tuple((x,y) for x in range(1,4) for y in range(8,13)))
        r,p,policy,risk,h=configured(areas=[home,safe]);advance(r,policy,risk)
        risk.predicted_smoke[10,12]=.7;policy.last_checked['P']=1
        advance(r,policy,risk,2)
        self.assertEqual(r.area_policy.states['HOME'],'AVOID')
        self.assertNotEqual(p.position,(12,10))

    def test_soft_proposal_rollback_restores_assignment_load_and_counters(self):
        r,p,policy,risk,h=configured();advance(r,policy,risk)
        assignment=r.assignments['P'];routes=r.routes_calculated;replans=r.replanned_routes
        loads=r.area_load.copy();changes=len(r.destination_changes)
        r.last_planned['P']=0;policy.last_checked['P']=0
        r.follower._routes['P']['status']='esperando_ocupacion'
        policy.last_positions['P']=p.position;policy.waiting_age['P']=20
        advance(r,policy,risk,40)
        self.assertEqual(r.assignments['P'],assignment)
        self.assertEqual(r.routes_calculated,routes);self.assertEqual(r.replanned_routes,replans)
        self.assertEqual(r.area_load,loads);self.assertEqual(len(r.destination_changes),changes)
        self.assertEqual(sum(r.arrival_flow.values()),0)
        self.assertFalse(r.replan_diagnostics[-1]['accepted'])

    def test_imminent_fire_invalidates_without_cooldown(self):
        r,p,policy,risk,h=configured();advance(r,policy,risk)
        old=r.routes_calculated;status=r.follower.route_snapshot('P')
        cell=r.paths['P'][status['steps_done']+2];h.fire_eta[cell[1],cell[0]]=0
        advance(r,policy,risk,2)
        self.assertGreater(r.hard_invalidations['current_danger']+r.hard_invalidations['imminent_fire'],0)
        self.assertTrue(r.routes_calculated>old or 'P' not in r.assignments)

    def test_continuous_critical_flow_does_not_starve_old_request(self):
        r,p,policy,risk,h=configured(budget=2)
        r.pending_since['P']=0
        for turn in range(1,60):
            newcomers=[Person('Z'+str(turn)+'a',1,1),Person('Z'+str(turn)+'b',2,1)]
            for q in newcomers:r.pending_since[q.person_id]=turn
            ordered=scheduling_order(r,[p]+newcomers,{p.person_id:0,**{q.person_id:10000 for q in newcomers}},turn)
            if p in ordered[:2]:break
        self.assertLessEqual(turn,C['route_scheduling']['fairness_wait_turns'])

    def test_dose_priority_affects_real_planning_queue(self):
        r,p,policy,risk,h=configured(budget=1,position=(2,2))
        q=Person('ZZZ',12,10);r.manager.add_person(q)
        r.exposures={'P':Exposure(),'ZZZ':Exposure(dose=2.7)};risk.smoke[10,12]=.1
        for person in r.manager.list_people():policy.inspect(person,r,1,exposure=r.exposures[person.person_id])
        priorities={pid:policy.priority_score(pid,exposure=e) for pid,e in r.exposures.items()}
        r.advance(risk.smoke,set(),set(),priorities,{'P','ZZZ'},1)
        self.assertEqual(r.last_planning_order[0],'ZZZ')

    def test_incapacitated_reason(self):
        r,p,policy,risk,h=configured();r.exposures={'P':Exposure(level='incapacitada')}
        advance(r,policy,risk);self.assertEqual(r.person_reasons['P'],'INCAPACITATED')

    def test_budget_reason(self):
        r,p,policy,risk,h=configured(budget=1);r.manager.add_person(Person('Q',12,11))
        advance(r,policy,risk)
        self.assertIn('ROUTE_BUDGET_EXHAUSTED',r.person_reasons.values())

    def test_retry_reason(self):
        r,p,policy,risk,h=configured();r.next_attempt['P']=8;advance(r,policy,risk)
        self.assertEqual(r.person_reasons['P'],'RETRY_COOLDOWN')

    def test_no_safe_meeting_reason(self):
        area=MeetingArea('OFF','test','left',(1,1,1,1),((1,1),),enabled=False)
        r,p,policy,risk,h=configured(areas=[area]);advance(r,policy,risk)
        self.assertEqual(r.person_reasons['P'],'NO_SAFE_MEETING_AREA')

    def test_full_meeting_reason(self):
        area=MeetingArea('FULL','test','left',(1,1,1,1),((1,1),))
        r,p,policy,risk,h=configured(areas=[area]);r.reserved[(1,1)]='other';advance(r,policy,risk)
        self.assertEqual(r.person_reasons['P'],'WAITING_FOR_CAPACITY')

    def test_disconnected_reason(self):
        r,p,policy,risk,h=configured();r.graph.cache_static_topology()
        wall={(8,y) for y in range(21)}|{(18,y) for y in range(21)}
        advance(r,policy,risk,blocked=wall)
        self.assertEqual(r.person_reasons['P'],'NO_REACHABLE_PATH')

    def test_congestion_blocked_reason(self):
        area=MeetingArea('E','test','right',(24,10,1,1),((24,10),))
        r,p,policy,risk,h=configured(areas=[area]);r.graph.cache_static_topology()
        # A wall of incapacitated people blocks a physically connected graph.
        for y in range(21):
            pid='BLOCK'+str(y);r.manager.add_person(Person(pid,18,y))
            r.exposures[pid]=Exposure(level='incapacitada')
        advance(r,policy,risk)
        self.assertEqual(r.person_reasons['P'],'CONGESTION_BLOCKED')

    def test_no_safe_route_reason(self):
        r,p,policy,risk,h=configured()
        # All routes must cross the temporal hazard wall, with no local gain.
        h.eta[:,7:10]=0;h.eta[:,16:19]=0;risk.costs.fill(0)
        advance(r,policy,risk)
        self.assertEqual(r.person_reasons['P'],'NO_SAFE_ROUTE')

    def test_escape_records_measurable_progress_and_history(self):
        area=MeetingArea('OFF','test','left',(1,1,1,1),((1,1),),enabled=False)
        r,p,policy,risk,h=configured(areas=[area]);h.eta[:,10:16]=10;risk.costs[:,10:16]=30
        advance(r,policy,risk)
        self.assertIn('P',r.temporary)
        self.assertEqual(r.person_reasons['P'],'INTERMEDIATE_GOAL_PENDING')
        e=policy.escape_progress[-1]
        self.assertLess(e['risk_after_escape'],e['risk_before_escape'])
        self.assertGreaterEqual(len(policy.intermediate_history['P']),1)

    def test_recent_intermediate_goal_is_not_reused(self):
        r,p,policy,risk,h=configured();h.eta[:,10:16]=10;risk.costs[:,10:16]=30
        first=policy.temporary_escape(p,r.graph,set(),set(),r.congestion)
        self.assertIsNotNone(first);policy.record_escape(p,first.goal,1)
        second=policy.temporary_escape(p,r.graph,set(),set(),r.congestion)
        self.assertTrue(second is None or first.goal!=second.goal)

    def test_escape_prefers_upwind_and_direction_changes_choice(self):
        r,p,policy,risk,h=configured();h.eta[:,10:16]=10;risk.costs[:,10:16]=30
        policy.predicted_vector=(1.,0.)
        west=policy.temporary_escape(p,r.graph,set(),set(),r.congestion)
        policy.predicted_vector=(-1.,0.)
        east=policy.temporary_escape(p,r.graph,set(),set(),r.congestion)
        self.assertLess(west.goal[0],p.x);self.assertGreater(east.goal[0],p.x)

    def test_reason_vocabulary_is_explicit(self):
        self.assertEqual(len(UNASSIGNED_REASONS),9)
        self.assertIn('CONGESTION_BLOCKED',UNASSIGNED_REASONS)


class SharedGuideTests(unittest.TestCase):
    def test_disabled_guide_uses_existing_astar_fallback(self):
        r,p,policy,risk,h=configured();r.graph.cache_static_topology()
        r.flow=MeetingFlowField(r.graph);r.flow.maximum_fields=0
        advance(r,policy,risk)
        self.assertIn('P',r.assignments);self.assertGreater(r.total_astar_searches,0)
    def test_cache_same_snapshot_same_path(self):
        r,p,_,_,_=configured();r.graph.cache_static_topology();flow=MeetingFlowField(r.graph)
        costs=np.zeros((21,31));area=r.areas['W']
        flow.prepare(costs,set());a=flow.route(p.position,'W',area.cells,area.cells,set())
        flow.prepare(costs,set());b=flow.route(p.position,'W',area.cells,area.cells,set())
        self.assertEqual(a,b);self.assertEqual(flow.hits,1);self.assertEqual(flow.misses,1)
        fresh=MeetingFlowField(r.graph);fresh.prepare(costs,set())
        self.assertEqual(a,fresh.route(p.position,'W',area.cells,area.cells,set()))
        fresh.cache_enabled=False
        self.assertEqual(a,fresh.route(p.position,'W',area.cells,area.cells,set()))

    def test_changed_blocked_signature_invalidates_and_avoids_new_block(self):
        r,p,_,_,_=configured();r.graph.cache_static_topology();flow=MeetingFlowField(r.graph)
        costs=np.zeros((21,31));area=r.areas['W'];flow.prepare(costs,set())
        a=flow.route(p.position,'W',area.cells,area.cells,set());block=a[2]
        flow.prepare(costs,{block});b=flow.route(p.position,'W',area.cells,area.cells,set())
        self.assertNotIn(block,b);self.assertEqual(flow.misses,2)

    def test_changed_risk_signature_recalculates(self):
        r,_,_,_,_=configured();r.graph.cache_static_topology();flow=MeetingFlowField(r.graph)
        costs=np.zeros((21,31));flow.prepare(costs,set());signature=flow.signature
        costs[10,10]=.001;flow.prepare(costs,set())
        self.assertNotEqual(flow.signature,signature);self.assertEqual(flow.rebuilds,2)

    def test_shared_guide_does_not_share_occupancy(self):
        r,p,policy,risk,h=configured();r.manager.add_person(Person('Q',12,11))
        r.graph.cache_static_topology();r.flow=MeetingFlowField(r.graph)
        for turn in range(1,15):
            advance(r,policy,risk,turn)
            self.assertEqual(len({q.position for q in r.manager.list_people()}),2)
        self.assertNotEqual(r.assignments['P'][1],r.assignments['Q'][1])

    def test_entry_capacity_and_load_are_reported(self):
        r,p,policy,risk,h=configured();advance(r,policy,risk)
        info=r.summary()['areas']['W']
        self.assertGreater(info['meeting_entry_capacity'],0)
        self.assertIn('assigned_in_transit',info);self.assertIn('predicted_arrival_rate',info)

    def test_physical_occupancy_counts_unassigned_passers(self):
        from routing.safe_routing import refresh_meeting_load
        r,p,policy,risk,h=configured();r.manager.add_person(Person('PASSER',2,9))
        refresh_meeting_load(r,r.manager.list_people())
        self.assertEqual(r.meeting_load['W']['current_occupancy'],1)
        self.assertEqual(r.meeting_load['W']['remaining_capacity'],len(r.areas['W'].cells)-1)


class IntegrationTests(unittest.TestCase):
    def test_report_json_is_strict_and_preserves_metrics(self):
        data=json.loads(report_json(dict(fire_contacts=2,SafetyScore=99.5,eta=math.inf,margin=-math.inf)),
            parse_constant=lambda value:(_ for _ in ()).throw(AssertionError('Nonstandard JSON '+value)))
        self.assertEqual(data['fire_contacts'],2);self.assertEqual(data['SafetyScore'],99.5)
        self.assertEqual(data['eta'],'Infinity');self.assertEqual(data['margin'],'-Infinity')
    def test_traditional_never_calls_changed_intelligent_replan_function(self):
        r,p,policy,risk,h=configured(mode='traditional')
        with patch('routing.intelligent_policy.IntelligentEvacuationPolicy.replan_reason',side_effect=AssertionError('Control called intelligent replan')):
            for turn in range(1,8):advance(r,policy,risk,turn)
        self.assertIn('P',r.assignments)
    def test_post_alarm_click_selects_person_and_debug_renders_in_real_pygame(self):
        import os
        os.environ.setdefault('SDL_VIDEODRIVER','dummy');os.environ.setdefault('SDL_AUDIODRIVER','dummy')
        import pygame
        from dcc_app.functional_application import FunctionalDisasterApp,TURTLE_MESSAGE
        from dcc_app.model import load_campus
        from dcc_app.presentation import rect_map
        assets=ROOT/'data/functional'
        app=FunctionalDisasterApp(load_campus(assets/'campus.json',assets/'building_entrances.json'),ROOT,mode='optimizado')
        app.scene.start();app.scene.center.toggle_pause()
        rect=rect_map(1320,830);app.camera.fit(rect)
        person=app.scene.people[0];pixel=app.camera.project(person.x+.5,person.y+.5)
        old=set(app.scene.environment.fire.burning)
        self.assertFalse(app.handle_map_click(pixel,rect))
        self.assertEqual(app.selected_person[1],person.person_id)
        app.toggle_debug();self.assertTrue(app.debug_risk)
        app.run(smoke_test=True)
        self.assertEqual(set(app.scene.environment.fire.burning),old)
        self.assertEqual(TURTLE_MESSAGE,'Ninguna tortuga saldrá lastimada durante esta simulación.')

    def test_score_same_formula_bounded_and_keeps_raw_metrics(self):
        metrics={k:0 for k in C['safety_score']['weights']}
        self.assertEqual(safety_score(metrics,100,100,C['safety_score']),100)
        metrics['fire_contacts']=100
        self.assertEqual(safety_score(metrics,100,100,C['safety_score']),70)
        self.assertEqual(metrics['fire_contacts'],100)

    def test_sixteen_categories_include_directed_cases(self):
        cases=benchmark_scenarios(turns=2)
        self.assertEqual(len(cases),16)
        self.assertTrue({'laboratory','vegetation','meeting_downwind','abrupt_wind','two_meetings',
            'blocked_primary_exit','persistent_smoke'}<={c['category'] for c in cases})
        self.assertTrue({'E15','E16'}<={c['building'] for c in cases})

    def test_blocked_primary_scenario_covers_all_fine_door_pairs(self):
        case=next(c for c in benchmark_scenarios(turns=2) if c['category']=='blocked_primary_exit')
        self.assertEqual(len([case['ignition']]+case['extra_ignitions']),3)
        self.assertEqual(len({tuple(p) for p in [case['ignition']]+case['extra_ignitions']}),3)
        accesses=json.loads((ROOT/'data/functional/building_entrances.json').read_text())['accesses']
        self.assertTrue(any(a['building']==case['building'] and a.get('role')=='secondary' for a in accesses))

    def test_physics_population_and_one_cell_per_turn_preserved(self):
        modes=[FunctionalSimulation(ROOT,mode='optimizado',evacuation_mode=mode,seed=156) for mode in ('traditional','intelligent')]
        for s in modes:s.start_alarm()
        for _ in range(5):
            for s in modes:
                old={p.person_id:p.position for p in s.people};s.step()
                self.assertEqual(len({p.position for p in s.people}),1879)
                self.assertTrue(all(abs(p.x-old[p.person_id][0])+abs(p.y-old[p.person_id][1])<=1 for p in s.people))
            self.assertEqual(physical_digest(modes[0]),physical_digest(modes[1]))


if __name__=='__main__':unittest.main(verbosity=2)
