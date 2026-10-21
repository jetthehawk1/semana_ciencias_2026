"""Politica de puertas seguras sobre el mismo motor de evacuacion interior."""
from __future__ import annotations

from collections import defaultdict, deque
import json
import heapq
from pathlib import Path

from simulation.hazard_impact import HazardEvacuationController
from simulation.indoor_evacuation import _distance_field


class AdaptiveExitController(HazardEvacuationController):
    def __init__(self, manager, entrances_path, *, risk_field=None, **options):
        super().__init__(manager, entrances_path, **options)
        self._cache = {}
        self.risk_field = risk_field
        self._building_cells = {name: [] for name in manager.building_ids}
        for y, row in enumerate(manager.building_owners):
            for x, name in enumerate(row):
                if name:
                    self._building_cells[name].append((x, y))
        self.distance_rebuilds = 0
        self.blocked_exit_groups = set()
        self.alternative_exits_used = 0
        self.alternative_exits_under_blockage = 0
        self.crossings = defaultdict(int)
        self.accesses = json.loads(Path(entrances_path).read_text(encoding="utf-8"))["accesses"]
        self.by_inside = {(a["interior_cell"]["x"], a["interior_cell"]["y"]): a for a in self.accesses}
        self._eta_cache = {}
        self.safety_policy = None
        self.predictive = None
        self.dependency_retry_attempts = 0
        self.dependency_moves = 0

    def exit_time(self, person):
        """Shared unweighted safe-exit distances, separate from weighted potential."""
        name = person.building_id
        cached = self._eta_cache.get(name)
        # Doors/hazards are already part of the controller's cached signature.
        weighted_signature = self._cache.get(name, (None,))[0]
        signature = weighted_signature[:2] if weighted_signature is not None else None
        if cached is None or cached[0] != signature:
            safe = self.doors[name] if signature is None else {p: self.doors[name][p] for p in signature[0]}
            hazards = frozenset() if signature is None else signature[1]
            distances = _distance_field(safe, lambda x, y: self.manager.building_at(x, y) == name and (x, y) not in hazards)
            nearest = {p: p for p in safe}
            for point in sorted(distances, key=distances.get):
                if point in nearest:
                    continue
                x, y = point
                parent = next((q for q in ((x, y-1), (x+1, y), (x, y+1), (x-1, y))
                               if distances.get(q, float('inf')) < distances[point] and q in nearest), None)
                if parent is not None:
                    nearest[point] = nearest[parent]
            self._eta_cache[name] = (signature, distances, nearest)
        _, distances, nearest = self._eta_cache[name]
        door = nearest.get(person.position)
        return (distances.get(person.position, float('inf'))+1,
                self.doors[name][door] if door is not None else person.position)

    def hazard_routes(self, blocked):
        if self.risk_field is not None:
            import numpy as np
            quantum = self.risk_field.config["exit_risk_quantization"]
            self._risk_costs = np.rint(self.risk_field.costs/quantum)*quantum
            if self.predictive is not None:
                self._risk_costs += self.predictive.config["probability_cost"]*self.predictive.threat.probability
        interior_hazards = defaultdict(set)
        for cell in blocked:
            name = self.manager.building_at(*cell)
            if name:
                interior_hazards[name].add(cell)
        door_maps, distance_maps = {}, {}
        unavailable = defaultdict(list)
        for name, doors in self.doors.items():
            hazards = frozenset(interior_hazards[name])
            safe = {inside: outside for inside, outside in doors.items()
                    if inside not in blocked and outside not in blocked}
            if self.safety_policy is not None:
                safe = {inside:outside for inside,outside in safe.items()
                        if self.safety_policy.step_safe(None,outside)}
            for inside in doors:
                access = self.by_inside[inside]
                unavailable[access["id"].rsplit("-sub", 1)[0]].append(inside not in safe)
            risk_signature = None
            if self.risk_field is not None:
                import numpy as np
                points = self._building_cells[name]+list(doors.values())
                xs, ys = zip(*points)
                risk_signature = np.rint(self._risk_costs[ys, xs]/self.risk_field.config["exit_risk_quantization"]).astype(np.int32).tobytes()
            signature = (tuple(sorted(safe)), hazards, risk_signature)
            cached = self._cache.get(name)
            if cached is None or cached[0] != signature:
                if self.risk_field is None:
                    distances = _distance_field(safe, lambda x, y, n=name, h=hazards:
                        self.manager.building_at(x, y) == n and (x, y) not in h)
                else:
                    distances = self._weighted_distances(name, safe, hazards)
                self._cache[name] = (signature, distances)
                self.distance_rebuilds += 1
            distance_maps[name] = self._cache[name][1]
            door_maps[name] = (safe if self.risk_field is None else {
                inside: outside for inside, outside in safe.items()
                if self.risk_field.config["exit_risk_weight"]*float(self._risk_costs[outside[1], outside[0]])
                <= distance_maps[name].get(inside, float('inf'))+1e-6})
        self.blocked_exit_groups = {key for key, values in unavailable.items() if all(values)}
        return door_maps, distance_maps

    def _weighted_distances(self, name, safe, hazards):
        """Campo multisource con semillas ponderadas; mismo movimiento interior."""
        field = self.risk_field
        distances = {inside: field.config["exit_risk_weight"]*float(self._risk_costs[outside[1], outside[0]])
                     for inside, outside in safe.items()}
        queue = [(cost, x, y) for (x, y), cost in distances.items()]
        heapq.heapify(queue)
        while queue:
            cost, x, y = heapq.heappop(queue)
            if cost != distances[x, y]:
                continue
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                point = (x+dx, y+dy)
                if point in hazards or self.manager.building_at(*point) != name:
                    continue
                candidate = cost+1+float(self._risk_costs[y, x])
                if candidate < distances.get(point, float('inf')):
                    distances[point] = candidate
                    heapq.heappush(queue, (candidate, *point))
        return distances

    def indoor_candidates(self, person, distance, current_distance, occupied, blocked):
        if self.predictive is not None and person.building_id in self.predictive.affected:
            return self.predictive.candidates(person, distance, current_distance, occupied, blocked)
        candidates = super().indoor_candidates(person, distance, current_distance, occupied, blocked)
        if self.safety_policy is not None:
            candidates = [p for p in candidates if self.safety_policy.step_safe(person,p)]
            if not candidates and self.safety_policy.hazard.time_to_hazard(*person.position) < float('inf'):
                # A dynamically cut-off room may have no exit potential at all.
                # Use the SAME one-cell controller to step to a strictly safer
                # indoor neighbor while waiting for a usable exit, never fire.
                choices = [(person.x+dx,person.y+dy) for dx,dy in ((0,-1),(1,0),(0,1),(-1,0))]
                choices = [p for p in choices if p not in occupied and p not in blocked
                           and self.manager.building_at(*p)==person.building_id
                           and self.safety_policy.step_safe(person,p)]
                current_risk = self.safety_policy.risk_cost(*person.position)
                choices = [p for p in choices if self.safety_policy.risk_cost(*p) < current_risk-1e-6]
                if choices:
                    best = min(self.safety_policy.risk_cost(*p) for p in choices)
                    return [p for p in choices if self.safety_policy.risk_cost(*p)<=best+1e-6]
        if not candidates or self.risk_field is None:
            return candidates
        scores = {point: distance[point]+1+float(self._risk_costs[point[1], point[0]]) for point in candidates}
        best = min(scores.values())
        return [p for p in candidates if scores[p] <= best+1e-6]

    def current_indoor_distance(self, person, distance):
        current = super().current_indoor_distance(person,distance)
        if current is None and self.safety_policy is not None:
            # The mask forbids ENTERING danger; it must not erase the ability
            # to leave a currently compromised origin through a safe neighbor.
            neighbors = [(person.x+dx,person.y+dy) for dx,dy in ((0,-1),(1,0),(0,1),(-1,0))]
            best = min((distance[p] for p in neighbors if p in distance and
                        self.safety_policy.step_safe(person,p)),default=float('inf'))
            return best+1 if best < float('inf') else float('inf')
        return current

    def finish_indoor_pass(self, tracker, occupied, moved_ids, eligible, move_one, priority_by_person):
        """Wake an unmoved pupil when another pupil clears its next cell.

        Reuses the SAME authorized move and current hazards. Each pupil can
        succeed once; each of its four neighboring cells can wake it once.
        No extra turn, no new physics update, no extra A*, no slowdown bypass.
        """
        if self.predictive is None or not self.predictive.config.get('resolve_priority_dependencies', False):
            return 0
        pending = [pid for pid in self.ids if pid not in moved_ids and eligible(pid)
                   and self.manager.people[pid].building_id in self.predictive.affected]
        pending.sort(key=lambda pid: (-(priority_by_person or {}).get(pid, 0), pid))
        watchers = defaultdict(set)
        for pid in pending:
            person = self.manager.people[pid]
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
                watchers[person.x+dx, person.y+dy].add(pid)
        queue = deque(pending)
        queued = set(pending)
        late = 0
        while queue:
            pid = queue.popleft()
            queued.discard(pid)
            if pid in moved_ids:
                continue
            old = self.manager.people[pid].position
            self.dependency_retry_attempts += 1
            if not move_one(pid):
                continue
            moved_ids.add(pid)
            late += 1
            for other in sorted(watchers[old]):
                if other not in moved_ids and other not in queued:
                    queue.append(other)
                    queued.add(other)
        self.dependency_moves += late
        return late

    def step_with_hazards(self, tracker, burning, *, priority_by_person=None):
        before = {pid: self.manager.people[pid].position for pid in self.ids
                  if self.manager.people[pid].building_id is not None}
        result = super().step_with_hazards(tracker, burning, priority_by_person=priority_by_person)
        for pid, previous in before.items():
            if self.manager.people[pid].building_id is not None:
                continue
            access = self.by_inside[previous]
            group = access["id"].rsplit("-sub", 1)[0]
            self.crossings[group] += 1
            if access.get("role", "primary") == "secondary":
                self.alternative_exits_used += 1
                primary_blocked = any(a["building"] == access["building"]
                    and a.get("role", "primary") == "primary"
                    and a["id"].rsplit("-sub", 1)[0] in self.blocked_exit_groups for a in self.accesses)
                self.alternative_exits_under_blockage += int(primary_blocked)
        return result

    def exit_metrics(self):
        return {"blocked_exits": len(self.blocked_exit_groups),
                "alternative_exits_used": self.alternative_exits_used,
                "alternative_exits_under_blockage": self.alternative_exits_under_blockage,
                "distance_rebuilds": self.distance_rebuilds,
                "dependency_retry_attempts": self.dependency_retry_attempts,
                "dependency_moves": self.dependency_moves,
                "crossings": dict(self.crossings)}
