"""Scheduling and safety hooks for the existing MeetingRouter and gateway.

No alternate movement engine: this module chooses when to invoke the same
planner, commits through the same route contract, and guards every next step.
"""
from __future__ import annotations

from collections import Counter
import math
import numpy as np


UNASSIGNED_REASONS = frozenset(('ROUTE_BUDGET_EXHAUSTED', 'RETRY_COOLDOWN',
    'NO_SAFE_MEETING_AREA', 'NO_SAFE_ROUTE', 'CONGESTION_BLOCKED',
    'INTERMEDIATE_GOAL_PENDING', 'INCAPACITATED', 'NO_REACHABLE_PATH', 'WAITING_FOR_CAPACITY'))


def route_values(router, path):
    if not path:
        return math.inf, math.inf
    cost = router._route_cost()
    risks = [cost.risk_cost(*p) if cost else 0 for p in path[1:]]
    return max(risks, default=0.), sum(1+r+router.congestion.get_cost(*p) for p,r in zip(path[1:], risks))


def improves_route(old_risk, new_risk, old_cost, new_cost, config):
    return (new_risk <= old_risk*(1-config['minimum_risk_improvement']) and new_risk < old_risk or
            new_cost <= old_cost*(1-config['minimum_route_improvement']) and new_risk <= old_risk)


def refresh_meeting_load(router, outside):
    counts, transit, rates, incoming = Counter(), Counter(), Counter(), Counter()
    for p in outside:
        actual_areas = router._areas_by_point.get(p.position, ())
        counts.update(actual_areas)
        assignment = router.assignments.get(p.person_id)
        if not assignment or assignment[0] not in router.areas:
            continue
        key, goal = assignment
        if p.position != goal:
            transit[key] += 1
            incoming[key] += int(key not in actual_areas)
            status = router.follower.route_snapshot(p.person_id)
            steps = max(1, len(router.paths[p.person_id])-1-(status['steps_done'] if status else 0))
            rates[key] += 1/steps
    for key, area in router.areas.items():
        xs, ys = router._area_indices[key]
        samples = area.cells[::max(1,len(area.cells)//24)]
        near = sum(router.congestion.get_congestion(*p) for p in samples)/max(1,len(samples))
        router.meeting_load[key] = dict(current_occupancy=counts[key], assigned_in_transit=transit[key],
            predicted_arrival_rate=rates[key], remaining_capacity=max(0,len(area.cells)-counts[key]-incoming[key]),
            congestion_near_area=near)


def scheduling_order(router, pending, priorities, turn):
    """Urgent first, with reserved aged slots even under endless critical input."""
    cfg = router.budget_config
    ranked = sorted(pending, key=lambda p: (-(priorities.get(p.person_id,0)+
        cfg['queue_age_weight']*(turn-router.pending_since[p.person_id])),
        router.pending_since[p.person_id], p.person_id))
    aged = sorted((p for p in pending if turn-router.pending_since[p.person_id] >= cfg['fairness_wait_turns']),
                  key=lambda p:(router.pending_since[p.person_id],p.person_id))
    # Fire/dose urgency retains the first slot; bounded fairness slots follow.
    fairness = aged[:cfg['fairness_reserved_slots']]
    first = ranked[:1]
    seen = {p.person_id for p in first+fairness}
    return first+[p for p in fairness if p not in first]+[p for p in ranked if p.person_id not in seen]


def advance_safe(router, concentrations, burning, blocked, priorities, eligible, turn):
    policy = router.decision_policy
    cfg = router.sixth_config
    physical = set(blocked)
    blocked = set(blocked)
    if policy:
        ys, xs = np.nonzero(policy.hazard.fire_eta <= policy.fire_safety['imminent_margin_turns'])
        blocked.update(zip(xs.tolist(), ys.tolist()))
        policy.refresh_costs()
    router.assess(concentrations, burning, blocked_cells=physical)
    people = router.manager.list_people()
    outside = [p for p in people if p.building_id is None]
    occupied = {p.position for p in people}
    router.routing_obstacles = {p.position for p in outside if router.at_meeting(p) or
        getattr(router.exposures.get(p.person_id), 'level', None) == 'incapacitada'}
    common_blocks = blocked | router.routing_obstacles
    router.congestion.update(outside)
    refresh_meeting_load(router, outside)
    router.arrival_flow.clear()
    pending, valid, soft = [], set(), {}
    for person in outside:
        pid = person.person_id
        exposure = router.exposures.get(pid)
        if getattr(exposure, 'level', None) == 'incapacitada':
            router._release(pid); router.person_reasons[pid] = 'INCAPACITATED'
            continue
        assignment = router.assignments.get(pid)
        status = router.follower.route_snapshot(pid)
        reason = None
        if assignment and status:
            path = router.paths[pid][status['steps_done']:]
            key = assignment[0]
            if pid in router.temporary and person.position == assignment[1]:
                reason = 'intermediate_reached'
            elif key in router.areas and (not router.safe[key] and
                    (not policy or router.area_policy.states[key] == 'CLOSED')):
                reason = 'meeting_closed'
            elif any(p in blocked for p in path[1:]):
                reason = 'current_danger'
            elif policy is None and any(p in router.routing_obstacles for p in path[1:]):
                reason = 'stationary_obstacle'
            elif policy and policy.minimum_fire_margin(path, policy.movement_factor(exposure)) <= policy.fire_safety['route_margin_turns']:
                reason = 'imminent_fire'
            elif policy and len(path)>1 and not policy.step_safe(person,path[1],exposure):
                reason = 'watchdog'
            if reason is None and policy:
                candidate = policy.replan_reason(person, router, status, turn)
                if candidate:
                    # A predicted temporal violation is not just a nicer path.
                    reason = candidate
            if reason is None and policy and turn-router.last_planned.get(pid,turn) >= cfg['route_stability']['soft_cooldown_turns']:
                lookahead = cfg['route_stability']['hard_lookahead_steps']
                congested = (status['status']=='esperando_ocupacion' and
                             policy.waiting_age.get(pid,0)>=router.retry_after_turns)
                stationary = any(p in router.routing_obstacles for p in path[1:lookahead+1])
                if congested or stationary:
                    soft[pid] = (assignment, list(path), 'congestion' if congested else 'stationary_obstacle')
            if reason:
                router.hard_invalidations[reason] += 1
                router._release(pid); router.next_attempt.pop(pid,None)
                router.pending_reasons[pid] = reason
                if policy and reason not in ('current_danger','meeting_closed'):
                    router.forecast_departure_candidates[pid] = dict(turn=turn,point=person.position,reason=reason)
                    router.preventive_reassignments += 1
                if reason in ('imminent_fire','watchdog'):
                    router.watchdog_events.append(dict(turn=turn,person_id=pid,point=person.position,reason=reason))
                assignment = None
        if assignment:
            valid.add(pid)
            if pid in router.temporary:
                router.person_reasons[pid] = 'INTERMEDIATE_GOAL_PENDING'
            elif pid in soft:
                router.pending_since.setdefault(pid,turn); pending.append(person)
        elif pid in eligible:
            router.pending_since.setdefault(pid,turn); pending.append(person)
        else:
            router.person_reasons.setdefault(pid,'RETRY_COOLDOWN')
    scheduling = router.budget_config
    pressured = len(pending)>=scheduling['burst_pending_threshold']
    urgent = policy and any(policy.diagnostics.get(p.person_id,{}).get('safety_margin',math.inf)<=0 for p in pending)
    normal = min(router.max_routes_per_turn,scheduling['normal_budget'])
    budget = min(scheduling['emergency_route_budget'], normal+(scheduling['critical_budget'] if urgent or pressured else 0))
    router.last_budget = budget; router.route_calls_remaining = budget; router.last_searches = 0
    # Guides use the same risk + congestion costs, built once for this snapshot.
    if router.flow is not None:
        costs = np.zeros((router.graph.height,router.graph.width),dtype=np.float64)
        if router._route_cost() is not None: costs += router._route_cost().costs
        for (x,y), value in router.congestion.congestion_map.items():
            if 0<=x<router.graph.width and 0<=y<router.graph.height:
                costs[y,x] += value*router.congestion.congestion_weight
        router.flow.prepare(costs,common_blocks)
    router.last_planning_order=[]
    escapes_left = scheduling['maximum_escapes_per_turn']
    for person in scheduling_order(router,pending,priorities,turn):
        pid=person.person_id
        if turn<router.next_attempt.get(pid,0):
            if pid not in valid: router.person_reasons[pid]='RETRY_COOLDOWN'
            continue
        if budget<=0:
            if pid not in valid: router.person_reasons[pid]='ROUTE_BUDGET_EXHAUSTED'
            continue
        budget-=1; router.last_planning_order.append(pid)
        diagnostics = policy.diagnostics.get(pid,{}) if policy else {}
        unsafe = diagnostics.get('unsafe_wait',False)
        old = soft.get(pid)
        if old:
            assignment, oldpath, why = old
            oldrisk, oldcost = route_values(router,oldpath)
            # Release reservation only while evaluating. On rejection restore
            # the VALID old route and destination; there is no unsafe gap.
            fullpath=router.paths[pid]; lastplanned=router.last_planned[pid]
            saved = {name:getattr(router,name).get(pid) for name in
                     ('last_destination','last_switch','last_planned','planned_threat')}
            changes_len=len(router.destination_changes)
            switches_before=router.replanned_routes
            arrival_flow_before=router.arrival_flow.copy()
            router._release(pid)
            before_count=router.routes_calculated
            ok=router._plan(person,blocked,occupied,turn)
            if ok:
                newpath=router.paths[pid]; newrisk,newcost=route_values(router,newpath)
                accept=improves_route(oldrisk,newrisk,oldcost,newcost,cfg['route_stability'])
                router.replan_diagnostics.append(dict(turn=turn,person_id=pid,old_route_risk=oldrisk,
                    new_route_risk=newrisk,old_route_cost=oldcost,new_route_cost=newcost,accepted=accept))
                if accept:
                    router.soft_replans+=1
                    valid.add(pid); continue
                router._release(pid)
                # Counters represent accepted routes, not speculative candidates.
                router.routes_calculated=before_count; router.replanned_routes=switches_before
            restore_route(router,person,assignment,fullpath,oldpath,turn)
            for name,value in saved.items():
                if value is None: getattr(router,name).pop(pid,None)
                else: getattr(router,name)[pid]=value
            del router.destination_changes[changes_len:]
            router.arrival_flow=arrival_flow_before
            router.last_planned[pid]=turn  # cooldown for the evaluated soft change
            if policy: policy.routes_conserved+=1
            continue
        if (policy and unsafe and escapes_left and diagnostics.get('safety_margin',math.inf)<=0 and
                policy.config['prefer_local_escape_on_negative_margin']):
            escapes_left-=1
            if router._escape(person,blocked,occupied,turn):
                valid.add(pid); continue
        if router._plan(person,blocked,occupied,turn):
            valid.add(pid); router.pending_since.pop(pid,None); router.next_attempt.pop(pid,None)
            continue
        if policy and escapes_left:
            escapes_left-=1
            if router._escape(person,blocked,occupied,turn):
                valid.add(pid); continue
        reason='ROUTE_BUDGET_EXHAUSTED' if router._plan_exhausted else router._failure_reason
        router.person_reasons[pid]=reason
        router.next_attempt[pid]=turn+(scheduling['unsafe_retry_turns'] if unsafe else router.retry_after_turns)
    router.maximum_budget_used=max(router.maximum_budget_used,len(router.last_planning_order))
    router.maximum_searches_used=max(router.maximum_searches_used,router.last_searches)

    def watchdog(person,target):
        if policy is None or policy.step_safe(person,target,router.exposures.get(person.person_id)):
            return True
        pid=person.person_id
        router._release(pid); router.next_attempt.pop(pid,None)
        router.pending_since.setdefault(pid,turn); router.pending_reasons[pid]='watchdog'
        router.person_reasons[pid]='NO_SAFE_ROUTE'
        policy.watchdog_stops+=1
        router.watchdog_events.append(dict(turn=turn,person_id=pid,point=person.position,target=target,reason='watchdog'))
        return False

    router.follower.set_blocked_cells(common_blocks)
    moved=router.follower.step(eligible_person_ids=valid&set(eligible),before_step=watchdog)
    refresh_meeting_load(router,outside)
    router.waiting=sum(p.person_id not in router.assignments for p in outside)
    router.unassigned_reasons=Counter(router.person_reasons[p.person_id] for p in outside
        if p.person_id not in router.assignments and p.person_id in router.person_reasons)
    return moved


def restore_route(router, person, assignment, fullpath, remaining, turn):
    """Restore through the public gateway contract, starting at current cell."""
    from integration.route_gateway import build_route_request
    key,goal=assignment; pid=person.person_id
    request=build_route_request(router.manager,router.map_name,
        {pid:dict(destination_id=key,goal=dict(x=goal[0],y=goal[1]))},turn=turn)
    route=dict(schema_version=request['schema_version'],map_name=router.map_name,
        width=router.manager.width,height=router.manager.height,person_id=pid,
        destination_id=key,route_id=f'kept-{turn}-{pid}',goal=dict(x=goal[0],y=goal[1]),
        path=[dict(x=x,y=y) for x,y in remaining])
    router.follower.set_request(request); router.follower.submit_route(route)
    router.assignments[pid]=assignment;router.paths[pid]=remaining;router.reserved[goal]=pid
    router.area_load[key]+=1
