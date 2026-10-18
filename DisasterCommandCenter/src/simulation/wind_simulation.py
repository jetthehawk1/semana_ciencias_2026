"""Disaster Command Center — Paso 11: viento aplicado al fuego y al humo.

Modelo DIDACTICO por turnos. Intensidad 0..1 sin unidades fisicas.
N significa que el viento SOPLA HACIA el norte (x igual, y disminuye).
No incorpora topografia, edificios como barreras de humo, clima real ni toxicidad.
No modifica FireSimulation / SmokeSimulation del Paso 9/10.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from simulation.fire_simulation import FireSimulation, NEIGHBORS_4
from simulation.smoke_simulation import SmokeSimulation

# x positivo hacia la derecha; y positivo hacia abajo.
# Valores diagonales normalizados para proyecciones correctas.
INV_SQRT2 = 1 / math.sqrt(2)
WIND_VECTORS = {
    'N': (0, -1), 'NE': (INV_SQRT2, -INV_SQRT2),
    'E': (1, 0), 'SE': (INV_SQRT2, INV_SQRT2),
    'S': (0, 1), 'SW': (-INV_SQRT2, INV_SQRT2),
    'W': (-1, 0), 'NW': (-INV_SQRT2, -INV_SQRT2),
}
WIND_STEPS = {
    'N': (0, -1), 'NE': (1, -1), 'E': (1, 0),
    'SE': (1, 1), 'S': (0, 1), 'SW': (-1, 1),
    'W': (-1, 0), 'NW': (-1, -1),
}


@dataclass(frozen=True)
class Wind:
    direction: str = 'E'
    intensity: float = 0.0

    def __post_init__(self):
        if not isinstance(self.direction, str) or self.direction not in WIND_VECTORS:
            raise ValueError('Direccion de viento invalida: use N, NE, E, SE, S, SW, W o NW.')
        if (isinstance(self.intensity, bool) or
                not isinstance(self.intensity, (int, float)) or
                not math.isfinite(self.intensity) or
                not 0 <= self.intensity <= 1):
            raise ValueError('La intensidad del viento debe estar entre 0 y 1.')

    @property
    def vector(self):
        return WIND_VECTORS[self.direction]

    @property
    def step_vector(self):
        return WIND_STEPS[self.direction]


class WindFireSimulation(FireSimulation):
    """FireSimulation con sesgo por viento durante la ignicion de vecinos."""

    def set_wind(self, wind: Wind):
        if not isinstance(wind, Wind):
            raise ValueError('Se requiere un objeto Wind.')
        self.wind = wind

    def step(self) -> dict:
        wind = getattr(self, 'wind', Wind())
        wx, wy = wind.vector
        old_fires = sorted(self.burning)
        new_fires = set()
        for x, y in old_fires:
            for dx, dy in NEIGHBORS_4:
                nx, ny = x + dx, y + dy
                point = (nx, ny)
                if (not self.in_bounds(nx, ny) or not self.combustible[ny][nx]
                        or point in self.burning or point in self.burned
                        or point in new_fires):
                    continue
                base_probability = self.spread_chances[self.terrain[ny][nx]]
                # A favor: aumenta; contra: disminuye. La calma conserva el Paso 9.
                alignment = dx * wx + dy * wy
                probability = max(0.0, min(1.0, base_probability * (
                    1 + 1.2 * wind.intensity * alignment)))
                if self.rng.random() < probability:
                    new_fires.add(point)

        exhausted = set()
        for point in old_fires:
            age = self.burning[point] + 1
            x, y = point
            if age >= self.burn_durations[self.terrain[y][x]]:
                exhausted.add(point)
            else:
                self.burning[point] = age
        for point in exhausted:
            del self.burning[point]
        self.burned.update(exhausted)
        for point in sorted(new_fires):
            self.burning[point] = 0
        self.total_ignitions += len(new_fires)
        self.turn += 1
        return {
            'turn': self.turn,
            'new_fires': len(new_fires),
            'exhausted': len(exhausted),
            'burning': len(self.burning),
            'burned': len(self.burned),
            'total_ignitions': self.total_ignitions,
        }


class WindSmokeSimulation(SmokeSimulation):
    """Humo con difusion cardinal + transporte hacia el viento.

    En el limite del mapa, la fraccion advectiva queda en la celda de origen:
    no se crea ni se pierde humo artificialmente antes de disipacion/saturacion.
    """

    def __init__(self, width, height, *, advection_rate=0.75, **options):
        super().__init__(width, height, **options)
        if (isinstance(advection_rate, bool) or
                not isinstance(advection_rate, (int, float)) or
                not math.isfinite(advection_rate) or
                not 0 <= advection_rate <= 1):
            raise ValueError('advection_rate debe estar entre 0 y 1.')
        self.advection_rate = float(advection_rate)
        self.wind = Wind()

    def set_wind(self, wind: Wind):
        if not isinstance(wind, Wind):
            raise ValueError('Se requiere un objeto Wind.')
        self.wind = wind

    def step(self, burning_cells=()) -> dict:
        if self.wind.intensity == 0 or self.advection_rate == 0:
            return super().step(burning_cells)

        try:
            sources = set(burning_cells)
        except (TypeError, ValueError) as exc:
            raise ValueError('Los focos deben ser coordenadas (x,y).') from exc
        for point in sources:
            if not isinstance(point, tuple) or len(point) != 2 or not self.in_bounds(*point):
                raise ValueError(f'Foco de fuego invalido: {point!r}')

        fraction = self.wind.intensity * self.advection_rate
        dx, dy = self.wind.step_vector
        nxt = [[0.0] * self.width for _ in range(self.height)]
        for y, row in enumerate(self.concentrations):
            for x, amount in enumerate(row):
                if amount <= 0:
                    continue
                remaining = amount * (1 - fraction)
                moved = amount * fraction
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    nxt[ny][nx] += moved
                else:
                    remaining += moved
                neighbors = [(x + vx, y + vy) for vx, vy in NEIGHBORS_4
                             if 0 <= x + vx < self.width and 0 <= y + vy < self.height]
                spreading = remaining * self.diffusion_rate if neighbors else 0.0
                nxt[y][x] += remaining - spreading
                if neighbors:
                    portion = spreading / len(neighbors)
                    for ax, ay in neighbors:
                        nxt[ay][ax] += portion

        total = 0.0
        peak = 0.0
        smoky_cells = 0
        for y in range(self.height):
            for x in range(self.width):
                amount = nxt[y][x] * (1 - self.decay_rate)
                if (x, y) in sources:
                    amount += self.emission_rate
                amount = min(self.max_concentration, amount)
                if amount < self.epsilon:
                    amount = 0.0
                nxt[y][x] = amount
                peak = max(peak, amount)
                total += amount
                if amount >= 0.05:
                    smoky_cells += 1

        self.concentrations = nxt
        self.turn += 1
        return {
            'turn': self.turn,
            'smoky_cells': smoky_cells,
            'max_concentration': round(peak, 4),
            'total_concentration': round(total, 4),
            'emitting_fires': len(sources),
        }


class WindFireSmokeSimulation:
    """Coordina fuego y humo con un viento compartido que se puede cambiar en vivo."""

    def __init__(self, fire: WindFireSimulation, *, direction='E', intensity=0.0,
                 advection_rate=0.75, **smoke_options):
        if not isinstance(fire, WindFireSimulation):
            raise ValueError('Se necesita WindFireSimulation.')
        self.fire = fire
        self.smoke = WindSmokeSimulation(
            fire.width, fire.height, advection_rate=advection_rate, **smoke_options)
        self.wind = Wind(direction, intensity)
        self.fire.set_wind(self.wind)
        self.smoke.set_wind(self.wind)

    @classmethod
    def from_campus_json(cls, filename, *, seed=2026, direction='E', intensity=0.0,
                         advection_rate=0.75, **smoke_options):
        fire = WindFireSimulation.from_campus_json(filename, seed=seed)
        return cls(fire, direction=direction, intensity=intensity,
                   advection_rate=advection_rate, **smoke_options)

    def set_wind(self, direction: str, intensity: float) -> None:
        wind = Wind(direction, intensity)  # valida antes de modificar estado
        self.fire.set_wind(wind)
        self.smoke.set_wind(wind)
        self.wind = wind

    def ignite(self, x: int, y: int) -> None:
        self.fire.ignite(x, y)

    def step(self) -> dict:
        smoke_stats = self.smoke.step(self.fire.burning)
        fire_stats = self.fire.step()
        return {'turn': fire_stats['turn'], 'wind': {'direction': self.wind.direction,
                'intensity': self.wind.intensity}, 'fire': fire_stats, 'smoke': smoke_stats}

    def stats(self) -> dict:
        return {'wind': {'direction': self.wind.direction,
                        'intensity': self.wind.intensity},
                'fire': self.fire.stats(), 'smoke': self.smoke.stats()}
