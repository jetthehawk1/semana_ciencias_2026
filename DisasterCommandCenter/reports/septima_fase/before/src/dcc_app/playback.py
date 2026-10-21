"""Reloj de reproduccion; no tiene acceso a fuego, humo ni personas."""
from __future__ import annotations

import math


class PlaybackClock:
    def __init__(self, config):
        self.config = dict(config)
        if (config["base_turn_interval_seconds"] <= 0 or
            type(config["max_turns_per_frame"]) is not int or config["max_turns_per_frame"] < 1):
            raise ValueError("Cadencia de reproduccion invalida.")
        self.set_speed(config["speed_multiplier"])

    def set_speed(self, multiplier):
        if (isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or
            not math.isfinite(multiplier) or not self.config["minimum_speed_multiplier"] <= multiplier <= self.config["maximum_speed_multiplier"]):
            raise ValueError("Multiplicador de reproduccion fuera de limites.")
        self.speed_multiplier = float(multiplier)
        return self.interval_seconds

    @property
    def interval_seconds(self):
        return self.config["base_turn_interval_seconds"]/self.speed_multiplier

    def due_turns(self, accumulated):
        if not math.isfinite(accumulated) or accumulated < 0:
            raise ValueError("Tiempo acumulado invalido.")
        # Cupo de trabajo por frame; conserva un resto acotado, no cambia el paso.
        count = min(self.config["max_turns_per_frame"], math.floor((accumulated+1e-12)/self.interval_seconds))
        remaining = min(self.interval_seconds, max(0, accumulated-count*self.interval_seconds))
        return count, remaining
