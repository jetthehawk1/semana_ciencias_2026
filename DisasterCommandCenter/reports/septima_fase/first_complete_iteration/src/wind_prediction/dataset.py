"""Ventanas causales u/v: division por secuencia, nunca por ventanas aleatorias."""
from __future__ import annotations

from dataclasses import dataclass
import math


def vector_from_degrees(degrees, speed):
    """Angulo matematico del grid: E=0, S=90, W=180, N=270; y hacia abajo."""
    if not all(math.isfinite(v) for v in (degrees, speed)) or not 0 <= speed <= 1:
        raise ValueError("Angulo/velocidad invalido.")
    radians = math.radians(degrees)
    return speed*math.cos(radians), speed*math.sin(radians)


def feature_names(lag_count):
    if type(lag_count) is not int or lag_count < 2:
        raise ValueError("Se requieren al menos dos lags.")
    return tuple(f"{name}_lag{lag}" for lag in range(lag_count-1, -1, -1)
                 for name in ("u", "v", "speed")) + ("delta_u", "delta_v", "delta_speed")


def features(vectors, lag_count):
    feature_names(lag_count)
    if len(vectors) < lag_count:
        raise ValueError("Historial insuficiente.")
    window = vectors[-lag_count:]
    result = [value for u, v in window for value in (u, v, math.hypot(u, v))]
    u, v = window[-1]; pu, pv = window[-2]
    return tuple(result+[u-pu, v-pv, math.hypot(u, v)-math.hypot(pu, pv)])


@dataclass(frozen=True)
class TemporalExample:
    sequence_id: str
    feature_turns: tuple[int, ...]
    target_turn: int
    X: tuple[float, ...]
    y: tuple[float, float]
    persistence: tuple[float, float]


def temporal_examples(sequences, lag_count):
    result = []
    seen = set()
    for sequence in sequences:
        sid = sequence["sequence_id"]
        if sid in seen or sequence["data_source"] != "synthetic_simulation":
            raise ValueError("Secuencia duplicada/origen incompatible.")
        seen.add(sid)
        rows = sequence["samples"]
        turns = [r["turn"] for r in rows]
        if turns != list(range(len(rows))):
            raise ValueError("Cada secuencia debe tener turnos consecutivos desde cero.")
        vectors = [(r["u"], r["v"]) for r in rows]
        if any(not all(math.isfinite(v) for v in uv) or math.hypot(*uv) > 1+1e-9 for uv in vectors):
            raise ValueError("Vector de viento invalido.")
        for target in range(lag_count, len(rows)):
            result.append(TemporalExample(sid, tuple(turns[target-lag_count:target]), turns[target],
                features(vectors[target-lag_count:target], lag_count), vectors[target], vectors[target-1]))
    return result


def split_sequences(sequences, train_fraction=.7, validation_fraction=.15):
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1-train_fraction:
        raise ValueError("Fracciones temporales invalidas.")
    a, b = int(len(sequences)*train_fraction), int(len(sequences)*(train_fraction+validation_fraction))
    if not 0 < a < b < len(sequences):
        raise ValueError("Se requieren secuencias independientes en train/validation/test.")
    return sequences[:a], sequences[a:b], sequences[b:]
