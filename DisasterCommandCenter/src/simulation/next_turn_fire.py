"""Precaution from observed fire, never from future RNG draws or wind inputs."""
from __future__ import annotations

import numpy as np

CARDINAL = ((0, -1), (1, 0), (0, 1), (-1, 0))


class NextTurnFireThreat:
    """Local union approximation over a short configured horizon.

    One-step contact probabilities use the real engine's probability function.
    Later steps assume independent ignition events and continuing sources; this
    is a precaution score, not a calibrated probability or an ignition oracle.
    Spotting contributes its uniform directional proposal probability without
    consuming either RNG. Only currently ignitable cells can be frontier.
    """
    def __init__(self, fire, config):
        self.fire, self.config = fire, config
        self.probability = np.zeros((fire.height, fire.width), dtype=np.float32)
        self.spot_probability = np.zeros_like(self.probability)
        self.frontier = np.zeros_like(self.probability, dtype=bool)
        self.current = np.zeros_like(self.frontier)
        self.turn = -1

    def update(self, wind):
        fire = self.fire
        self.probability.fill(0); self.spot_probability.fill(0)
        self.current.fill(False)
        sources = dict.fromkeys(fire.burning, 1.)
        for x, y in sources:
            self.current[y, x] = True
        probabilities = dict(sources)
        for _ in range(self.config['horizon_turns']):
            survival = {}
            for source, source_probability in probabilities.items():
                x, y = source
                for dx, dy in CARDINAL:
                    target = x+dx, y+dy
                    if not fire.can_ignite(*target):
                        continue
                    chance = source_probability*fire.spread_probability(source, target, wind)
                    survival[target] = survival.get(target, 1.)*(1.-chance)
            probabilities = {**sources, **{p: 1.-v for p, v in survival.items()}}
        for (x, y), probability in probabilities.items():
            self.probability[y, x] = probability
        cfg = fire.behavior
        if cfg['spotting_enabled'] and wind.intensity >= cfg['spotting_min_wind'] and wind.intensity > 0:
            offsets = np.asarray(fire.spot_offsets[wind.direction], dtype=np.int16)
            if len(offsets):
                chance = cfg['spotting_probability']*wind.intensity/len(offsets)
                # The configured global cap makes this an upper approximation.
                for x, y in sources:
                    points = offsets+(x, y)
                    valid = ((points[:, 0] >= 0) & (points[:, 0] < fire.width)
                             & (points[:, 1] >= 0) & (points[:, 1] < fire.height))
                    points = points[valid]
                    self.spot_probability[points[:, 1], points[:, 0]] += chance
                for y, x in zip(*np.nonzero(self.spot_probability)):
                    if not fire.can_ignite(int(x), int(y)):
                        self.spot_probability[y, x] = 0
                self.probability[:] = 1.-(1.-self.probability)*(1.-self.spot_probability)
        self.frontier[:] = self.probability >= self.config['frontier_probability']
        self.frontier[self.current] = False
        self.turn = fire.turn

    def classify(self, point):
        x, y = point
        return 'FIRE_NOW' if self.current[y, x] else 'FIRE_FRONTIER' if self.frontier[y, x] else 'SAFE'
