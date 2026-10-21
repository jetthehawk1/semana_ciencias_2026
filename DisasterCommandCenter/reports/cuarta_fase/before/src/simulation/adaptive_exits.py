"""Politica de puertas seguras sobre el mismo motor de evacuacion interior."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from simulation.hazard_impact import HazardEvacuationController
from simulation.indoor_evacuation import _distance_field


class AdaptiveExitController(HazardEvacuationController):
    def __init__(self, manager, entrances_path, **options):
        super().__init__(manager, entrances_path, **options)
        self._cache = {}
        self.distance_rebuilds = 0
        self.blocked_exit_groups = set()
        self.alternative_exits_used = 0
        self.alternative_exits_under_blockage = 0
        self.crossings = defaultdict(int)
        self.accesses = json.loads(Path(entrances_path).read_text(encoding="utf-8"))["accesses"]
        self.by_inside = {(a["interior_cell"]["x"], a["interior_cell"]["y"]): a for a in self.accesses}

    def hazard_routes(self, blocked):
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
            for inside in doors:
                access = self.by_inside[inside]
                unavailable[access["id"].rsplit("-sub", 1)[0]].append(inside not in safe)
            signature = (tuple(sorted(safe)), hazards)
            cached = self._cache.get(name)
            if cached is None or cached[0] != signature:
                distances = _distance_field(safe, lambda x, y, n=name, h=hazards:
                    self.manager.building_at(x, y) == n and (x, y) not in h)
                self._cache[name] = (signature, distances)
                self.distance_rebuilds += 1
            door_maps[name], distance_maps[name] = safe, self._cache[name][1]
        self.blocked_exit_groups = {key for key, values in unavailable.items() if all(values)}
        return door_maps, distance_maps

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
                "crossings": dict(self.crossings)}
