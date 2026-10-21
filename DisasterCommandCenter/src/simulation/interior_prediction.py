"""Predictive choices for AdaptiveExitController; never moves a person itself."""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import heapq
import math

from simulation.next_turn_fire import CARDINAL


@dataclass(frozen=True)
class InteriorSafeIntermediateGoal:
    cells: frozenset
    distances: dict
    quality: float


class PredictiveInteriorPolicy:
    def __init__(self, controller, threat, config):
        self.controller, self.threat, self.config = controller, threat, config
        self.policy = controller.safety_policy
        self.risk, self.hazard = self.policy.risk, self.policy.hazard
        self.groups = {}
        for access in controller.accesses:
            self.groups.setdefault(access['building'], set()).add(access['id'].rsplit('-sub', 1)[0])
        self.exit_counts = {name: len(groups) for name, groups in self.groups.items()}
        self.single_exit_buildings = sorted(name for name, count in self.exit_counts.items() if count == 1)
        self.neighbors = {p: tuple((p[0]+dx, p[1]+dy) for dx, dy in CARDINAL
                           if controller.manager.building_at(p[0]+dx, p[1]+dy) == name)
                          for name, points in controller._building_cells.items() for p in points}
        self.refuges = {}
        self.affected = set()
        self.diagnostics = {}
        self.actions = Counter()
        self.refuge_history = {}

    def prepare(self, tracker):
        self.tracker = tracker
        self.refuges.clear()
        self.affected = {name for name, points in self.controller._building_cells.items()
                         if any(self.risk.fire_distance[y, x] <= self.config['building_alert_distance'] for x, y in points)}

    def priority(self, person):
        name = person.building_id
        if name not in self.affected:
            return 0.
        x, y = person.position
        frontier = bool(self.threat.frontier[y, x])
        redundancy = (self.config['single_exit_threat_priority'] if self.exit_counts[name] == 1 else
                      self.config['two_exit_threat_priority'] if self.exit_counts[name] == 2 else 0)
        value = redundancy+(self.config['frontier_priority'] if frontier else 0)
        self.diagnostics[person.person_id] = dict(frontier=frontier, exit_groups=self.exit_counts[name],
            exit_redundancy_risk=redundancy, fire_eta=self.hazard.time_to_fire(x, y),
            smoke_eta=self.hazard.time_to_smoke(x, y),
            toxic_dose_eta=self.policy.diagnostics.get(person.person_id, {}).get('toxic_dose_eta', math.inf))
        return value

    def safe(self, point):
        x, y = point
        return (not self.threat.current[y, x] and not self.threat.frontier[y, x]
                and self.hazard.fire_eta[y, x] > self.policy.fire_safety['imminent_margin_turns']
                and self.risk.smoke[y, x] < self.policy.fire_safety['watchdog_smoke_threshold'])

    def quality(self, point):
        x, y = point
        c = self.config
        return (c['fire_distance_weight']*min(60., float(self.risk.fire_distance[y, x]))
                + min(60., float(self.hazard.fire_eta[y, x]))
                - c['smoke_weight']*float(self.risk.smoke[y, x])
                - c['predicted_smoke_weight']*float(self.risk.predicted_smoke[y, x])
                + len(self.neighbors[point]))

    def _refuge_fields(self, name, blocked):
        """One component/goal field per threatened building and turn, not pupil."""
        if name in self.refuges:
            return self.refuges[name]
        remaining = {p for p in self.controller._building_cells[name] if p not in blocked and self.safe(p)}
        result = {}
        while remaining:
            start = min(remaining)
            component = {start}; queue = deque([start]); remaining.remove(start)
            while queue:
                for neighbor in self.neighbors[queue.popleft()]:
                    if neighbor in remaining:
                        remaining.remove(neighbor); component.add(neighbor); queue.append(neighbor)
            # A static connection to a registered exit is mandatory. Prefer
            # branching cells; a cul-de-sac is used only if the whole component
            # offers no such alternative. Occupancy is checked at each step.
            candidates = [p for p in component if p in self.controller.indoor_distance[name]
                          and sum(q in component for q in self.neighbors[p]) >= self.config['refuge_degree_minimum']]
            if not candidates:
                candidates = [p for p in component if p in self.controller.indoor_distance[name]]
            if not candidates:
                continue
            occupied = self.controller._occupied()
            candidates = [p for p in candidates if p not in occupied]
            if not candidates:
                continue
            mobile = sum(p.building_id == name and self.tracker.records[p.person_id].level != 'incapacitada'
                         for p in self.controller.manager.people.values())
            # A single maximum funnels a whole class into a corner. Offer a
            # free high-quality tier, with room for the pending population.
            wanted = max(math.ceil(len(candidates)*self.config['refuge_candidate_fraction']),
                         math.ceil(mobile*self.config['refuge_cells_per_mobile']))
            scores = sorted((self.quality(p) for p in candidates), reverse=True)
            best = scores[min(len(scores), wanted)-1]
            goals = frozenset(p for p in candidates if self.quality(p) >= best)
            distances = dict.fromkeys(goals, 0.)
            heap = [(0., *p) for p in sorted(goals)]; heapq.heapify(heap)
            while heap:
                cost, x, y = heapq.heappop(heap)
                if cost != distances[x, y]:
                    continue
                for p in self.neighbors[x, y]:
                    if p not in component:
                        continue
                    candidate = cost+1.+float(self.risk.smoke[y, x])*self.config['smoke_weight']
                    if candidate < distances.get(p, math.inf):
                        distances[p] = candidate; heapq.heappush(heap, (candidate, *p))
            # quality is a LOWER BOUND for every offered goal, not its maximum.
            # The movement gate therefore still requires a genuine gain.
            refuge = InteriorSafeIntermediateGoal(goals, distances, best)
            for p in component:
                result[p] = refuge
        self.refuges[name] = result
        return result

    def candidates(self, person, distances, current, occupied, blocked):
        name = person.building_id
        choices = [p for p in self.neighbors[person.position]
                   if p not in occupied and p not in blocked and self.safe(p)]
        if not choices:
            self.actions['waiting_no_safe_neighbor'] += 1
            return []
        descending = [p for p in choices if distances.get(p, math.inf) < current]
        x, y = person.position
        emergency = bool(self.threat.frontier[y, x]) or self.hazard.fire_eta[y, x] <= self.policy.fire_safety['imminent_margin_turns']
        if descending:
            # Exit field remains shared. Frontier probability is an additional
            # decision cost; only one deterministic best next cell is returned.
            dest = min(descending, key=lambda p: (distances[p]
                + self.config['probability_cost']*float(self.threat.probability[p[1], p[0]])
                + self.config['smoke_weight']*float(self.risk.smoke[p[1], p[0]]), p))
            self.actions['preventive_exit' if emergency else 'safe_exit'] += 1
            self.diagnostics.setdefault(person.person_id, {})['action'] = 'salida segura'
            return [dest]
        fields = self._refuge_fields(name, blocked)
        options = []
        for p in choices:
            refuge = fields.get(p)
            if refuge is None or refuge.quality < self.quality(person.position)+self.config['refuge_minimum_gain']:
                continue
            origin_distance = refuge.distances.get(person.position, math.inf)
            if refuge.distances[p] < origin_distance:
                options.append((refuge.distances[p], -refuge.quality, p))
        if options:
            _, _, dest = min(options)
            self.actions['interior_refuge'] += 1
            self.refuge_history[person.person_id] = dict(turn=self.threat.turn, point=dest)
            self.diagnostics.setdefault(person.person_id, {})['action'] = 'refugio interior temporal'
            return [dest]
        # A frontier origin may be outside the safe component. Leaving it is
        # still possible, with an explicit quality improvement, never random.
        better = [p for p in choices if self.quality(p) > self.quality(person.position)+self.config['refuge_minimum_gain']
                  or (emergency and self.hazard.time_to_fire(*p) > self.hazard.time_to_fire(*person.position))]
        if emergency and better:
            self.actions['emergency_escape'] += 1
            return [min(better, key=lambda p: (-self.quality(p), p))]
        self.actions['waiting_no_improvement'] += 1
        return []
