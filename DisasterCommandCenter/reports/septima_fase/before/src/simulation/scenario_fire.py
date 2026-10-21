"""Fuego didactico configurable del escenario fino; no cambia defaults legacy."""
from __future__ import annotations

import hashlib
import math
import random

from simulation.wind_simulation import Wind, WIND_VECTORS, WindFireSimulation


class ScenarioFireSimulation(WindFireSimulation):
    def __init__(self, terrain, combustible, *, behavior, owners, properties, seed=2026):
        self.behavior = dict(behavior)
        for key in ("base_spread_rate", "vegetation_multiplier", "laboratory_multiplier",
                    "wind_multiplier", "spotting_probability", "spotting_min_wind", "spotting_min_alignment"):
            value = behavior[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Parametro de fuego invalido: {key}")
        for key in ("base_spread_rate", "spotting_probability", "spotting_min_wind", "spotting_min_alignment"):
            if behavior[key] > 1:
                raise ValueError(f"{key} debe estar en 0..1.")
        if behavior["laboratory_multiplier"] < 1 or type(behavior["spotting_enabled"]) is not bool:
            raise ValueError("Politica de laboratorio/brasas invalida.")
        for key in ("spotting_min_distance", "spotting_max_distance", "spotting_max_per_turn"):
            if type(behavior[key]) is not int or behavior[key] < 1:
                raise ValueError(f"{key} debe ser entero positivo.")
        if not 2 <= behavior["spotting_min_distance"] <= behavior["spotting_max_distance"]:
            raise ValueError("Distancias de brasas invalidas.")
        if len(owners) != len(terrain) or any(len(a) != len(b) for a, b in zip(owners, terrain)):
            raise ValueError("Geometria de edificios incompatible.")
        self.laboratory_cells = frozenset((x, y) for y, row in enumerate(owners)
            for x, name in enumerate(row) if name and properties[name]["laboratory"]
            and properties[name]["flammable_materials"])
        rate = behavior["base_spread_rate"]
        chances = {"building": rate, "grass": rate*behavior["vegetation_multiplier"]}
        super().__init__(terrain, combustible, seed=seed, spread_chances=chances,
                         burn_durations=behavior["burn_durations"])
        # Flujo independiente: activar brasas no altera los sorteos de contacto.
        self.spot_rng = random.Random(int.from_bytes(hashlib.sha256(f"{seed}:embers".encode()).digest(), "big"))
        maximum, minimum = behavior["spotting_max_distance"], behavior["spotting_min_distance"]
        self.spot_offsets = {}
        for direction, (wx, wy) in WIND_VECTORS.items():
            self.spot_offsets[direction] = tuple((dx, dy)
                for dy in range(-maximum, maximum+1) for dx in range(-maximum, maximum+1)
                if minimum <= math.hypot(dx, dy) <= maximum
                and dx*wx+dy*wy >= behavior["spotting_min_alignment"]*math.hypot(dx, dy))
        self.spotting_events = []
        self.last_spots = []

    @classmethod
    def from_scenario(cls, path, *, behavior, owners, properties, seed=2026):
        base = WindFireSimulation.from_campus_json(path, seed=seed)
        return cls(base.terrain, base.combustible, behavior=behavior,
                   owners=owners, properties=properties, seed=seed)

    def spread_probability(self, source, destination, wind):
        dx, dy = destination[0]-source[0], destination[1]-source[1]
        wx, wy = wind.vector
        probability = self.spread_chances[self.terrain[destination[1]][destination[0]]]
        if source in self.laboratory_cells or destination in self.laboratory_cells:
            probability *= self.behavior["laboratory_multiplier"]
        probability *= 1+self.behavior["wind_multiplier"]*wind.intensity*(dx*wx+dy*wy)
        return max(0.0, min(1.0, probability))

    def step(self):
        sources = sorted(self.burning)
        result = super().step()
        self.last_spots = []
        wind = getattr(self, "wind", Wind())
        cfg = self.behavior
        if cfg["spotting_enabled"] and wind.intensity > 0 and wind.intensity >= cfg["spotting_min_wind"]:
            # A lo sumo una propuesta por foco anterior y cupo global de igniciones.
            for x, y in sources:
                if len(self.last_spots) >= cfg["spotting_max_per_turn"]:
                    break
                if self.spot_rng.random() >= cfg["spotting_probability"]*wind.intensity:
                    continue
                dx, dy = self.spot_rng.choice(self.spot_offsets[wind.direction])
                target = (x+dx, y+dy)
                if self.can_ignite(*target):
                    self.ignite(*target)
                    event = {"turn": self.turn, "source": (x, y), "target": target,
                             "direction": wind.direction, "intensity": wind.intensity}
                    self.last_spots.append(event)
                    self.spotting_events.append(event)
        result.update(new_fires=result["new_fires"]+len(self.last_spots),
                      burning=len(self.burning), total_ignitions=self.total_ignitions,
                      secondary_foci=len(self.spotting_events))
        return result

    def stats(self):
        return {**super().stats(), "secondary_foci": len(self.spotting_events)}
