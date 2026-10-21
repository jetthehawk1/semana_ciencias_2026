"""Same observer in both modes. No metric controls or forces the simulation."""
from __future__ import annotations

from collections import deque
import math
import numpy as np

from routing.intelligent_policy import IntelligentEvacuationPolicy


class EvacuationMetrics:
    def __init__(self, simulation):
        s = simulation
        self.observer = IntelligentEvacuationPolicy(s.risk_field, s.hazard_arrival,
            s.config['intelligent_evacuation'], s.config['route_safety'], s.config['meeting_assignment'])
        self.waiting_age = {}
        self.first_arrivals = {}
        self.close_contacts = set()
        self.unsafe_waiting_person_turns = 0
        self.distance_traveled = 0
        self.maximum_congestion = 0
        self.later_hazard_people = set()
        self.recent_occupancy = deque(maxlen=s.config['hazard_arrival']['horizon_turns'])
        self.confirmed_departures = []
        self.expired_departures = 0
        self.pending_departures = []
        self._departure_ids = set()
        self.destination_failures = []
        self._last_assignment = {}
        self._failed_assignment = set()
        self.samples = []
        self.states = {}
        self._people_ids = [p.person_id for p in s.people]

    def sample(self, s, previous):
        turn = s.environment.fire.turn
        field = s.hazard_arrival
        risk = s.risk_field
        smoke = risk.smoke
        threshold = s.config['hazard_arrival']['danger_smoke_threshold']
        dangerous = (smoke >= threshold) | (risk.fire_distance <= s.config['hazard_arrival']['fire_clearance_cells'])
        for occupancy in self.recent_occupancy:
            mask = dangerous[occupancy[:, 1], occupancy[:, 0]]
            self.later_hazard_people.update(self._people_ids[i] for i in np.flatnonzero(mask))
        self.recent_occupancy.append(np.asarray([p.position for p in s.people], dtype=np.int16))
        for event in self.pending_departures[:]:
            x, y = event['point']
            if dangerous[y, x] and s.manager.get_person(event['person_id']).position != (x, y):
                self.confirmed_departures.append({**event, 'confirmed_turn': turn})
                self.pending_departures.remove(event)
            elif turn-event['departure_turn'] > field.config['horizon_turns']:
                self.pending_departures.remove(event)
                self.expired_departures += 1
        changed_people = {e['person_id'] for e in s.router.destination_changes if e['turn'] == turn}
        for p in s.people:
            pid = p.person_id
            old = previous[pid]
            moved = abs(p.x-old[0])+abs(p.y-old[1])
            self.distance_traveled += moved
            exposure = s.tracker.records[pid]
            hazard_eta = field.time_to_hazard(*old)
            evacuation_eta = self.observer.evacuation_eta(p, s.router, s.controller, exposure)
            unsafe = math.isfinite(hazard_eta) and hazard_eta-evacuation_eta <= self.observer.config['unsafe_wait_margin_turns']
            if exposure.level == 'incapacitada':
                state = 'INCAPACITATED'
            elif not moved and unsafe:
                state = 'WAITING_UNSAFE'
                self.unsafe_waiting_person_turns += 1
            elif s.router.at_meeting(p):
                state = 'AT_MEETING_AREA'
            elif not moved:
                state = 'WAITING_SAFE'
            elif pid in changed_people:
                state = 'REASSIGNING'
            else:
                state = 'EVACUATING'
            self.states[pid] = state
            if risk.fire_distance[old[1], old[0]] <= 3:
                self.close_contacts.add(pid)
            if s.router.at_meeting(p) and s.router.safe.get(s.router.assignments[pid][0], False):
                self.first_arrivals.setdefault(pid, turn)
            event = s.router.forecast_departure_candidates.get(pid)
            if moved and event and event['point'] == old:
                signature = (pid, event['turn'])
                if signature not in self._departure_ids:
                    self._departure_ids.add(signature)
                    self.pending_departures.append(dict(person_id=pid, point=old, reason=event['reason'], departure_turn=turn))
                s.router.forecast_departure_candidates.pop(pid, None)
            previous_assignment = self._last_assignment.get(pid)
            assignment = s.router.assignments.get(pid)
            for observed, assigned_turn in ([previous_assignment] if previous_assignment else [])+(
                    [(assignment, s.router.last_switch.get(pid, 0))] if assignment else []):
                if observed[0] not in s.router.areas or old == observed[1]:
                    continue
                # A new path/goal inside the same area is not a new destination.
                key = (pid, observed[0], assigned_turn)
                area = observed[0]
                # Symmetric predictive assessment, including Traditional decisions.
                if s.router.area_policy.states[area] in ('AVOID', 'CLOSED') and key not in self._failed_assignment:
                    self.destination_failures.append(dict(person_id=pid, area=area, turn=turn))
                    self._failed_assignment.add(key)
            self._last_assignment[pid] = (assignment, s.router.last_switch.get(pid, 0)) if assignment else None
        self.maximum_congestion = max(self.maximum_congestion, max(s.router.congestion.congestion_map.values(), default=0))

    def result(self, s):
        records = list(s.tracker.records.values())
        arrivals = list(self.first_arrivals.values())
        from statistics import mean, median
        return dict(safe_meeting_arrivals=s.router.gathered_count(),
            people_ever_reached_meeting=len(arrivals), mean_turns_to_first_meeting=mean(arrivals) if arrivals else None,
            median_turns_to_first_meeting=median(arrivals) if arrivals else None,
            worst_turns_to_first_meeting=max(arrivals) if arrivals else None,
            people_exposed_smoke=sum(r.peak_smoke > 0 for r in records),
            accumulated_smoke_dose=sum(r.dose for r in records),
            people_close_to_fire=len(self.close_contacts),
            fire_contacts=sum(r.fire_contact for r in records),
            incapacitated=sum(r.level == 'incapacitada' for r in records),
            routes_recalculated=s.router.replanned_routes, preventive_reassignments=s.router.preventive_reassignments,
            maximum_congestion=self.maximum_congestion, distance_traveled=self.distance_traveled,
            people_in_cells_that_later_became_hazardous=len(self.later_hazard_people),
            unsafe_waiting_person_turns=self.unsafe_waiting_person_turns,
            destination_became_unsafe_before_arrival=len(self.destination_failures),
            confirmed_forecast_departures=len(self.confirmed_departures),
            forecast_departures=len(self._departure_ids),
            unconfirmed_forecast_departures=len(self.pending_departures),
            expired_unconfirmed_forecast_departures=self.expired_departures,
            temporary_goals=s.decision_policy.intermediate_goals if s.decision_policy else 0,
            temporal_routes_rejected=s.decision_policy.temporal_rejections if s.decision_policy else 0,
            unassigned=s.router.waiting,
            state_counts={key: sum(v == key for v in self.states.values()) for key in
                ('WAITING_SAFE', 'WAITING_UNSAFE', 'EVACUATING', 'REASSIGNING', 'AT_MEETING_AREA', 'INCAPACITATED')})
