"""Coste preventivo compartido: geometria Manhattan y corredor didactico de humo."""
from __future__ import annotations

import math
import numpy as np
from scipy.ndimage import distance_transform_cdt

NO_FIRE_DISTANCE = np.iinfo(np.int32).max


class DynamicRiskField:
    def __init__(self, terrain, config, *, owners=None, properties=None):
        self.terrain = np.asarray(terrain)
        self.height, self.width = self.terrain.shape
        self.config = dict(config)
        for key, value in config.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Parametro de riesgo invalido: {key}")
        for key in ("fire_radius", "vegetation_radius", "laboratory_radius", "plume_stride", "route_lookahead"):
            if type(config[key]) is not int or config[key] < 1:
                raise ValueError(f"{key} debe ser entero positivo.")
        if not 0 <= config["current_wind_fraction"] <= 1:
            raise ValueError("Fraccion de viento invalida.")
        if config["exit_risk_quantization"] <= 0:
            raise ValueError("La cuantizacion de riesgo debe ser positiva.")
        self.costs = np.zeros(self.terrain.shape, dtype=np.float32)
        self.fire_distance = np.full(self.terrain.shape, NO_FIRE_DISTANCE, dtype=np.int32)
        self.fire_proximity = self.costs.copy()
        self.vegetation_proximity = self.costs.copy()
        self.laboratory_proximity = self.costs.copy()
        self.predicted_smoke = self.costs.copy()
        self.smoke = self.costs.copy()
        self._fires = None
        self._vegetation_fires = None
        self._last_wind = None
        self.wind_changed = False
        self.turn = 0
        self.updates = 0
        self.lab_fields = {}
        if owners is not None and properties is not None:
            owner_array = np.asarray(owners)
            for name, props in properties.items():
                if props["laboratory"] and props["flammable_materials"]:
                    self.lab_fields[name] = self._proximity(owner_array == name, config["laboratory_radius"])[1]

    def _proximity(self, mask, radius):
        if not np.any(mask):
            distance = np.full(self.terrain.shape, NO_FIRE_DISTANCE, dtype=np.int32)
        else:
            distance = distance_transform_cdt(~mask, metric="taxicab")
        return distance, np.maximum(0, 1-distance/(radius+1)).astype(np.float32)**2

    @staticmethod
    def _stamp(destination, source, dx, dy, weight):
        h, w = source.shape
        if abs(dx) >= w or abs(dy) >= h:
            return
        xa, xb = max(0, dx), min(w, w+dx)
        ya, yb = max(0, dy), min(h, h+dy)
        target = destination[ya:yb, xa:xb]
        np.maximum(target, source[ya-dy:yb-dy, xa-dx:xb-dx]*weight, out=target)

    def _plume(self, sources, wind_vector, speed):
        cfg = self.config
        stride = cfg["plume_stride"]
        h, w = self.height, self.width
        pad = np.pad(sources, ((0, (-h) % stride), (0, (-w) % stride)))
        source = pad.reshape(pad.shape[0]//stride, stride, pad.shape[1]//stride, stride).max(axis=(1, 3))
        result = np.zeros_like(source)
        if speed < cfg["minimum_plume_speed"] or not np.any(source):
            return np.zeros_like(sources)
        wx, wy = wind_vector
        length = cfg["plume_length"]*speed/stride
        for distance in range(1, math.ceil(length)+1):
            decay = max(0, 1-distance/(length+1))
            width = math.ceil(cfg["plume_initial_width"]/stride+cfg["plume_lateral_growth"]*distance)
            for side in range(-width, width+1):
                dx = round(wx*distance-wy*side)
                dy = round(wy*distance+wx*side)
                lateral = 1-abs(side)/(width+1)
                self._stamp(result, source, dx, dy, decay*lateral)
        return np.repeat(np.repeat(result, stride, axis=0), stride, axis=1)[:h, :w]

    def update(self, burning, concentrations, current_wind, predicted_wind, *, turn=0, building_risk=None):
        cfg = self.config
        fires = frozenset(burning)
        if fires != self._fires:
            mask = np.zeros(self.terrain.shape, dtype=bool)
            if fires:
                xs, ys = zip(*fires); mask[ys, xs] = True
            self.fire_distance, self.fire_proximity = self._proximity(mask, cfg["fire_radius"])
            grass = mask & (self.terrain == "grass")
            self._vegetation_distance, self.vegetation_proximity = self._proximity(grass, cfg["vegetation_radius"])
            self._fires = fires
        self.smoke = np.asarray(concentrations, dtype=np.float32)
        sources = np.where(self.smoke >= cfg["plume_source_smoke_threshold"], self.smoke, 0).copy()
        if fires:
            xs, ys = zip(*fires); sources[ys, xs] = 1.0
        current = self._plume(sources, current_wind.vector, current_wind.intensity)
        wx, wy = current_wind.vector
        future = (current if (wx*current_wind.intensity, wy*current_wind.intensity) == (predicted_wind.u, predicted_wind.v)
                  else self._plume(sources, predicted_wind.vector, predicted_wind.speed))
        share = cfg["current_wind_fraction"]
        self.predicted_smoke = share*current+(1-share)*future
        if building_risk is not None:
            building_risk.update_from_distance(self.fire_distance)
        self.laboratory_proximity.fill(0)
        if building_risk is not None:
            for name, field in self.lab_fields.items():
                if building_risk.levels[name] == "critical":
                    np.maximum(self.laboratory_proximity, field, out=self.laboratory_proximity)
        self.costs = (cfg["fire_proximity_weight"]*self.fire_proximity + cfg["current_smoke_weight"]*self.smoke
            + cfg["burning_vegetation_weight"]*self.vegetation_proximity
            + cfg["laboratory_proximity_weight"]*self.laboratory_proximity
            + cfg["predicted_smoke_weight"]*self.predicted_smoke)
        wx, wy = current_wind.vector
        signature = (wx*current_wind.intensity, wy*current_wind.intensity, predicted_wind.u, predicted_wind.v)
        self.wind_changed = self._last_wind is None or max(abs(a-b) for a, b in zip(signature, self._last_wind)) >= cfg["prediction_wind_change_threshold"]
        if self.wind_changed:
            self._last_wind = signature
        self.turn, self.updates = turn, self.updates+1

    def risk_cost(self, x, y):
        return float(self.costs[y, x])

    def route_threat(self, path):
        if not path:
            return 0.0
        xs, ys = zip(*path)
        return float(np.maximum(self.predicted_smoke[ys, xs], self.fire_proximity[ys, xs]).max())
