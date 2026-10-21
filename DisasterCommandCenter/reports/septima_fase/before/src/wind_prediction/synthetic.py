"""Patrones controlados del viento virtual; NO clima observado de Ensenada."""
from __future__ import annotations

import math
import random
from simulation.wind_simulation import Wind


def synthetic_sequences(*, seed=2026, count=48, length=160):
    rng = random.Random(seed)
    directions = ("E", "SE", "S", "SW", "W", "NW", "N", "NE")
    sequences = []
    for i in range(count):
        phase = rng.randrange(8)
        offset = rng.random()*math.tau
        period = rng.choice((24, 32, 40, 48))
        mode = ("persistence", "rotation_speed_ramp", "oscillation", "occasional_changes")[i % 4]
        rows = []
        speed = rng.uniform(.2, .9)
        direction = directions[phase]
        for turn in range(length):
            if mode == "rotation_speed_ramp":
                direction = directions[(phase+turn//12) % 8]
                speed = .55+.3*math.sin(turn/period*math.tau+offset)
            elif mode == "oscillation":
                direction = directions[(phase+round(math.sin(turn/period*math.tau+offset))) % 8]
                speed = .55+.2*math.sin(turn/(period*2)*math.tau+offset)
            elif mode == "occasional_changes" and rng.random() < .04:
                direction = rng.choice(directions); speed = rng.uniform(.2, .9)
            wind = Wind(direction, speed)
            u, v = wind.vector
            rows.append({"turn": turn, "wind_direction": direction, "wind_speed": speed,
                         "u": u*speed, "v": v*speed})
        sequences.append({"sequence_id": f"synthetic-wind-{seed}-{i:03d}",
                          "data_source": "synthetic_simulation", "pattern": mode, "samples": rows})
    return sequences
