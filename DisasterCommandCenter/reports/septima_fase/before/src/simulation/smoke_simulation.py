"""Disaster Command Center — Paso 10: humo en una cuadricula.

Modelo educativo, no calibrado. No considera viento, altura, ventilacion,
muros interiores, toxicidad ni efectos sobre las personas.
El humo, a diferencia del fuego, puede ocupar calles y pisos.

Este modulo NO modifica FireSimulation ni la cuadricula del campus.
"""
from __future__ import annotations

import math

CARDINAL = ((0, -1), (1, 0), (0, 1), (-1, 0))


class SmokeSimulation:
    """Dispersa concentraciones normalizadas [0, 1] por turnos.

    Cada turno:
      1. El humo anterior se difunde a vecinos cardinales en forma simultanea.
      2. Parte del humo se disipa.
      3. Cada foco de fuego activo al inicio del turno produce humo nuevo.

    Llamar smoke.step(fire.burning) ANTES de fire.step() para que los dos
    motores compartan la misma linea temporal. Las concentraciones NO son
    unidades fisicas de exposicion.
    """

    def __init__(self, width: int, height: int, *, emission_rate: float = 0.62,
                 diffusion_rate: float = 0.30, decay_rate: float = 0.08,
                 max_concentration: float = 1.0, epsilon: float = 0.0001):
        if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
            raise ValueError('Las dimensiones del mapa deben ser enteros positivos.')
        for name, value, lo, hi, include_zero in (
            ('emission_rate', emission_rate, 0, 1, False),
            ('diffusion_rate', diffusion_rate, 0, 1, True),
            ('decay_rate', decay_rate, 0, 1, True),
        ):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not (lo <= value <= hi)
                    or (not include_zero and value == 0)):
                raise ValueError(f'{name} debe estar entre {lo} y {hi}' +
                                 (', mayor que cero' if not include_zero else ''))
        if (isinstance(max_concentration, bool) or
                not isinstance(max_concentration, (int, float)) or
                not math.isfinite(max_concentration) or max_concentration <= 0):
            raise ValueError('max_concentration debe ser positiva y finita.')
        if (isinstance(epsilon, bool) or not isinstance(epsilon, (int, float))
                or not math.isfinite(epsilon) or epsilon < 0
                or epsilon >= max_concentration):
            raise ValueError('epsilon debe ser no negativa y menor al maximo.')

        self.width = width
        self.height = height
        self.emission_rate = float(emission_rate)
        self.diffusion_rate = float(diffusion_rate)
        self.decay_rate = float(decay_rate)
        self.max_concentration = float(max_concentration)
        self.epsilon = float(epsilon)
        self.concentrations = [[0.0] * width for _ in range(height)]
        self.turn = 0

    def in_bounds(self, x: int, y: int) -> bool:
        return (type(x) is int and type(y) is int and
                0 <= x < self.width and 0 <= y < self.height)

    def concentration_at(self, x: int, y: int) -> float:
        if not self.in_bounds(x, y):
            raise ValueError('Coordenadas de humo fuera de la cuadricula.')
        return self.concentrations[y][x]

    def reset(self) -> None:
        """Limpia solo el humo; no toca el incendio ni el terreno."""
        self.concentrations = [[0.0] * self.width for _ in range(self.height)]
        self.turn = 0

    def step(self, burning_cells=()) -> dict:
        """Avanza un turno usando las celdas que ardian al INICIO del turno.

        burning_cells puede ser fire.burning (dict), fire.burning.keys(),
        o cualquier iterable de tuplas (x, y). No modifica ese iterable.
        """
        try:
            sources = set(burning_cells)
        except (TypeError, ValueError) as exc:
            raise ValueError('Los focos de fuego deben ser coordenadas (x, y).') from exc
        for point in sources:
            if (not isinstance(point, tuple) or len(point) != 2 or
                    not self.in_bounds(*point)):
                raise ValueError(f'Foco de fuego fuera del mapa o invalido: {point!r}')

        nxt = [[0.0] * self.width for _ in range(self.height)]
        for y, row in enumerate(self.concentrations):
            for x, value in enumerate(row):
                if value <= 0:
                    continue
                adjacent = [
                    (x + dx, y + dy) for dx, dy in CARDINAL
                    if 0 <= x + dx < self.width and 0 <= y + dy < self.height
                ]
                leaving = value * self.diffusion_rate if adjacent else 0.0
                nxt[y][x] += value - leaving
                if adjacent:
                    portion = leaving / len(adjacent)
                    for nx, ny in adjacent:
                        nxt[ny][nx] += portion

        remaining = 1 - self.decay_rate
        total = 0.0
        smoky_cells = 0
        peak = 0.0
        for y in range(self.height):
            for x in range(self.width):
                concentration = nxt[y][x] * remaining
                if (x, y) in sources:
                    concentration += self.emission_rate
                concentration = min(self.max_concentration, concentration)
                if concentration < self.epsilon:
                    concentration = 0.0
                nxt[y][x] = concentration
                total += concentration
                if concentration >= 0.05:
                    smoky_cells += 1
                peak = max(peak, concentration)

        self.concentrations = nxt
        self.turn += 1
        return {
            'turn': self.turn,
            'smoky_cells': smoky_cells,
            'max_concentration': round(peak, 4),
            'total_concentration': round(total, 4),
            'emitting_fires': len(sources),
        }

    def stats(self) -> dict:
        values = (c for row in self.concentrations for c in row)
        total = 0.0
        smoky_cells = 0
        peak = 0.0
        for c in values:
            total += c
            peak = max(peak, c)
            if c >= 0.05:
                smoky_cells += 1
        return {
            'turn': self.turn,
            'smoky_cells': smoky_cells,
            'max_concentration': round(peak, 4),
            'total_concentration': round(total, 4),
        }


class FireSmokeSimulation:
    """Control minimo que mantiene fuego y humo sincronizados por turno."""

    def __init__(self, fire, **smoke_options):
        # Import interno para no exigir Pygame ni afectar fire_simulation.py.
        from simulation.fire_simulation import FireSimulation
        if not isinstance(fire, FireSimulation):
            raise ValueError('Se requiere una instancia de FireSimulation.')
        self.fire = fire
        self.smoke = SmokeSimulation(fire.width, fire.height, **smoke_options)

    @classmethod
    def from_campus_json(cls, filename, *, seed=2026, **smoke_options):
        from simulation.fire_simulation import FireSimulation
        fire = FireSimulation.from_campus_json(filename, seed=seed)
        return cls(fire, **smoke_options)

    def ignite(self, x: int, y: int) -> None:
        self.fire.ignite(x, y)

    def step(self) -> dict:
        # Humo generado por focos ya activos; nuevos focos emiten al turno siguiente.
        smoke_info = self.smoke.step(self.fire.burning)
        fire_info = self.fire.step()
        return {'turn': fire_info['turn'], 'fire': fire_info, 'smoke': smoke_info}

    def stats(self) -> dict:
        return {'fire': self.fire.stats(), 'smoke': self.smoke.stats()}
