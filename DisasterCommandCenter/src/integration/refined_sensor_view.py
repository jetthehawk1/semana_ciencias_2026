"""Proyeccion explicita grid fino -> contrato de sensores fuente, sin IA."""
from __future__ import annotations

from types import SimpleNamespace


def source_sensor_environment(environment, source_terrain, scale):
    """Maximo de humo por bloque; fuego presente si arde alguna subcelda.

    Las coordenadas y la distancia del target siguen en celdas fuente.
    No se mezclan coordenadas finas con el contrato 160x100.
    """
    height, width = len(source_terrain), len(source_terrain[0])
    smoke = environment.smoke.concentrations
    concentrations = [[max(smoke[y*scale+dy][x*scale+dx]
                           for dy in range(scale) for dx in range(scale))
                       for x in range(width)] for y in range(height)]
    fire = SimpleNamespace(width=width, height=height, turn=environment.fire.turn,
                           terrain=source_terrain,
                           burning={(x//scale, y//scale) for x, y in environment.fire.burning})
    return SimpleNamespace(fire=fire, smoke=SimpleNamespace(
        width=width, height=height, turn=environment.smoke.turn, concentrations=concentrations))
