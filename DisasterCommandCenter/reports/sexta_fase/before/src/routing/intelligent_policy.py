"""Decisiones de evacuacion; el gateway existente sigue siendo quien mueve."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RouteSafety:
    state: str
    minimum_margin: float
    arrival_eta: float


@dataclass(frozen=True)
class SafeIntermediateGoal:
    goal: tuple[int, int]
    path: tuple[tuple[int, int], ...]


class IntelligentEvacuationPolicy:
    def __init__(self, risk, hazard, config, route_config, assignment_config):
        self.risk, self.hazard = risk, hazard
        self.config, self.route_config, self.assignment_config = config, route_config, assignment_config
        self.waiting_age = {}
        self.last_positions = {}
        self.states = {}
        self.diagnostics = {}
        self.events = deque(maxlen=6)
        self._event_turns = {}
        self.temporal_rejections = 0
        self.intermediate_goals = 0
        self.avoided_destinations = 0
        self.costs = risk.costs+hazard.urgency_cost
        self._exit_distance = {}

    def risk_cost(self, x, y):
        return float(self.costs[y, x])

    def refresh_costs(self):
        self.costs = self.risk.costs+self.hazard.urgency_cost

    @staticmethod
    def movement_factor(exposure):
        return 2. if exposure is not None and exposure.level == 'ralentizada' else 1.

    def evacuation_eta(self, person, router, controller=None, exposure=None):
        factor = self.movement_factor(exposure)
        pid = person.person_id
        if person.building_id is not None and controller is not None:
            # Unweighted distance is in steps; the risk-weighted potential is NOT time.
            indoor, outside = controller.exit_time(person)
            if outside not in self._exit_distance:
                self._exit_distance[outside] = min((max(a.bounds[0]-outside[0], 0, outside[0]-(a.bounds[0]+a.bounds[2]-1))+
                    max(a.bounds[1]-outside[1], 0, outside[1]-(a.bounds[1]+a.bounds[3]-1))
                    for a in router.areas.values() if a.enabled), default=0)
            exterior = self._exit_distance[outside]
            return (indoor+exterior)*factor+self.config['door_queue_turns']
        status = router.follower.route_snapshot(pid)
        if status and pid in router.paths:
            steps = max(0, len(router.paths[pid])-1-status['steps_done'])
        else:
            steps = min((max(a.bounds[0]-person.x, 0, person.x-(a.bounds[0]+a.bounds[2]-1))+
                         max(a.bounds[1]-person.y, 0, person.y-(a.bounds[1]+a.bounds[3]-1))
                         for a in router.areas.values() if a.enabled and router.safe.get(a.area_id, False)),
                        default=self.config['escape_radius'])
        congestion = min(self.config['maximum_congestion_delay'],
                         router.congestion.get_congestion(person.x, person.y)*self.config['congestion_delay_per_unit'])
        return steps*factor+congestion

    def inspect(self, person, router, turn, *, controller=None, exposure=None):
        pid = person.person_id
        hazard_eta = self.hazard.time_to_hazard(*person.position)
        evacuation_eta = self.evacuation_eta(person, router, controller, exposure)
        margin = hazard_eta-evacuation_eta
        unsafe = math.isfinite(hazard_eta) and margin <= self.config['unsafe_wait_margin_turns']
        previous = self.last_positions.get(pid)
        waiting = previous == person.position
        self.waiting_age[pid] = self.waiting_age.get(pid, 0)+1 if waiting else 0
        self.last_positions[pid] = person.position
        at_meeting = router.at_meeting(person)
        state = ('INCAPACITATED' if exposure is not None and exposure.level == 'incapacitada' else
                 'WAITING_UNSAFE' if waiting and unsafe else
                 'AT_MEETING_AREA' if at_meeting and not unsafe else
                 'WAITING_SAFE' if waiting else 'EVACUATING')
        self.states[pid] = state
        data = dict(hazard_eta=hazard_eta, evacuation_eta=evacuation_eta, safety_margin=margin,
                    unsafe_wait=unsafe, waiting_age=self.waiting_age[pid], state=state)
        self.diagnostics[pid] = data
        return data

    def priority_score(self, pid, laboratory_priority=0, exposure=None):
        d = self.diagnostics[pid]
        c = self.config
        urgency = c['critical_priority'] if d['safety_margin'] <= 0 else c['urgent_priority'] if d['unsafe_wait'] else 0
        current = c['current_danger_priority'] if d['hazard_eta'] == 0 else 0
        age = c['starvation_weight']*d['waiting_age']  # Unbounded aging; no permanent ID starvation.
        return urgency+current+laboratory_priority+age+(exposure.dose*c['exposure_weight'] if exposure else 0)

    def destination_margin(self, area, travel_eta):
        xs, ys = zip(*area.cells)
        eta = float(self.hazard.eta[ys, xs].min())
        return eta-travel_eta-self.meeting_buffer

    @property
    def meeting_buffer(self):
        return self.config['safety_buffer_turns']+self.config['minimum_meeting_stay_turns']

    def validate_route(self, path, *, exposure=None, congestion=None):
        if not path:
            return RouteSafety('UNSAFE', -math.inf, math.inf)
        c = self.route_config
        factor = self.movement_factor(exposure)
        indices = sorted({*range(1, len(path), c['sample_stride']), len(path)-1})
        minimum = math.inf
        delay = 0.
        initial_eta = self.hazard.time_to_hazard(*path[0])
        for i in indices:
            x, y = path[i]
            if congestion is not None:
                delay = min(c['maximum_delay_turns'], delay+congestion.get_congestion(x, y)*c['delay_per_sample'])
            arrival = i*factor+delay
            hazard = self.hazard.time_to_hazard(x, y)
            margin = hazard-arrival
            # Escape from a threatened origin may cross a short improving prefix.
            if i <= c['escape_grace_steps'] and hazard > initial_eta and margin < 0:
                continue
            minimum = min(minimum, margin)
        state = ('UNSAFE' if minimum < c['unsafe_margin_turns'] else
                 'MARGINAL' if minimum < c['marginal_margin_turns'] else 'SAFE')
        return RouteSafety(state, minimum, (len(path)-1)*factor+delay)

    def temporary_escape(self, person, graph, blocked, occupied, congestion):
        """Bounded local decision, not a second A*: same graph, gateway moves.

        BFS only discovers reachable intermediate candidates and reconstructs
        their cardinal prefix. It never searches for a second campus route.
        """
        c = self.config
        start = person.position
        queue = deque([start]); parents = {start: None}; depths = {start: 0}
        base_eta = self.hazard.time_to_hazard(*start)
        base_risk = self.risk_cost(*start)
        candidates = []
        while queue and len(parents) <= c['escape_max_visited']:
            point = queue.popleft(); depth = depths[point]
            if point != start and point not in occupied:
                eta = self.hazard.time_to_hazard(*point)
                gain = min(eta, c['horizon_turns'])-min(base_eta, c['horizon_turns'])
                score = gain*c['escape_eta_weight']+base_risk-self.risk_cost(*point)-congestion.get_cost(*point)
                if score >= c['escape_minimum_improvement'] and eta > depth:
                    candidates.append((-score, depth, point))
            if depth >= c['escape_radius']:
                continue
            for neighbor in graph.get_neighbors(*point):
                if neighbor in parents or neighbor in blocked or neighbor in occupied:
                    continue
                parents[neighbor] = point; depths[neighbor] = depth+1; queue.append(neighbor)
        if not candidates:
            return None
        goal = min(candidates)[2]
        path = [goal]
        while parents[path[-1]] is not None:
            path.append(parents[path[-1]])
        path.reverse()
        if self.validate_route(path).state == 'UNSAFE':
            return None
        return SafeIntermediateGoal(goal, tuple(path))

    def emit(self, turn, kind, message):
        if turn-self._event_turns.get(kind, -10**9) < self.config['event_cooldown_turns']:
            return
        self.events.append(dict(turn=turn, kind=kind, message=message))
        self._event_turns[kind] = turn

    def replan_reason(self, person, router, status, turn):
        """Emergency overrides stability; safe destinations remain sticky."""
        pid = person.person_id
        assignment = router.assignments.get(pid)
        if assignment is None or pid in router.temporary:
            return None
        key, _ = assignment
        path = router.paths[pid][status['steps_done']:] if status else []
        factor = self.movement_factor(router.exposures.get(pid))
        eta = max(0, len(path)-1)*factor
        destination_margin = router.area_eta[key]-eta-self.meeting_buffer
        cooldown = turn-router.last_planned.get(pid, turn) >= self.risk.config['replan_cooldown']
        if destination_margin <= 0:
            return 'future_destination'
        if router._preventive_change(person, assignment, turn):
            return 'predicted_destination'
        if path and (cooldown or self.risk.wind_changed):
            check = self.validate_route(path, exposure=router.exposures.get(pid), congestion=router.congestion)
            if check.state == 'UNSAFE':
                return 'temporal_route'
        return None
