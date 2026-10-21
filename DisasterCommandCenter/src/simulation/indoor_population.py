"""Paso 8.11 — Distribucion automatica y validada de personas en edificios.

Trabaja con IndoorPersonManager (Paso 8.10) y los accesos del Paso 8.2.
No cambia el mapa, no habilita movimiento ni abre puertas.
Cada celda interior admite como maximo una persona en este prototipo.
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Mapping

from simulation.indoor_people import IndoorPersonManager
from simulation.person import Person

CARDINAL = ((1, 0), (-1, 0), (0, 1), (0, -1))


class IndoorPopulationDistributor:
    """Coloca personas en celdas conectadas a accesos del mismo edificio."""

    def __init__(self, manager: IndoorPersonManager, entrances_path: str | Path):
        if not isinstance(manager, IndoorPersonManager):
            raise ValueError("Se requiere un IndoorPersonManager.")
        self.manager = manager
        path = Path(entrances_path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"No se pudo leer el archivo de accesos: {path}") from error
        if not isinstance(data, dict) or (data.get("width"), data.get("height")) != (
            manager.width, manager.height
        ):
            raise ValueError("Las dimensiones de los accesos no coinciden con el mapa.")
        if not isinstance(data.get("accesses"), list):
            raise ValueError("El archivo de accesos necesita una lista 'accesses'.")

        door_cells: dict[str, set[tuple[int, int]]] = defaultdict(set)
        for index, item in enumerate(data["accesses"]):
            try:
                building = item["building"]
                interior = item["interior_cell"]
                exterior = item["exterior_cell"]
                inside = (interior["x"], interior["y"])
                outside = (exterior["x"], exterior["y"])
            except (KeyError, TypeError) as error:
                raise ValueError(f"Acceso incompleto en indice {index}.") from error
            if not isinstance(building, str) or building not in manager.building_ids:
                raise ValueError(f"Edificio desconocido en acceso {index}: {building!r}")
            if any(type(v) is not int for v in inside + outside):
                raise ValueError(f"Coordenadas invalidas en acceso {index}.")
            if manager.building_at(*inside) != building:
                raise ValueError(f"El acceso interior de {building} no es de ese edificio.")
            if not manager.is_transitable(*outside):
                raise ValueError(f"El acceso exterior de {building} no es transitable.")
            if abs(inside[0] - outside[0]) + abs(inside[1] - outside[1]) != 1:
                raise ValueError(f"Las celdas del acceso {index} no son vecinas.")
            door_cells[building].add(inside)

        missing = manager.building_ids - door_cells.keys()
        if missing:
            raise ValueError(f"No hay acceso definido para: {', '.join(sorted(missing))}")

        self._cells: dict[str, tuple[tuple[int, int], ...]] = {}
        for building, entrances in door_cells.items():
            visited = set(entrances)
            queue = deque(sorted(entrances))
            while queue:
                x, y = queue.popleft()
                for dx, dy in CARDINAL:
                    point = (x + dx, y + dy)
                    if point not in visited and manager.building_at(*point) == building:
                        visited.add(point)
                        queue.append(point)
            self._cells[building] = tuple(sorted(visited))

    def capacity(self, building: str) -> int:
        """Cantidad de celdas interiores alcanzables desde accesos (no aforo legal)."""
        if building not in self._cells:
            raise ValueError(f"Edificio desconocido: {building!r}")
        return len(self._cells[building])

    def available_cells(self, building: str) -> list[tuple[int, int]]:
        """Celdas libres conectadas a las puertas de este edificio."""
        if building not in self._cells:
            raise ValueError(f"Edificio desconocido: {building!r}")
        occupied = {person.position for person in self.manager.list_people()}
        return [p for p in self._cells[building] if p not in occupied]

    def distribute(
        self,
        building_counts: Mapping[str, int],
        *,
        seed: int = 2026,
        id_prefix: str = "P",
    ) -> list[Person]:
        """Registra personas; si algo falla, conserva las personas ya existentes.

        - Los conteos se validan antes de registrar a nadie.
        - Usa semillas para hacer las ubicaciones reproducibles.
        - Nombra las personas P001, P002... sin repetir IDs existentes.
        """
        if not isinstance(building_counts, Mapping):
            raise ValueError("building_counts debe ser un diccionario de edificio y cantidad.")
        if type(seed) is not int:
            raise ValueError("La semilla debe ser un numero entero.")
        if not isinstance(id_prefix, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", id_prefix):
            raise ValueError("Prefijo de persona invalido.")

        requests = {}
        for building, count in building_counts.items():
            if not isinstance(building, str) or building not in self._cells:
                raise ValueError(f"Edificio inexistente: {building!r}")
            if type(count) is not int or count < 0:
                raise ValueError(f"Cantidad invalida para el edificio {building!r}.")
            requests[building] = count

        # Se revisa toda la solicitud antes de registrar a la primera persona.
        for building, count in requests.items():
            free = len(self.available_cells(building))
            if count > free:
                raise ValueError(
                    f"{building}: se solicitaron {count} personas, pero hay "
                    f"{free} celdas interiores disponibles."
                )

        existing_ids = set(self.manager.people)
        numeric_ids = [int(pid[len(id_prefix):]) for pid in existing_ids
                       if pid.startswith(id_prefix) and pid[len(id_prefix):].isdigit()]
        next_number = max(numeric_ids, default=0) + 1
        rng = random.Random(seed)
        planned: list[Person] = []
        for building in sorted(requests):
            count = requests[building]
            if count == 0:
                continue
            points = rng.sample(self.available_cells(building), count)
            for x, y in points:
                while f"{id_prefix}{next_number:03d}" in existing_ids:
                    next_number += 1
                pid = f"{id_prefix}{next_number:03d}"
                next_number += 1
                existing_ids.add(pid)
                planned.append(Person(pid, x, y, building_id=building))

        # Proteccion extra ante fallos inesperados durante el registro.
        added = []
        try:
            for person in planned:
                self.manager.add_person(person)
                added.append(person.person_id)
        except Exception:
            for pid in reversed(added):
                self.manager.remove_person(pid)
            raise
        return planned


def load_population_config(config_path: str | Path) -> dict:
    """Lee una configuracion de ocupacion ficticia y valida su estructura."""
    path = Path(config_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"No se pudo leer la configuracion: {path}") from error
    if not isinstance(data, dict) or not isinstance(data.get("building_counts"), dict):
        raise ValueError("La configuracion debe incluir building_counts.")
    return data
