"""Paso 13: red de sensores VIRTUALES para Disaster Command Center.

Lecturas sintéticas sobre el estado actual del motor del Paso 11/12.
No cambia el fuego, humo, viento ni personas. Un turno NO equivale a un segundo.
No es instrumentación física ni sirve como alarma real de seguridad.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import random

SCHEMA_VERSION = "1.0"
TERRAIN_WALKABLE = frozenset({"floor", "road"})


@dataclass(frozen=True)
class VirtualSensor:
    sensor_id: str
    x: int
    y: int
    building_id: str | None


class VirtualSensorNetwork:
    """Lee fuego/humo del estado existente de WindFireSmokeSimulation.

    temperature_c = 24 + calor local ficticio (no térmica real).
    smoke_index = concentración adimensional ya calculada por SmokeSimulation.
    La etiqueta fire_within_2_cells es verdad-terreno del simulador (NO
    es una medición ni un dato disponible al sensor físico o a una IA real).
    """

    def __init__(self, environment, campus_path, sensors_path, *,
                 run_id="ensayo_001", seed=2026, temperature_noise=0.0,
                 smoke_noise=0.0, smoke_threshold=0.30,
                 temperature_threshold=55.0):
        for key, val in (("temperature_noise", temperature_noise),
                         ("smoke_noise", smoke_noise)):
            if (isinstance(val, bool) or not isinstance(val, (int, float))
                    or not math.isfinite(val) or val < 0):
                raise ValueError(f"{key} debe ser finito y no negativo.")
        for key, val in (("smoke_threshold", smoke_threshold),
                         ("temperature_threshold", temperature_threshold)):
            if (isinstance(val, bool) or not isinstance(val, (int, float))
                    or not math.isfinite(val) or val <= 0):
                raise ValueError(f"{key} debe ser finito y positivo.")
        if not (0 < smoke_threshold <= 1):
            raise ValueError("smoke_threshold debe estar entre 0 y 1.")
        if not isinstance(run_id, str) or not run_id.strip():
            raise ValueError("run_id debe ser texto no vacío.")
        if len(run_id) > 120:
            raise ValueError("run_id demasiado largo.")
        if type(seed) is not int:
            raise ValueError("seed debe ser entero.")
        if not (hasattr(environment, "fire") and hasattr(environment, "smoke")):
            raise ValueError("Se necesita el ambiente con fuego y humo del Paso 11/12.")
        self.environment = environment
        fire, smoke = environment.fire, environment.smoke
        if (fire.width != smoke.width or fire.height != smoke.height):
            raise ValueError("Fuego y humo tienen dimensiones diferentes.")
        self.width, self.height = fire.width, fire.height
        self.campus_path = Path(campus_path)
        self.sensors_path = Path(sensors_path)
        self.sensors = self._load_sensors()
        self.run_id = run_id
        self.temperature_noise = float(temperature_noise)
        self.smoke_noise = float(smoke_noise)
        self.smoke_threshold = float(smoke_threshold)
        self.temperature_threshold = float(temperature_threshold)
        self.rng = random.Random(seed)
        self.last_turn: int | None = None

    def _load_sensors(self) -> tuple[VirtualSensor, ...]:
        """Valida coordenadas contra la ocupación EFECTIVA del campus."""
        campus = json.loads(self.campus_path.read_text(encoding="utf-8"))
        if (campus.get("width"), campus.get("height")) != (self.width, self.height):
            raise ValueError("El tamaño del campus no coincide con el ambiente.")
        owners = [[None] * self.width for _ in range(self.height)]
        ground = [[campus.get("default_terrain", "grass")] * self.width
                  for _ in range(self.height)]
        for zone in campus["zones"]:
            x, y, w, h = (zone[k] for k in ("x", "y", "width", "height"))
            typ = zone["terrain_type"]
            owner = zone["name"] if typ == "building" else None
            for j in range(y, y + h):
                ground[j][x:x+w] = [typ] * w
                owners[j][x:x+w] = [owner] * w
        config = json.loads(self.sensors_path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or config.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Versión de configuración de sensores no compatible.")
        collection = config.get("sensors")
        if not isinstance(collection, list) or not collection:
            raise ValueError("La lista de sensores debe tener elementos.")
        sensors, ids, positions = [], set(), set()
        for idx, s in enumerate(collection):
            if not isinstance(s, dict):
                raise ValueError(f"Sensor {idx} inválido.")
            try:
                sid, x, y, building = (s[k] for k in
                                       ("sensor_id", "x", "y", "building_id"))
            except KeyError as error:
                raise ValueError(f"Sensor {idx} incompleto: {error}.") from error
            if not isinstance(sid, str) or not sid.strip() or sid != sid.strip():
                raise ValueError(f"sensor_id inválido en sensor {idx}.")
            if sid in ids:
                raise ValueError("ID de sensor repetido.")
            if (type(x) is not int or type(y) is not int or
                    not (0 <= x < self.width and 0 <= y < self.height)):
                raise ValueError(f"Coordenadas inválidas para {sid}.")
            if (x, y) in positions:
                raise ValueError("Dos sensores ocupan la misma celda.")
            if building is not None and (not isinstance(building, str) or not building):
                raise ValueError(f"building_id inválido en {sid}.")
            if building is None:
                if ground[y][x] not in TERRAIN_WALKABLE:
                    raise ValueError(f"Sensor exterior {sid} fuera del área transitable.")
            elif owners[y][x] != building:
                raise ValueError(f"Sensor {sid} no está en su edificio {building}.")
            if ground[y][x] != self.environment.fire.terrain[y][x]:
                raise ValueError(f"El terreno de {sid} no coincide con el motor de fuego.")
            ids.add(sid)
            positions.add((x, y))
            sensors.append(VirtualSensor(sid, x, y, building))
        return tuple(sensors)

    @staticmethod
    def _nearest_distance(burning, x, y) -> int | None:
        """Distancia Manhattan mínima de hasta dos celdas a fuego activo."""
        best = 3
        for bx, by in burning:
            d = abs(bx - x) + abs(by - y)
            if d < best:
                best = d
                if d == 0:
                    break
        return best if best <= 2 else None

    def sample(self) -> list[dict]:
        """Una muestra por sensor y turno; no avanza ni modifica el ambiente."""
        env = self.environment
        tick = env.fire.turn
        if tick != env.smoke.turn:
            raise ValueError("Los motores de fuego y humo no están sincronizados.")
        if self.last_turn is not None and tick <= self.last_turn:
            raise ValueError("Turno repetido o retrocedido: crea una red nueva tras reinicio.")
        burning = tuple(env.fire.burning)
        rows = []
        for s in self.sensors:
            distance = self._nearest_distance(burning, s.x, s.y)
            heat = {0: 85.0, 1: 50.0, 2: 25.0, None: 0.0}[distance]
            temp = 24.0 + heat + self.rng.uniform(
                -self.temperature_noise, self.temperature_noise)
            smoke = env.smoke.concentrations[s.y][s.x] + self.rng.uniform(
                -self.smoke_noise, self.smoke_noise)
            smoke = min(1.0, max(0.0, smoke))
            temp, smoke = round(temp, 3), round(smoke, 5)
            rows.append({
                "schema_version": SCHEMA_VERSION,
                "run_id": self.run_id,
                "turn": tick,
                "sensor_id": s.sensor_id,
                "x": s.x,
                "y": s.y,
                "building_id": s.building_id,
                "temperature_c": temp,
                "smoke_index": smoke,
                "alarm": temp >= self.temperature_threshold
                         or smoke >= self.smoke_threshold,
                "fire_within_2_cells": distance is not None,
            })
        self.last_turn = tick
        return rows
