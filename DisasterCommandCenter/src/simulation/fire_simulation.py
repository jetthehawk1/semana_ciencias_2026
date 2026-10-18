"""Disaster Command Center — Paso 9: incendio celular basico.

Independiente de Pygame, personas, IA y rutas.
Modelo educativo por turnos: no reproduce incendios fisicos reales.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

NEIGHBORS_4 = ((0, -1), (1, 0), (0, 1), (-1, 0))
VALID_TERRAINS = frozenset({'building', 'grass', 'floor', 'road'})
SPREAD_CHANCES = {'building': 0.57, 'grass': 0.34}
BURN_DURATIONS = {'building': 7, 'grass': 4}  # turnos enteros


class FireSimulation:
    """Simula ignicion, propagacion y agotamiento en celdas combustibles."""

    def __init__(self, terrain, combustible=None, *, seed=2026,
                 spread_chances=None, burn_durations=None):
        if not terrain or not isinstance(terrain, (list, tuple)) or not terrain[0]:
            raise ValueError('La matriz de terreno no puede estar vacia.')
        if any(len(row) != len(terrain[0]) for row in terrain):
            raise ValueError('Las filas deben tener el mismo ancho.')
        if any(t not in VALID_TERRAINS for row in terrain for t in row):
            raise ValueError('El mapa contiene tipos de terreno desconocidos.')
        self.height = len(terrain)
        self.width = len(terrain[0])
        self.terrain = tuple(tuple(row) for row in terrain)
        if combustible is None:
            combustible = [[t in SPREAD_CHANCES for t in row] for row in terrain]
        if (len(combustible) != self.height or
                any(len(row) != self.width for row in combustible)):
            raise ValueError('La mascara combustible debe tener las mismas dimensiones.')
        self.combustible = tuple(tuple(bool(c) for c in row) for row in combustible)
        if any(self.combustible[y][x] and self.terrain[y][x] not in SPREAD_CHANCES
               for y in range(self.height) for x in range(self.width)):
            raise ValueError('Una calle o piso no puede marcarse como combustible en este modelo.')
        self.spread_chances = dict(SPREAD_CHANCES if spread_chances is None else spread_chances)
        self.burn_durations = dict(BURN_DURATIONS if burn_durations is None else burn_durations)
        for terrain_name in ('building', 'grass'):
            chance = self.spread_chances.get(terrain_name)
            duration = self.burn_durations.get(terrain_name)
            if (isinstance(chance, bool) or not isinstance(chance, (int, float))
                    or not math.isfinite(chance) or not 0 <= chance <= 1):
                raise ValueError('La probabilidad debe estar entre 0 y 1.')
            if type(duration) is not int or duration < 1:
                raise ValueError('La duracion de combustion debe ser un entero positivo.')
        self.rng = random.Random(seed)
        self.turn = 0
        self.burning: dict[tuple[int, int], int] = {}  # (x,y) -> turnos transcurridos
        self.burned: set[tuple[int, int]] = set()
        self.total_ignitions = 0

    @classmethod
    def from_campus_json(cls, filename: str | Path, *, seed=2026,
                         spread_chances=None, burn_durations=None):
        """Reconstruye el terreno del campus aplicando zonas en el orden del JSON.

        El 'grass' por defecto, fuera de zonas explicitas, NO se considera
        combustible: el plano no distingue jardines del terreno fuera del recinto.
        """
        with Path(filename).open('r', encoding='utf-8') as source:
            data = json.load(source)
        w, h = data['width'], data['height']
        if type(w) is not int or type(h) is not int or w <= 0 or h <= 0:
            raise ValueError('Dimensiones incorrectas del campus.')
        default = data.get('default_terrain', 'grass')
        if default not in VALID_TERRAINS:
            raise ValueError('Terreno por defecto desconocido.')
        terrain = [[default for _ in range(w)] for _ in range(h)]
        combustible = [[False for _ in range(w)] for _ in range(h)]
        for i, zone in enumerate(data['zones']):
            try:
                kind = zone['terrain_type']
                x, y, zw, zh = (zone[k] for k in ('x', 'y', 'width', 'height'))
            except KeyError as exc:
                raise ValueError(f'Falta un campo en zona {i}: {exc}') from exc
            if kind not in VALID_TERRAINS:
                raise ValueError(f'Tipo de terreno desconocido en zona {i}: {kind}')
            if (any(type(v) is not int for v in (x, y, zw, zh)) or
                    x < 0 or y < 0 or zw <= 0 or zh <= 0 or
                    x + zw > w or y + zh > h):
                raise ValueError(f'Zona {i} fuera del mapa o con dimensiones invalidas.')
            for yy in range(y, y + zh):
                terrain[yy][x:x+zw] = [kind] * zw
                combustible[yy][x:x+zw] = [kind in SPREAD_CHANCES] * zw
        return cls(terrain, combustible, seed=seed,
                   spread_chances=spread_chances, burn_durations=burn_durations)

    def in_bounds(self, x: int, y: int) -> bool:
        return (type(x) is int and type(y) is int and
                0 <= x < self.width and 0 <= y < self.height)

    def can_ignite(self, x: int, y: int) -> bool:
        return (self.in_bounds(x, y) and self.combustible[y][x] and
                (x, y) not in self.burning and (x, y) not in self.burned)

    def ignite(self, x: int, y: int) -> None:
        """Enciende una celda valida; si no se puede, lanza ValueError."""
        if not self.in_bounds(x, y):
            raise ValueError('Coordenadas fuera del campus o no enteras.')
        if not self.combustible[y][x]:
            raise ValueError('Esta celda no tiene combustible en el modelo.')
        if (x, y) in self.burning or (x, y) in self.burned:
            raise ValueError('Esta celda ya arde o se consumio.')
        self.burning[(x, y)] = 0
        self.total_ignitions += 1

    def state_at(self, x: int, y: int) -> str:
        if not self.in_bounds(x, y):
            raise ValueError('Coordenadas fuera del campus.')
        if (x, y) in self.burning:
            return 'burning'
        if (x, y) in self.burned:
            return 'burned'
        return 'unburned'

    def step(self) -> dict:
        """Avanza UN turno.

        Solo las celdas que ardian al INICIO del turno pueden propagar.
        Los focos nuevos comenzaran a propagar en el siguiente turno.
        """
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
                if self.rng.random() < self.spread_chances[self.terrain[ny][nx]]:
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

    def stats(self) -> dict:
        return {
            'turn': self.turn,
            'burning': len(self.burning),
            'burned': len(self.burned),
            'total_ignitions': self.total_ignitions,
        }
