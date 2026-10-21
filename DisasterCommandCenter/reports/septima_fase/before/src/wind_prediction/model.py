"""Inferencia vectorial JSON: entrenamiento offline, persistencia ante cualquier fallo."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from simulation.wind_simulation import WIND_VECTORS
from wind_prediction.dataset import features, feature_names


@dataclass(frozen=True)
class PredictedWind:
    turn: int
    u: float
    v: float
    direction: str
    speed: float
    method: str
    fallback_reason: str | None = None
    data_source: str = "synthetic_simulation"

    @property
    def vector(self):
        return (self.u/self.speed, self.v/self.speed) if self.speed > 0 else (0.0, 0.0)


def vector_prediction(turn, u, v, method, reason=None):
    if not all(math.isfinite(value) for value in (u, v)):
        raise ValueError("Prediccion no finita.")
    magnitude = math.hypot(u, v)
    if magnitude > 1:
        u, v = u/magnitude, v/magnitude
    speed = min(1.0, magnitude)
    direction = max(WIND_VECTORS, key=lambda key: u*WIND_VECTORS[key][0]+v*WIND_VECTORS[key][1])
    return PredictedWind(turn, u, v, direction, speed, method, reason)


class PersistenceWindPredictor:
    def predict(self, measurements):
        latest = measurements[-1]
        return vector_prediction(latest["turn"]+1, latest["u"], latest["v"], "persistence")


class WindPredictor:
    def __init__(self, config, model_path=None):
        self.config = dict(config)
        self.model = None
        self.load_error = None
        self.inference_errors = 0
        self.calls = {"ridge": 0, "persistence": 0}
        self.persistence = PersistenceWindPredictor()
        if config["enabled"] and model_path is not None:
            try:
                model = json.loads(Path(model_path).read_text(encoding="utf-8"))
                names = feature_names(config["lag_count"])
                if (model["schema_version"] != "wind_predictor/1.0" or
                    model["data_source"] != "synthetic_simulation" or
                    model["feature_names"] != list(names) or
                    model["training_samples"] < config["minimum_training_samples"] or
                    model["selected_model"] not in ("ridge", "persistence")):
                    raise ValueError("Modelo de viento incompatible.")
                numeric_rows = [model["mean"], model["scale"], *model["coefficients"]]
                if len(model["coefficients"]) != 2 or any(len(row) != len(names) for row in numeric_rows):
                    raise ValueError("Dimensiones de modelo invalidas.")
                if (len(model["intercept"]) != 2 or any(s <= 0 for s in model["scale"]) or
                    any(not math.isfinite(v) for row in numeric_rows+[model["intercept"]] for v in row)):
                    raise ValueError("Coeficientes de modelo invalidos.")
                self.model = model
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.load_error = type(error).__name__

    def _ridge(self, measurements):
        raw = features([(r["u"], r["v"]) for r in measurements], self.config["lag_count"])
        standardized = [(x-m)/s for x, m, s in zip(raw, self.model["mean"], self.model["scale"])]
        values = [bias+sum(c*x for c, x in zip(row, standardized))
                  for row, bias in zip(self.model["coefficients"], self.model["intercept"])]
        return vector_prediction(measurements[-1]["turn"]+1, *values, "ridge")

    def predict(self, measurements):
        if not measurements:
            raise ValueError("Se necesita al menos una medicion para persistencia.")
        result = self.persistence.predict(measurements)
        reason = None
        if not self.config["enabled"]:
            reason = "disabled"
        elif self.model is None:
            reason = "model_unavailable"
        elif len(measurements) < self.config["lag_count"]:
            reason = "insufficient_history"
        elif self.model["selected_model"] == "persistence":
            reason = "validation_selected_persistence"
        elif any(b["turn"] != a["turn"]+1 for a, b in zip(measurements[-self.config["lag_count"]:],
                                                          measurements[-self.config["lag_count"]+1:])):
            reason = "nonconsecutive_history"
        elif all(abs(r["u"]-measurements[-1]["u"])+abs(r["v"]-measurements[-1]["v"])
                 <= self.config["constant_tolerance"] for r in measurements[-self.config["lag_count"]:]):
            reason = "constant_history"
        else:
            try:
                result = self._ridge(measurements)
            except Exception:
                self.inference_errors += 1
                reason = "inference_error"
        if reason:
            result = vector_prediction(result.turn, result.u, result.v, "persistence", reason)
        self.calls[result.method] += 1
        return result
