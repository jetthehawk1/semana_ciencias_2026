"""Decisiones de evacuacion; el gateway existente sigue siendo quien mueve."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import numpy as np
from simulation.personal_safety import toxic_dose_eta, personal_hazard_eta


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
        self.fire_safety = self.personal_config = self.escape_config = self.stability_config = None
        self.intermediate_history = {}
        self.escape_progress = []
        self.last_checked = {}
        self.watchdog_stops = 0
        self.routes_conserved = 0

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
        environmental_eta = hazard_eta
        dose_eta = math.inf
        if self.personal_config is not None:
            x, y = person.position
            dose_eta = toxic_dose_eta(exposure, self.risk.smoke[y, x], self.risk.predicted_smoke[y, x],
                                      self.personal_config, dose_limit=self.personal_config['dose_limit'])
            hazard_eta = personal_hazard_eta(hazard_eta, dose_eta)
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
                    environmental_hazard_eta=environmental_eta, personal_hazard_eta=hazard_eta,
                    toxic_dose_eta=dose_eta, fire_eta=self.hazard.time_to_fire(*person.position),
                    smoke_eta=self.hazard.time_to_smoke(*person.position),
                    personal_safety_margin=margin, unsafe_wait=unsafe, waiting_age=self.waiting_age[pid], state=state)
        self.diagnostics[pid] = data
        return data

    def priority_score(self, pid, laboratory_priority=0, exposure=None):
        d = self.diagnostics[pid]
        c = self.config
        urgency = c['critical_priority'] if d['safety_margin'] <= 0 else c['urgent_priority'] if d['unsafe_wait'] else 0
        current = c['current_danger_priority'] if d['hazard_eta'] == 0 else 0
        if self.fire_safety is not None and d['fire_eta'] <= self.fire_safety['imminent_margin_turns']:
            current += self.fire_safety['imminent_priority']
        age = c['starvation_weight']*d['waiting_age']  # Unbounded aging; no permanent ID starvation.
        dose_priority = 0
        if self.personal_config is not None:
            pc = self.personal_config
            dose_priority = (pc['critical_dose_priority'] if d['toxic_dose_eta'] <= pc['critical_dose_eta'] else
                             pc['urgent_dose_priority'] if d['toxic_dose_eta'] <= pc['urgent_dose_eta'] else 0)
            if dose_priority:
                self.emit(self.hazard.turn, 'dose', 'PRIORIDAD CRITICA: DOSIS DE HUMO')
        score = urgency+current+dose_priority+laboratory_priority+age+(exposure.dose*c['exposure_weight'] if exposure else 0)
        d['priority'] = score
        return score

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
        if self.fire_safety is not None:
            fire_margin = self.minimum_fire_margin(path, factor)
            if fire_margin <= self.fire_safety['route_margin_turns']:
                self.emit(self.hazard.turn, 'fire_rejection', 'RUTA RECHAZADA: FUEGO LLEGARIA ANTES')
                return RouteSafety('UNSAFE', fire_margin, (len(path)-1)*factor)
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

    def minimum_fire_margin(self, path, factor=1.):
        """Every future point, including between smoke samples; no fire grace."""
        if len(path) < 2:
            return math.inf
        points = np.asarray(path[1:], dtype=np.int32)
        etas = self.hazard.fire_eta[points[:, 1], points[:, 0]]
        arrival = np.arange(1, len(path))*factor
        return float(np.min(etas-arrival-self.route_config['maximum_delay_turns']))

    def step_safe(self, person, target, exposure=None):
        if self.fire_safety is None:
            return True
        x, y = target
        c = self.fire_safety
        fire_eta = self.hazard.time_to_fire(x, y)
        return (self.risk.fire_distance[y, x] != 0 and
                fire_eta-self.movement_factor(exposure) > c['imminent_margin_turns'] and
                self.risk.smoke[y, x] < c['watchdog_smoke_threshold'] and
                self.risk.predicted_smoke[y, x] < c['watchdog_predicted_threshold'])

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
        extra = self.escape_config
        recent = self.intermediate_history.get(person.person_id, ())
        wind_vector = getattr(self, 'predicted_vector', (0., 0.))
        while queue and len(parents) <= c['escape_max_visited']:
            point = queue.popleft(); depth = depths[point]
            if point != start and point not in occupied:
                eta = self.hazard.time_to_hazard(*point)
                gain = min(eta, c['horizon_turns'])-min(base_eta, c['horizon_turns'])
                score = gain*c['escape_eta_weight']+base_risk-self.risk_cost(*point)-congestion.get_cost(*point)
                if extra is not None:
                    if depth < extra['minimum_distance'] or any(
                        point == old['goal'] and self.hazard.turn-old['turn'] < extra['recent_goal_turns'] for old in recent):
                        score = -math.inf
                    exits = sum(q not in blocked and q not in occupied for q in graph.get_neighbors(*point))
                    # Two-hop branchiness penalizes cul-de-sacs without a new
                    # global geometry search for each person.
                    branches = sum(len(graph.get_neighbors(*q)) >= 3 for q in graph.get_neighbors(*point) if q not in blocked)
                    upwind = -((point[0]-start[0])*wind_vector[0]+(point[1]-start[1])*wind_vector[1])/max(1, depth)
                    score += extra['connectivity_weight']*(exits-2+branches/4)+extra['upwind_weight']*upwind
                    score -= extra['predicted_smoke_weight']*self.risk.predicted_smoke[point[1], point[0]]
                    improved = gain >= extra['minimum_eta_gain'] or base_risk-self.risk_cost(*point) >= extra['minimum_risk_gain']
                    if not improved or exits < 2:
                        score = -math.inf
                if score >= c['escape_minimum_improvement'] and eta > depth:
                    candidates.append((-score, depth, point))
            if depth >= c['escape_radius']:
                continue
            for neighbor in graph.get_neighbors(*point):
                if neighbor in parents or neighbor in blocked or neighbor in occupied:
                    continue
                if self.fire_safety is not None and not self.step_safe(person, neighbor):
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

    def record_escape(self, person, goal, turn):
        start = person.position
        history = self.intermediate_history.setdefault(person.person_id, deque(maxlen=self.escape_config['history_length']))
        history.append(dict(goal=goal, turn=turn))
        self.escape_progress.append(dict(person_id=person.person_id, turn=turn, start=start, goal=goal,
            kind='ETA_ESCAPE' if self.hazard.time_to_hazard(*goal)>self.hazard.time_to_hazard(*start) else 'LOWER_RISK_REFUGE',
            risk_before_escape=self.risk_cost(*start), risk_after_escape=self.risk_cost(*goal),
            hazard_eta_before=self.hazard.time_to_hazard(*start), hazard_eta_after=self.hazard.time_to_hazard(*goal)))

    def emit(self, turn, kind, message):
        if turn-self._event_turns.get(kind, -10**9) < self.config['event_cooldown_turns']:
            return
        self.events.append(dict(turn=turn, kind=kind, message=message))
        self._event_turns[kind] = turn

    def replan_reason(self, person, router, status, turn):
        """Emergency overrides stability; safe destinations remain sticky."""
        pid = person.person_id
        assignment = router.assignments.get(pid)
        if assignment is None:
            return None
        key, _ = assignment
        path = router.paths[pid][status['steps_done']:] if status else []
        factor = self.movement_factor(router.exposures.get(pid))
        if self.fire_safety is not None and self.minimum_fire_margin(path, factor) <= self.fire_safety['route_margin_turns']:
            return 'imminent_fire'
        if self.stability_config is not None:
            sc = self.stability_config
            elapsed = turn-self.last_checked.get(pid, self.last_checked.setdefault(pid, turn))
            if elapsed < sc['soft_cooldown_turns'] and not self.risk.wind_changed:
                self.routes_conserved += 1
                return None
            self.last_checked[pid] = turn
            check = self.validate_route(path, exposure=router.exposures.get(pid), congestion=router.congestion)
            d = self.diagnostics.get(pid, {})
            d['route_stability_score'] = max(0., min(1., check.minimum_margin/self.route_config['marginal_margin_turns']))
            if check.state == 'UNSAFE' and check.minimum_margin < -sc['soft_margin_hysteresis']:
                return 'temporal_route'
            if pid in router.temporary:
                return None
            if self.hazard.time_to_hazard(*person.position) == 0 or self._destination_unsafe(router, key, path, factor):
                return 'future_destination'
            if router._preventive_change(person, assignment, turn):
                return 'predicted_destination'
            self.routes_conserved += 1
            self.emit(turn, 'stable', 'RUTA CONSERVADA: CAMBIO NO JUSTIFICA REPLAN')
            return None
        if pid in router.temporary:
            return None
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

    def _destination_unsafe(self, router, key, path, factor):
        return key in router.areas and router.area_eta[key]-max(0,len(path)-1)*factor-self.meeting_buffer <= 0
