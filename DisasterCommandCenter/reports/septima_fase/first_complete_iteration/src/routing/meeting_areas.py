"""Destinos de reunion, reservas y rutas; sin Pygame ni campos inventados de IA."""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from integration.route_gateway import ExternalRouteFollower, build_route_request
from routing.congestion import CongestionManager
from routing.congestion_route_adapter import calculate_congestion_route


@dataclass
class MeetingArea:
    area_id: str
    anchor_building: str
    side: str
    bounds: tuple[int, int, int, int]
    cells: tuple[tuple[int, int], ...]
    enabled: bool = True


def load_meeting_areas(config, manager, outside_doors):
    scale = config["subdivision"]
    result = []
    used = set()
    for item in config["meeting_areas"]:
        if item["anchor_building"] not in manager.building_ids or item["id"] in used:
            raise ValueError("Zona de reunion duplicada o edificio desconocido.")
        x, y, w, h = item["bounds_source"]
        if min(x, y) < 0 or min(w, h) < 1 or (x+w)*scale > manager.width or (y+h)*scale > manager.height:
            raise ValueError("Zona de reunion fuera del plano.")
        cells = tuple((xx, yy) for yy in range(y*scale, (y+h)*scale)
                      for xx in range(x*scale, (x+w)*scale)
                      if manager.is_transitable(xx, yy) and (xx, yy) not in outside_doors)
        if not cells:
            raise ValueError("Zona de reunion sin suelo transitable.")
        used.add(item["id"])
        result.append(MeetingArea(item["id"], item["anchor_building"], item["side"],
                                  (x*scale, y*scale, w*scale, h*scale), cells, item["enabled"]))
    return result


class MeetingRouter:
    """Unica autoridad de movimiento exterior: el gateway de Persona 1.

    Limita calculos por turno para repartir el coste; personas sin ruta esperan.
    La prioridad afecta realmente al orden de asignacion del presupuesto.
    """
    def __init__(self, graph, manager, map_name, areas, *, smoke_threshold=.30,
                 max_routes_per_turn=24, retry_after_turns=8, risk_field=None, area_policy=None,
                 decision_policy=None, evacuation_mode=None):
        self.graph, self.manager, self.map_name = graph, manager, map_name
        self.areas = {area.area_id: area for area in areas}
        self.follower = ExternalRouteFollower(manager, map_name)
        self.congestion = CongestionManager()
        self.smoke_threshold = smoke_threshold
        self.max_routes_per_turn = max_routes_per_turn
        self.retry_after_turns = retry_after_turns
        self.assignments = {}
        self.paths = {}
        self.reserved = {}
        self.next_attempt = {}
        self.safe = {key: area.enabled for key, area in self.areas.items()}
        self.smoke_levels = {key: 0.0 for key in self.areas}
        self.reassignments = 0
        self.routes_calculated = 0
        self.replanned_routes = 0
        self.previously_routed = set()
        self.waiting = 0
        self.last_planning_order = []
        self.risk_field, self.area_policy = risk_field, area_policy
        self.last_planned = {}
        self.planned_threat = {}
        self.last_destination = {}
        self.last_switch = {}
        self.destination_changes = []
        self.preventive_reassignments = 0
        self.predictive_route_invalidations = 0
        self.pending_reasons = {}
        self.area_load = Counter()
        self.decision_policy, self.evacuation_mode = decision_policy, evacuation_mode
        self.area_centers = {k: (a.bounds[0]+a.bounds[2]//2, a.bounds[1]+a.bounds[3]//2) for k, a in self.areas.items()}
        self.area_eta = {}
        self.temporary = set()
        self.fixed_destinations = {}
        self.unassigned_reasons = Counter()
        self.pending_since = {}
        self.arrival_flow = Counter()
        self.last_budget = max_routes_per_turn
        self.maximum_budget_used = 0
        self.temporal_invalidations = 0
        self.forecast_departure_candidates = {}
        self.exposures = {}
        self.budget_config = {}
        self._area_indices = {k: tuple(zip(*a.cells)) for k, a in self.areas.items()}
        self._component_signature = None
        self._components = None
        self.route_calls_remaining = None
        self.last_searches = 0
        self.maximum_searches_used = 0
        self.routing_obstacles = set()
        self.sixth_config = None
        self.flow = None
        self.person_reasons = {}
        self.total_astar_searches = 0
        self.hard_invalidations = Counter()
        self.soft_replans = 0
        self.replan_diagnostics = []
        self.watchdog_events = []
        self.meeting_load = {}
        self.entry_capacity = {}
        self._areas_by_point = {}
        for key, area in self.areas.items():
            region = set(area.cells)
            for point in region:
                self._areas_by_point.setdefault(point, []).append(key)
            self.entry_capacity[key] = max(1, sum(any(q not in region for q in self.graph.get_neighbors(*p))
                                               for p in area.cells))

    def _can_reach_goal(self, start, goal, blocked):
        """Exact negative precheck on the SAME static 4-neighbor graph.

        Doesn't select a route or change costs. Avoids exhaustive failed A*
        searches for every person in disconnected components. Editable graphs
        retain the previous live-query behavior.
        """
        if self.graph._static_neighbors is None:
            return True
        signature = frozenset(blocked)
        if signature != self._component_signature:
            import numpy as np
            from scipy.ndimage import label
            valid = np.array(self.graph._static_valid, dtype=bool)
            if blocked:
                xs, ys = zip(*blocked)
                valid[ys, xs] = False
            self._components = label(valid)[0]  # default cross = cardinal neighbors
            self._component_signature = signature
        sx, sy = start
        gx, gy = goal
        target = self._components[gy, gx]
        if not target:
            return False
        origin = self._components[sy, sx]
        if origin:
            return origin == target
        # The route contract permits escaping a blocked origin by removing
        # ONLY that cell from the request. Any adjacent component is reachable.
        return any(self._components[y, x] == target for x, y in self.graph.get_neighbors(sx, sy))

    def assess(self, concentrations, burning, *, blocked_cells=()):
        fire = set(burning) | set(blocked_cells)
        for key, area in self.areas.items():
            self.smoke_levels[key] = max(concentrations[y][x] for x, y in area.cells)
            self.safe[key] = (area.enabled and self.smoke_levels[key] < self.smoke_threshold
                              and not any(point in fire for point in area.cells))
        if self.area_policy is not None and self.risk_field is not None:
            states = self.area_policy.evaluate(self.areas, {k: not value for k, value in self.safe.items()},
                                               self.smoke_levels, self.risk_field, self.risk_field.turn)
            self.safe = {key: state in ("SAFE", "CAUTION") for key, state in states.items()}
        if self.decision_policy is not None:
            h = self.decision_policy.hazard
            self.area_eta = {key: float(h.eta[ys, xs].min()) for key, (xs, ys) in self._area_indices.items()}
            for key, eta in self.area_eta.items():
                self.area_policy.diagnostics[key]['estimated_hazard_arrival_turn'] = (h.turn+eta if eta != float('inf') else None)
        if self.evacuation_mode == 'traditional':
            # Current danger only; future diagnostics never govern this mode.
            self.safe = {key: area.enabled and self.smoke_levels[key] < self.smoke_threshold
                         and not any(p in fire for p in area.cells) for key, area in self.areas.items()}
        return dict(self.safe)

    def _area_score(self, person, area):
        x, y, w, h = area.bounds
        distance = max(x-person.x, 0, person.x-(x+w-1)) + max(y-person.y, 0, person.y-(y+h-1))
        if self.evacuation_mode == 'traditional':
            return (distance, area.area_id)
        if self.area_policy is None:
            return (distance, self.smoke_levels[area.area_id], area.area_id)
        config = self.area_policy.config
        risk = self.area_policy.diagnostics[area.area_id]["risk_score"]
        filled = self.area_load[area.area_id]/len(area.cells)
        extra = 0
        if self.decision_policy is not None:
            cfg = self.decision_policy.assignment_config
            eta = self.area_eta[area.area_id]
            factor = self.decision_policy.movement_factor(self.exposures.get(person.person_id))
            margin = eta-distance*factor-self.decision_policy.meeting_buffer
            extra = (cfg['predicted_arrival_weight']*max(0, cfg['preferred_margin_turns']-margin)
                     + cfg['future_capacity_weight']*filled**2
                     + cfg['arrival_flow_weight']*self.arrival_flow[area.area_id])
            if self.sixth_config is not None:
                load = self.meeting_load.get(area.area_id, {})
                entry = self.entry_capacity[area.area_id]
                extra += (cfg['entry_load_weight']*load.get('assigned_in_transit', 0)/entry
                    + cfg['arrival_rate_weight']*load.get('predicted_arrival_rate', 0)/entry
                    + cfg['near_congestion_weight']*load.get('congestion_near_area', 0))
        return (config["distance_weight"]*distance + config["destination_risk_weight"]*risk
                + config["capacity_weight"]*filled+extra, area.area_id)

    def _preventive_change(self, person, assignment, turn):
        if self.area_policy is None or assignment is None:
            return False
        key, goal = assignment
        policy = self.area_policy
        if policy.states[key] != "AVOID":
            return False
        risk = policy.diagnostics[key]["risk_score"]
        cfg = policy.config
        urgent = risk >= cfg["resident_reassign_threshold"]
        if urgent:
            return True  # Una amenaza fuerte prima sobre cooldown, incluso sin destino libre.
        if turn-self.last_switch.get(person.person_id, turn) < cfg["reassignment_cooldown"]:
            return False
        if abs(person.x-goal[0])+abs(person.y-goal[1]) <= cfg["near_goal_distance"]:
            return False
        return any(self.safe[other] and policy.diagnostics[other]["risk_score"] <= risk-cfg["minimum_risk_improvement"]
                   for other in self.areas if other != key)

    def _release(self, pid):
        previous = self.assignments.pop(pid, None)
        if previous:
            self.reserved.pop(previous[1], None)
            if previous[0] in self.areas:
                self.area_load[previous[0]] -= 1
        self.paths.pop(pid, None)
        self.temporary.discard(pid)

    def _plan(self, person, blocked, occupied, turn):
        px, py = person.position
        candidates = sorted((a for key, a in self.areas.items() if self.safe[key]),
                            key=lambda a: self._area_score(person, a))
        # Recalcular un camino no implica cambiar un destino aun seguro. Intenta
        # primero conservarlo; si ya no hay plaza/camino, prueba las alternativas.
        previous_area = self.last_destination.get(person.person_id)
        if self.evacuation_mode == 'traditional':
            fixed = self.fixed_destinations.setdefault(person.person_id,
                min(self.areas.values(), key=lambda a: self._area_score(person, a)).area_id)
            candidates = [a for a in candidates if a.area_id == fixed]
        elif self.decision_policy is not None:
            candidates = [a for a in candidates if self.area_eta[a.area_id] >
                          self._minimum_travel_eta(person, a)+self.decision_policy.meeting_buffer]
        if self.area_policy is not None and previous_area and self.safe.get(previous_area, False):
            candidates.sort(key=lambda area: area.area_id != previous_area)
        marginal = None
        attempted = 0
        self._plan_exhausted = False
        costs = self._route_cost()
        self._failure_reason = 'NO_SAFE_MEETING_AREA' if not candidates else 'NO_SAFE_ROUTE'
        cost_array = costs.costs if costs is not None else None
        for area in candidates:
            if self.decision_policy and attempted >= self.decision_policy.config['maximum_destination_attempts']:
                break
            free = [point for point in area.cells
                    if point not in self.reserved and (point not in occupied or point == person.position)
                    and point not in blocked]
            if not free:
                self._failure_reason = 'WAITING_FOR_CAPACITY'
                if self.decision_policy:
                    self.decision_policy.emit(turn,'capacity',area.area_id+' DESCARTADA: SATURACION')
                continue
            attempted += 1
            goal = min(free, key=lambda p: (abs(p[0]-px)+abs(p[1]-py)
                + (float(cost_array[p[1], p[0]]) if cost_array is not None else 0), p))
            guide = None
            if self.flow is not None:
                guide = self.flow.route(person.position, area.area_id, area.cells, free,
                    occupied-{person.position}, frontier_penalty=self.sixth_config['meeting_assignment']['frontier_penalty'])
                if guide is not None:
                    goal = guide[-1]
            # Permite salir de una celda con humo: el siguiente paso debe ser seguro.
            route_blocks = (blocked | self.routing_obstacles) - {person.position}
            request = build_route_request(self.manager, self.map_name, {
                person.person_id: {"destination_id": area.area_id,
                                   "goal": {"x": goal[0], "y": goal[1]}},
            }, turn=turn, blocked_cells=route_blocks)
            # Cache the common mask once; _can_reach_goal already handles
            # escaping a blocked origin without relabeling the whole grid.
            if not self._can_reach_goal(person.position, goal, blocked | self.routing_obstacles):
                self._failure_reason = ('CONGESTION_BLOCKED' if self.routing_obstacles and
                    self._can_reach_goal(person.position, goal, blocked) else 'NO_REACHABLE_PATH')
                continue
            route = None
            if guide is not None:
                route = dict(schema_version=request['schema_version'], map_name=self.map_name,
                    width=self.manager.width, height=self.manager.height, person_id=person.person_id,
                    destination_id=area.area_id, route_id=f'guide-{turn}-{person.person_id}',
                    goal=dict(x=goal[0], y=goal[1]), path=[dict(x=x,y=y) for x,y in guide])
                if self.decision_policy and self.decision_policy.validate_route(guide,
                        exposure=self.exposures.get(person.person_id), congestion=self.congestion).state == 'UNSAFE':
                    route = None
            if route is None and self.route_calls_remaining is not None:
                if self.route_calls_remaining <= 0:
                    self._plan_exhausted = True
                    break
                self.route_calls_remaining -= 1
                self.last_searches += 1
                self.total_astar_searches += 1
            if route is None:
                route = calculate_congestion_route(
                    self.graph, request, person.person_id, self.congestion,
                    route_id=f"meeting-{turn}-{person.person_id}-{self.routes_calculated+1}", risk_field=self._route_cost())
            if route is None:
                self._failure_reason = 'NO_REACHABLE_PATH'
                continue
            if self.decision_policy is not None:
                path = [(p['x'], p['y']) for p in route['path']]
                check = self.decision_policy.validate_route(path, exposure=self.exposures.get(person.person_id), congestion=self.congestion)
                margin = self.area_eta[area.area_id]-check.arrival_eta-self.decision_policy.meeting_buffer
                if check.state == 'UNSAFE' or margin <= 0:
                    self._failure_reason = 'NO_SAFE_ROUTE'
                    self.decision_policy.temporal_rejections += 1
                    self.decision_policy.avoided_destinations += int(margin <= 0)
                    continue
                if check.state == 'MARGINAL':
                    if marginal is None or check.minimum_margin > marginal[0]:
                        marginal = (check.minimum_margin, request, route, area.area_id, goal)
                    continue
            self._commit(person, request, route, area.area_id, goal, turn)
            return True
        if marginal is not None:
            _, request, route, key, goal = marginal
            self._commit(person, request, route, key, goal, turn)
            return True
        return False

    def _route_cost(self):
        if self.evacuation_mode == 'traditional':
            return None
        return self.decision_policy or self.risk_field

    def _minimum_travel_eta(self, person, area):
        x, y, w, h = area.bounds
        distance = max(x-person.x, 0, person.x-(x+w-1))+max(y-person.y, 0, person.y-(y+h-1))
        factor = self.decision_policy.movement_factor(self.exposures.get(person.person_id)) if self.decision_policy else 1
        return distance*factor

    def _commit(self, person, request, route, key, goal, turn, *, temporary=False):
        pid = person.person_id
        self.follower.set_request(request)
        self.follower.submit_route(route)
        self.assignments[pid] = (key, goal)
        self.reserved[goal] = pid
        if not temporary:
            self.area_load[key] += 1
            self.arrival_flow[key] += 1
        else:
            self.temporary.add(pid)
        self.paths[pid] = [(p['x'], p['y']) for p in route['path']]
        self.routes_calculated += 1
        self.replanned_routes += int(pid in self.previously_routed)
        self.previously_routed.add(pid)
        previous = self.last_destination.get(pid)
        if previous != key:
            if previous is not None:
                self.destination_changes.append(dict(turn=turn, person_id=pid, **{'from': previous, 'to': key},
                                                    reason=self.pending_reasons.get(pid, 'replan')))
            self.last_switch[pid] = turn
        if not temporary:
            self.last_destination[pid] = key
        self.last_planned[pid] = turn
        self.planned_threat[pid] = self.risk_field.route_threat(self.paths[pid]) if self.risk_field is not None else 0
        self.pending_reasons.pop(pid, None)
        self.person_reasons.pop(pid, None)

    def at_meeting(self, person):
        assignment = self.assignments.get(person.person_id)
        return bool(assignment and assignment[0] in self.areas and person.position == assignment[1])

    def _escape(self, person, blocked, occupied, turn):
        policy = self.decision_policy
        if policy.escape_config is not None:
            history = policy.intermediate_history.get(person.person_id, ())
            if history and turn-history[-1]['turn'] < policy.escape_config['cooldown_turns'] and policy.hazard.time_to_fire(*person.position) > policy.fire_safety['imminent_margin_turns']:
                self._failure_reason = 'RETRY_COOLDOWN'
                return False
        escape = policy.temporary_escape(person, self.graph, blocked, occupied | set(self.reserved), self.congestion)
        if escape is None:
            return False
        pid, key = person.person_id, 'INTERMEDIATE'
        request = build_route_request(self.manager, self.map_name,
            {pid: {'destination_id': key, 'goal': {'x': escape.goal[0], 'y': escape.goal[1]}}},
            turn=turn, blocked_cells=blocked-{person.position})
        route = dict(schema_version=request['schema_version'], map_name=self.map_name,
            width=self.manager.width, height=self.manager.height, person_id=pid,
            destination_id=key, route_id=f'escape-{turn}-{pid}',
            goal={'x': escape.goal[0], 'y': escape.goal[1]}, path=[dict(x=x, y=y) for x, y in escape.path])
        self._commit(person, request, route, key, escape.goal, turn, temporary=True)
        if policy.escape_config is not None:
            policy.record_escape(person, escape.goal, turn)
            self.person_reasons[pid] = 'INTERMEDIATE_GOAL_PENDING'
        self.next_attempt[pid] = turn+self.retry_after_turns
        policy.intermediate_goals += 1
        policy.emit(turn, 'escape', 'ESCAPE TEMPORAL: HUMO PREVISTO')
        return True

    def advance(self, concentrations, burning, blocked, priorities, eligible, turn):
        if self.evacuation_mode is not None:
            return self._advance_policy(concentrations, burning, blocked, priorities, eligible, turn)
        blocked = set(blocked)
        previous_safe = dict(self.safe)
        self.assess(concentrations, burning, blocked_cells=blocked)
        outside = [p for p in self.manager.list_people() if p.building_id is None]
        occupied = {p.position for p in self.manager.list_people()}
        pending, valid = [], set()
        changed = previous_safe != self.safe or (self.risk_field is not None and self.risk_field.wind_changed)
        for person in outside:
            pid = person.person_id
            assignment = self.assignments.get(pid)
            status = self.follower.route_snapshot(pid)
            compromised = assignment and (self.area_policy.states[assignment[0]] == "CLOSED"
                if self.area_policy is not None else not self.safe[assignment[0]])
            obstructed = assignment and status and any(
                cell in blocked for cell in self.paths[pid][status["steps_done"]+1:])
            congested = status and status["status"] == "esperando_ocupacion" and status["waits"] >= self.retry_after_turns
            preventive = self._preventive_change(person, assignment, turn)
            predicted = False
            if self.risk_field is not None:
                cfg = self.risk_field.config
                cooldown = turn-self.last_planned.get(pid, turn) >= cfg["replan_cooldown"]
                congested = congested and cooldown
                if assignment and status and (cooldown or self.risk_field.wind_changed):
                    future_path = self.paths[pid][status["steps_done"]+1:status["steps_done"]+1+cfg["route_lookahead"]]
                    threat = self.risk_field.route_threat(future_path)
                    predicted = threat >= cfg["route_risk_threshold"] and threat-self.planned_threat.get(pid, 0) >= cfg["route_risk_increase"]
            if compromised or obstructed or congested or preventive or predicted:
                self._release(pid)
                self.next_attempt.pop(pid, None)
                if compromised or preventive:
                    self.reassignments += 1
                self.preventive_reassignments += int(preventive)
                self.predictive_route_invalidations += int(predicted)
                self.pending_reasons[pid] = ("current_danger" if compromised or obstructed else
                                            "predicted_destination" if preventive else "predicted_path" if predicted else "congestion")
                assignment = None
                if self.risk_field is None:
                    changed = True
            if assignment:
                valid.add(pid)
            elif pid in eligible:
                pending.append(person)
        self.congestion.update(outside)
        pending.sort(key=lambda p: (-priorities.get(p.person_id, 0), self.next_attempt.get(p.person_id, 0), p.person_id))
        budget = self.max_routes_per_turn
        self.last_planning_order = []
        for person in pending:
            pid = person.person_id
            if budget == 0:
                break
            if turn < self.next_attempt.get(pid, 0) and not changed:
                continue
            budget -= 1
            self.last_planning_order.append(pid)
            if self._plan(person, blocked, occupied, turn):
                valid.add(pid)
                self.next_attempt.pop(pid, None)
            else:
                self.next_attempt[pid] = turn + self.retry_after_turns
        self.follower.set_blocked_cells(blocked)
        moved = self.follower.step(eligible_person_ids=valid & set(eligible))
        self.waiting = sum(p.person_id not in self.assignments for p in outside)
        return moved

    def _advance_policy(self, concentrations, burning, blocked, priorities, eligible, turn):
        """Same routing/gateway, bounded scheduling and explicit fallback decisions."""
        if self.sixth_config is not None:
            from routing.safe_routing import advance_safe
            return advance_safe(self, concentrations, burning, blocked, priorities, eligible, turn)
        blocked = set(blocked)
        self.assess(concentrations, burning, blocked_cells=blocked)
        people = self.manager.list_people()
        outside = [p for p in people if p.building_id is None]
        occupied = {p.position for p in people}
        self.routing_obstacles = {p.position for p in outside if self.at_meeting(p) or
            (self.exposures.get(p.person_id) is not None and self.exposures[p.person_id].level == 'incapacitada')}
        route_blocks = blocked | self.routing_obstacles
        self.congestion.update(outside)
        self.arrival_flow.clear()  # Each turn is a batch; reservations update after each decision.
        pending, valid = [], set()
        policy = self.decision_policy
        if policy:
            policy.refresh_costs()
        for person in outside:
            pid = person.person_id
            assignment = self.assignments.get(pid)
            status = self.follower.route_snapshot(pid)
            reason = None
            if assignment:
                if pid in self.temporary:
                    if person.position == assignment[1] and turn >= self.next_attempt.get(pid, 0):
                        reason = 'intermediate_reached'
                elif not self.safe.get(assignment[0], False) and (
                        self.evacuation_mode == 'traditional' or self.area_policy.states[assignment[0]] == 'CLOSED'):
                    reason = 'current_danger'
                if status and any(p in blocked for p in self.paths[pid][status['steps_done']+1:]):
                    reason = 'current_danger'
                elif status and any(p in self.routing_obstacles for p in self.paths[pid][status['steps_done']+1:]):
                    reason = 'stationary_obstacle'
                if policy and reason is None:
                    reason = policy.replan_reason(person, self, status, turn)
                # Replanning occupancy every 8 turns caused churn. Only retry a
                # persistently blocked route after a longer configurable interval.
                if self.evacuation_mode != 'traditional' and reason is None and status and (
                        status['status'] == 'esperando_ocupacion' and
                        policy is not None and policy.waiting_age.get(pid, 0) >= self.retry_after_turns and
                        turn-self.last_planned.get(pid, turn) >= self.budget_config['congestion_replan_turns']):
                    reason = 'congestion'
            if reason:
                self._release(pid)
                self.next_attempt.pop(pid, None)
                predictive = reason in ('future_destination', 'predicted_destination', 'temporal_route')
                self.preventive_reassignments += int(predictive)
                self.temporal_invalidations += int(reason == 'temporal_route')
                self.reassignments += int(reason in ('future_destination', 'predicted_destination', 'current_danger'))
                self.pending_reasons[pid] = reason
                if policy and predictive:
                    self.forecast_departure_candidates[pid] = dict(turn=turn, point=person.position, reason=reason)
                    policy.emit(turn, reason, 'Ruta recalculada por humo previsto' if reason == 'temporal_route' else 'Reunion evitada por riesgo futuro')
                assignment = None
            if assignment:
                valid.add(pid)
            elif pid in eligible:
                self.pending_since.setdefault(pid, turn)
                pending.append(person)
        # Both modes get the SAME pressure-based burst cap (not a predictive advantage).
        budget = (self.budget_config['emergency_route_budget']
                  if len(pending) >= self.budget_config['burst_pending_threshold'] else self.max_routes_per_turn)
        self.last_budget = budget
        self.route_calls_remaining = budget
        self.last_searches = 0
        pending.sort(key=lambda p: (-(priorities.get(p.person_id, 0)+
            self.budget_config['queue_age_weight']*(turn-self.pending_since[p.person_id])),
            self.pending_since[p.person_id], p.person_id))
        self.last_planning_order = []
        self.unassigned_reasons.clear()
        escape_budget = self.budget_config['maximum_escapes_per_turn']
        for person in pending:
            pid = person.person_id
            unsafe = policy is not None and (policy.diagnostics.get(pid, {}).get('unsafe_wait', False) or
                (self.pending_reasons.get(pid) in ('future_destination', 'predicted_destination', 'temporal_route')
                 and policy.hazard.time_to_hazard(*person.position) < float('inf')))
            if budget <= 0:
                self.unassigned_reasons['budget_exhausted'] += 1
                continue
            if turn < self.next_attempt.get(pid, 0):
                self.unassigned_reasons['retry_cooldown'] += 1
                continue
            budget -= 1
            self.last_planning_order.append(pid)
            if unsafe and self.pending_reasons.get(pid) != 'current_danger':
                self.forecast_departure_candidates.setdefault(pid, dict(turn=turn, point=person.position, reason='unsafe_wait'))
            # A full trip cannot finish before the estimated hazard when margin
            # is negative. First try a bounded local escape, not several costly
            # campus-wide searches while remaining in the threatened cell.
            if (unsafe and escape_budget and policy.config['prefer_local_escape_on_negative_margin']
                    and policy.diagnostics.get(pid, {}).get('safety_margin', float('inf')) <= 0):
                escape_budget -= 1
                if self._escape(person, blocked, occupied, turn):
                    valid.add(pid)
                    continue
            if self._plan(person, blocked, occupied, turn):
                valid.add(pid)
                self.pending_since.pop(pid, None)
                self.next_attempt.pop(pid, None)
                continue
            if unsafe and escape_budget:
                escape_budget -= 1
                if self._escape(person, blocked, occupied, turn):
                    valid.add(pid)
                    continue
            self.unassigned_reasons['search_budget_exhausted' if self._plan_exhausted else 'no_safe_reachable_destination'] += 1
            self.next_attempt[pid] = turn+(self.budget_config['unsafe_retry_turns'] if unsafe else self.retry_after_turns)
        self.maximum_budget_used = max(self.maximum_budget_used, len(self.last_planning_order))
        self.maximum_searches_used = max(self.maximum_searches_used, self.last_searches)
        self.follower.set_blocked_cells(route_blocks)
        moved = self.follower.step(eligible_person_ids=valid & set(eligible))
        self.waiting = sum(p.person_id not in self.assignments for p in outside)
        return moved

    def gathered_count(self):
        return sum(self.safe.get(area, False) and self.manager.get_person(pid).position == goal
                   for pid, (area, goal) in self.assignments.items())

    def summary(self):
        return {"gathered": self.gathered_count(), "unassigned": self.waiting,
                "reassignments": self.reassignments, "routes_calculated": self.routes_calculated,
                "replanned_routes": self.replanned_routes,
                "preventive_reassignments": self.preventive_reassignments,
                "predictive_route_invalidations": self.predictive_route_invalidations,
                "destination_changes": len(self.destination_changes),
                "unassigned_reasons": dict(self.unassigned_reasons),
                "person_route_reasons": dict(self.person_reasons),
                "total_astar_searches": self.total_astar_searches,
                "cache_hits": self.flow.hits if self.flow else 0,
                "cache_misses": self.flow.misses if self.flow else 0,
                "flow_field_usage": self.flow.usage if self.flow else 0,
                "watchdog_stops": len(self.watchdog_events),
                "hard_invalidations": dict(self.hard_invalidations),
                "soft_replans": self.soft_replans,
                "temporary_goals": len(self.temporary), "route_budget": self.last_budget,
                "astar_searches": self.last_searches, "maximum_astar_searches": self.maximum_searches_used,
                "temporal_invalidations": self.temporal_invalidations,
                "areas": {key: {"available": self.safe[key], "smoke": self.smoke_levels[key],
                                **(self.area_policy.diagnostics.get(key, {}) if self.area_policy else {}),
                                "capacity": len(a.cells),
                                "meeting_entry_capacity": self.entry_capacity[key],
                                **self.meeting_load.get(key, {}),
                                "reserved": sum(area == key for area, _ in self.assignments.values())}
                          for key, a in self.areas.items()}}
