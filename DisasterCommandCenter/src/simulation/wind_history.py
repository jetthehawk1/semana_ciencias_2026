"""Viento configurable por API: velocidad normalizada, historial y persistencia."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from simulation.wind_simulation import Wind


@dataclass(frozen=True)
class WindState:
    turn: int
    direction: str
    speed: float
    speed_unit: str = "normalized_0_1"


class WindHistory:
    def __init__(self, direction="E", speed=0.75, *, history_limit=256):
        if type(history_limit) is not int or history_limit < 1:
            raise ValueError("history_limit debe ser positivo.")
        Wind(direction, speed)
        self.history = deque(maxlen=history_limit)
        self.state = WindState(0, direction, float(speed))
        self.history.append(self.state)
        self.measurements = deque(maxlen=history_limit)

    def observe(self, observations):
        """Una muestra global por turno, aunque dos sensores midan el mismo vector.

        Los cambios del control dentro de un turno siguen en history; el predictor
        usa solo measurements, procedentes de telemetria y sin duplicados.
        """
        from integration.wind_telemetry import validate_wind_observation
        rows = [validate_wind_observation(row) for row in observations]
        if not rows:
            return
        first = rows[0]
        if any((r["run_id"], r["turn"], r["wind_direction"], r["wind_speed"]) !=
               (first["run_id"], first["turn"], first["wind_direction"], first["wind_speed"]) for r in rows):
            raise ValueError("Esta politica requiere un vector global coherente por turno.")
        wx, wy = Wind(first["wind_direction"], first["wind_speed"]).vector
        sample = {"turn": first["turn"], "u": wx*first["wind_speed"], "v": wy*first["wind_speed"]}
        if self.measurements and sample["turn"] <= self.measurements[-1]["turn"]:
            if sample == self.measurements[-1]:
                return
            raise ValueError("Medicion retrocedida o modificada en el mismo turno.")
        self.measurements.append(sample)

    def configure(self, direction, speed, *, turn):
        Wind(direction, speed)  # valida antes de alterar historial o motor
        if type(turn) is not int or turn < self.state.turn:
            raise ValueError("Turno de viento invalido.")
        state = WindState(turn, direction, float(speed))
        self.state = state
        if self.history[-1] != state:
            self.history.append(state)
        return state

    def record(self, turn):
        return self.configure(self.state.direction, self.state.speed, turn=turn)

    def predict_next(self):
        """Persistencia: mismo rumbo/velocidad del ultimo dato, no meteorologia."""
        latest = self.history[-1]
        return WindState(latest.turn+1, latest.direction, latest.speed)
