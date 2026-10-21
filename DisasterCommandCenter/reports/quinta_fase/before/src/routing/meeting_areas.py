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
                 max_routes_per_turn=24, retry_after_turns=8, risk_field=None, area_policy=None):
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
        return dict(self.safe)

    def _area_score(self, person, area):
        x, y, w, h = area.bounds
        distance = max(x-person.x, 0, person.x-(x+w-1)) + max(y-person.y, 0, person.y-(y+h-1))
        if self.area_policy is None:
            return (distance, self.smoke_levels[area.area_id], area.area_id)
        config = self.area_policy.config
        risk = self.area_policy.diagnostics[area.area_id]["risk_score"]
        filled = self.area_load[area.area_id]/len(area.cells)
        return (config["distance_weight"]*distance + config["destination_risk_weight"]*risk
                + config["capacity_weight"]*filled, area.area_id)

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
            self.area_load[previous[0]] -= 1
        self.paths.pop(pid, None)

    def _plan(self, person, blocked, occupied, turn):
        px, py = person.position
        candidates = sorted((a for key, a in self.areas.items() if self.safe[key]),
                            key=lambda a: self._area_score(person, a))
        # Recalcular un camino no implica cambiar un destino aun seguro. Intenta
        # primero conservarlo; si ya no hay plaza/camino, prueba las alternativas.
        previous_area = self.last_destination.get(person.person_id)
        if self.area_policy is not None and previous_area and self.safe[previous_area]:
            candidates.sort(key=lambda area: area.area_id != previous_area)
        for area in candidates:
            free = [point for point in area.cells
                    if point not in self.reserved and (point not in occupied or point == person.position)
                    and point not in blocked]
            if not free:
                continue
            goal = min(free, key=lambda p: (abs(p[0]-px)+abs(p[1]-py)
                + (self.risk_field.risk_cost(*p) if self.risk_field is not None else 0), p))
            # Permite salir de una celda con humo: el siguiente paso debe ser seguro.
            route_blocks = blocked - {person.position}
            request = build_route_request(self.manager, self.map_name, {
                person.person_id: {"destination_id": area.area_id,
                                   "goal": {"x": goal[0], "y": goal[1]}},
            }, turn=turn, blocked_cells=route_blocks)
            route = calculate_congestion_route(
                self.graph, request, person.person_id, self.congestion,
                route_id=f"meeting-{turn}-{person.person_id}-{self.routes_calculated+1}", risk_field=self.risk_field)
            if route is None:
                continue
            self.follower.set_request(request)
            self.follower.submit_route(route)
            self.assignments[person.person_id] = (area.area_id, goal)
            self.area_load[area.area_id] += 1
            self.reserved[goal] = person.person_id
            self.paths[person.person_id] = [(p["x"], p["y"]) for p in route["path"]]
            self.routes_calculated += 1
            if person.person_id in self.previously_routed:
                self.replanned_routes += 1
            self.previously_routed.add(person.person_id)
            pid = person.person_id
            previous = self.last_destination.get(pid)
            if previous != area.area_id:
                if previous is not None:
                    self.destination_changes.append({"turn": turn, "person_id": pid,
                        "from": previous, "to": area.area_id, "reason": self.pending_reasons.get(pid, "replan")})
                self.last_switch[pid] = turn
            self.last_destination[pid] = area.area_id
            self.last_planned[pid] = turn
            self.planned_threat[pid] = self.risk_field.route_threat(self.paths[pid]) if self.risk_field is not None else 0
            self.pending_reasons.pop(pid, None)
            return True
        return False

    def advance(self, concentrations, burning, blocked, priorities, eligible, turn):
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

    def gathered_count(self):
        return sum(self.safe[area] and self.manager.get_person(pid).position == goal
                   for pid, (area, goal) in self.assignments.items())

    def summary(self):
        return {"gathered": self.gathered_count(), "unassigned": self.waiting,
                "reassignments": self.reassignments, "routes_calculated": self.routes_calculated,
                "replanned_routes": self.replanned_routes,
                "preventive_reassignments": self.preventive_reassignments,
                "predictive_route_invalidations": self.predictive_route_invalidations,
                "destination_changes": len(self.destination_changes),
                "areas": {key: {"available": self.safe[key], "smoke": self.smoke_levels[key],
                                **(self.area_policy.diagnostics.get(key, {}) if self.area_policy else {}),
                                "capacity": len(a.cells),
                                "reserved": sum(area == key for area, _ in self.assignments.values())}
                          for key, a in self.areas.items()}}
