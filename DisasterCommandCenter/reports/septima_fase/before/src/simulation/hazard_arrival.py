"""ETA heuristica en turnos discretos; nunca modifica fuego, humo ni viento."""
from __future__ import annotations

import numpy as np
from scipy.ndimage import distance_transform_edt


class HazardArrivalField:
    """Campo compartido O(grid), sin consultar entradas futuras del escenario.

    Distancia/vector a la fuente observada mas cercana, frente difusivo y
    transporte a sotavento. Infinito significa fuera del horizonte, no seguro
    para siempre. Las brasas solo reducen la ETA cerca de combustible y con
    viento suficiente; no se conocen sus sorteos futuros.
    """
    def __init__(self, terrain, config, fire_behavior, smoke_behavior):
        self.terrain = np.asarray(terrain)
        self.config = config
        self.fire_behavior, self.smoke_behavior = fire_behavior, smoke_behavior
        self.eta = np.full(self.terrain.shape, np.inf, dtype=np.float32)
        self.fire_eta = self.eta.copy()
        self.smoke_eta = self.eta.copy()
        self.fire_safety = None
        self.urgency_cost = np.zeros_like(self.eta)
        self._ys, self._xs = np.indices(self.terrain.shape)
        self.turn = 0

    def update(self, risk, wind, predicted_wind):
        c = self.config
        smoke = risk.smoke
        sources = (smoke >= c['source_smoke_threshold']) | (risk.fire_distance == 0)
        self.eta.fill(np.inf)
        self.fire_eta.fill(np.inf)
        self.smoke_eta.fill(np.inf)
        if np.any(sources):
            distance, indices = distance_transform_edt(~sources, return_indices=True)
            sy, sx = indices
            dx, dy = self._xs-sx, self._ys-sy
            current = wind.vector
            future = predicted_wind.vector
            estimates = []
            for (wx, wy), speed in ((current, wind.intensity), (future, predicted_wind.speed)):
                along = dx*wx+dy*wy
                lateral = np.abs(dx*wy-dy*wx)
                downwind = np.maximum(0, along)
                drift = max(c['minimum_drift'], self.smoke_behavior['advection_rate']*speed)
                # Lateral diffusion is deliberately slower than downwind advection.
                travel = downwind/drift + lateral/c['lateral_cells_per_turn']
                travel = np.where(along >= 0, travel, distance/c['upwind_cells_per_turn'])
                if speed == 0:
                    # A calm prediction has vector (0,0); projection alone
                    # would falsely yield zero travel time at every cell.
                    travel = distance/c['lateral_cells_per_turn']
                strength = np.maximum(smoke[sy, sx], (risk.fire_distance[sy, sx] == 0)*1.0)
                buildup = c['accumulation_turns']*(1-strength)
                estimates.append(travel+buildup)
            smoke_eta = np.minimum(*estimates)
            # Project only locally; don't claim knowledge of half the campus.
            smoke_eta[distance > c['maximum_source_distance']] = np.inf
            fire_rate = self.fire_behavior['base_spread_rate']
            fuel_multiplier = np.where(self.terrain == 'grass', self.fire_behavior['vegetation_multiplier'], 1.)
            fuel_multiplier *= 1+(self.fire_behavior['laboratory_multiplier']-1)*risk.laboratory_proximity
            fire_eta = np.maximum(0, risk.fire_distance-c['fire_clearance_cells']) / np.maximum(.001, fire_rate*fuel_multiplier)
            if self.fire_behavior['spotting_enabled'] and wind.intensity >= self.fire_behavior['spotting_min_wind']:
                near_fuel = np.isin(self.terrain, ('grass', 'building')) & (risk.predicted_smoke >= c['spotting_plume_threshold'])
                fire_eta = np.where(near_fuel, np.minimum(fire_eta, c['spotting_precaution_turns']), fire_eta)
            # Separate diagnostic fields keep the original horizon heuristic;
            # the additional conservative clearance is a DECISION policy only.
            if self.fire_safety is not None:
                fire_eta[risk.fire_distance <= self.fire_safety['clearance_cells']] = 0
            self.fire_eta[:] = fire_eta
            self.smoke_eta[:] = smoke_eta
            self.fire_eta[self.fire_eta > c['horizon_turns']] = np.inf
            self.smoke_eta[self.smoke_eta > c['horizon_turns']] = np.inf
            self.smoke_eta[smoke >= c['danger_smoke_threshold']] = 0
            self.eta[:] = np.minimum(smoke_eta, fire_eta)
            self.eta[self.eta > c['horizon_turns']] = np.inf
        self.eta[(smoke >= c['danger_smoke_threshold']) | (risk.fire_distance <= c['fire_clearance_cells'])] = 0
        self.urgency_cost[:] = c['routing_weight']*np.maximum(0, 1-self.eta/c['horizon_turns'])**2
        self.turn = risk.turn

    def time_to_hazard(self, x, y):
        return float(self.eta[y, x])

    def time_to_fire(self, x, y):
        return float(self.fire_eta[y, x])

    def time_to_smoke(self, x, y):
        return float(self.smoke_eta[y, x])

    def arrival_turn(self, x, y):
        return self.turn+self.time_to_hazard(x, y)
