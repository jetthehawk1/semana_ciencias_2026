"""Destinos de reunion, reservas y rutas; sin Pygame ni campos inventados de IA."""
from __future__ import annotations

from dataclasses import dataclass
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
                 max_routes_per_turn=24, retry_after_turns=8):
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

    def assess(self, concentrations, burning, *, blocked_cells=()):
        fire = set(burning) | set(blocked_cells)
        for key, area in self.areas.items():
            self.smoke_levels[key] = max(concentrations[y][x] for x, y in area.cells)
            self.safe[key] = (area.enabled and self.smoke_levels[key] < self.smoke_threshold
                              and not any(point in fire for point in area.cells))
        return dict(self.safe)

    def _release(self, pid):
        previous = self.assignments.pop(pid, None)
        if previous:
            self.reserved.pop(previous[1], None)
        self.paths.pop(pid, None)

    def _plan(self, person, blocked, occupied, turn):
        px, py = person.position
        def distance(area):
            x, y, w, h = area.bounds
            return max(x-px, 0, px-(x+w-1)) + max(y-py, 0, py-(y+h-1))
        candidates = sorted((a for key, a in self.areas.items() if self.safe[key]),
                            key=lambda a: (distance(a), self.smoke_levels[a.area_id], a.area_id))
        for area in candidates:
            free = [point for point in area.cells
                    if point not in self.reserved and (point not in occupied or point == person.position)
                    and point not in blocked]
            if not free:
                continue
            goal = min(free, key=lambda p: (abs(p[0]-px)+abs(p[1]-py), p))
            # Permite salir de una celda con humo: el siguiente paso debe ser seguro.
            route_blocks = blocked - {person.position}
            request = build_route_request(self.manager, self.map_name, {
                person.person_id: {"destination_id": area.area_id,
                                   "goal": {"x": goal[0], "y": goal[1]}},
            }, turn=turn, blocked_cells=route_blocks)
            route = calculate_congestion_route(
                self.graph, request, person.person_id, self.congestion,
                route_id=f"meeting-{turn}-{person.person_id}-{self.routes_calculated+1}")
            if route is None:
                continue
            self.follower.set_request(request)
            self.follower.submit_route(route)
            self.assignments[person.person_id] = (area.area_id, goal)
            self.reserved[goal] = person.person_id
            self.paths[person.person_id] = [(p["x"], p["y"]) for p in route["path"]]
            self.routes_calculated += 1
            if person.person_id in self.previously_routed:
                self.replanned_routes += 1
            self.previously_routed.add(person.person_id)
            return True
        return False

    def advance(self, concentrations, burning, blocked, priorities, eligible, turn):
        blocked = set(blocked)
        previous_safe = dict(self.safe)
        self.assess(concentrations, burning, blocked_cells=blocked)
        outside = [p for p in self.manager.list_people() if p.building_id is None]
        occupied = {p.position for p in self.manager.list_people()}
        pending, valid = [], set()
        changed = previous_safe != self.safe
        for person in outside:
            pid = person.person_id
            assignment = self.assignments.get(pid)
            status = self.follower.route_snapshot(pid)
            compromised = assignment and not self.safe[assignment[0]]
            obstructed = assignment and status and any(
                cell in blocked for cell in self.paths[pid][status["steps_done"]+1:])
            congested = status and status["status"] == "esperando_ocupacion" and status["waits"] >= self.retry_after_turns
            if compromised or obstructed or congested:
                self._release(pid)
                self.next_attempt.pop(pid, None)
                if compromised:
                    self.reassignments += 1
                assignment = None
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
                "areas": {key: {"available": self.safe[key], "smoke": self.smoke_levels[key],
                                "capacity": len(a.cells),
                                "reserved": sum(area == key for area, _ in self.assignments.values())}
                          for key, a in self.areas.items()}}
