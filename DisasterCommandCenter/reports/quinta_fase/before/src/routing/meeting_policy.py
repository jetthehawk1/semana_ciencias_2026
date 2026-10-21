"""Estados preventivos y recuperacion estable de las ocho zonas de reunion."""
from __future__ import annotations

import math


class MeetingAreaPolicy:
    def __init__(self, areas, config, smoke_threshold):
        self.config, self.smoke_threshold = dict(config), smoke_threshold
        if (any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in config.values())
            or not 0 < config["caution_threshold"] < config["avoid_threshold"] < 1
            or config["hysteresis"] >= config["caution_threshold"]):
            raise ValueError("Politica de reuniones invalida.")
        self.indices = {a.area_id: tuple(zip(*a.cells)) for a in areas}
        self.states = {a.area_id: "SAFE" for a in areas}
        self.changed_at = {a.area_id: 0 for a in areas}
        self.diagnostics = {}
        self.transitions = []

    def evaluate(self, areas, closed, smoke_levels, risk_field, turn):
        c = self.config
        for key, area in areas.items():
            xs, ys = self.indices[key]
            fire = float(risk_field.fire_proximity[ys, xs].max())
            vegetation = float(risk_field.vegetation_proximity[ys, xs].max())
            lab = float(risk_field.laboratory_proximity[ys, xs].max())
            predicted = float(risk_field.predicted_smoke[ys, xs].max())
            smoke = smoke_levels[key]/self.smoke_threshold
            score = min(1.0, c["fire_weight"]*fire + c["vegetation_weight"]*vegetation
                        + c["laboratory_weight"]*lab + c["current_smoke_weight"]*smoke
                        + c["predicted_risk_weight"]*predicted)
            old = self.states[key]
            if closed[key]:
                state = "CLOSED"
            else:
                state = "AVOID" if score >= c["avoid_threshold"] else "CAUTION" if score >= c["caution_threshold"] else "SAFE"
                severity = {"SAFE": 0, "CAUTION": 1, "AVOID": 2, "CLOSED": 3}
                if severity[state] < severity[old]:
                    threshold = c["avoid_threshold"] if old in ("AVOID", "CLOSED") else c["caution_threshold"]
                    if score >= threshold-c["hysteresis"] or turn-self.changed_at[key] < c["recovery_turns"]:
                        # CLOSED puede pasar a AVOID tras desaparecer el peligro actual;
                        # no se habilita para nuevos destinos antes de recuperarse.
                        state = "AVOID" if old == "CLOSED" else old
            if state != old:
                self.changed_at[key] = turn
                self.transitions.append({"turn": turn, "area_id": key, "from": old, "to": state, "score": score})
            self.states[key] = state
            self.diagnostics[key] = {"state": state, "risk_score": score,
                "predicted_smoke": predicted, "fire_distance": int(risk_field.fire_distance[ys, xs].min()),
                "fire_proximity": fire, "current_smoke": smoke_levels[key]}
        return dict(self.states)
