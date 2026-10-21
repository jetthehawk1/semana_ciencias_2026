"""Paso 8.10: registro de personas dentro de edificios del campus.

Compatibilidad: no modifica Person ni PersonManager.
- Una persona SIN building_id solo puede estar en floor o road.
- Una persona CON building_id solo puede empezar en una celda building
  que pertenezca exactamente a ese edificio.
- No se permite movimiento interior ni cruzar puertas en este paso;
  se implementara usando los accesos provisionales en el Paso 8.12.
- Al reconstruir las celdas se respeta el orden de zonas de campus.json.
"""

from __future__ import annotations

import json
from pathlib import Path

from simulation.person import Person
from simulation.person_manager import PersonManager


class IndoorPersonManager(PersonManager):
    """Administrador de personas exteriores e interiores en una sola instancia."""

    def __init__(self, map_data: dict):
        if not isinstance(map_data, dict):
            raise ValueError("El mapa debe ser un diccionario JSON.")

        width = map_data.get("width")
        height = map_data.get("height")
        if (type(width) is not int or type(height) is not int
                or width <= 0 or height <= 0):
            raise ValueError("Dimensiones de mapa invalidas.")

        default = map_data.get("default_terrain", "grass")
        if not isinstance(default, str) or not default:
            raise ValueError("Terreno predeterminado invalido.")
        zones = map_data.get("zones")
        if not isinstance(zones, list):
            raise ValueError("El mapa debe contener una lista de zonas.")

        self.terrain = [[default] * width for _ in range(height)]
        self.building_owners = [[None] * width for _ in range(height)]

        # Se utilizan las zonas EFECTIVAS tras aplicar superposiciones.
        for index, zone in enumerate(zones):
            try:
                x, y = zone["x"], zone["y"]
                size_x, size_y = zone["width"], zone["height"]
                kind, name = zone["terrain_type"], zone["name"]
            except (KeyError, TypeError) as error:
                raise ValueError(f"Zona {index} incompleta.") from error

            if (any(type(v) is not int for v in (x, y, size_x, size_y))
                    or x < 0 or y < 0 or size_x <= 0 or size_y <= 0
                    or x + size_x > width or y + size_y > height):
                raise ValueError(f"Zona {index} fuera de los limites del mapa.")
            if not isinstance(kind, str) or not kind:
                raise ValueError(f"Tipo de terreno invalido en zona {index}.")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(f"Nombre de zona invalido en zona {index}.")

            owner = name if kind == "building" else None
            for row in range(y, y + size_y):
                self.terrain[row][x:x + size_x] = [kind] * size_x
                self.building_owners[row][x:x + size_x] = [owner] * size_x

        self.building_ids = frozenset(
            owner
            for row in self.building_owners
            for owner in row
            if owner is not None
        )

        super().__init__(width, height, self._is_exterior_transitable)

    @classmethod
    def from_json(cls, campus_path: str | Path) -> "IndoorPersonManager":
        path = Path(campus_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data)

    def _is_exterior_transitable(self, x: int, y: int) -> bool:
        return (
            type(x) is int and type(y) is int
            and 0 <= x < self.width and 0 <= y < self.height
            and self.terrain[y][x] in {"floor", "road"}
        )

    def building_at(self, x: int, y: int) -> str | None:
        """Devuelve el edificio al que pertenece la celda o None."""
        if (type(x) is not int or type(y) is not int
                or not (0 <= x < self.width and 0 <= y < self.height)):
            return None
        return self.building_owners[y][x]

    def add_person(self, person: Person):
        if not isinstance(person, Person):
            raise ValueError("Se necesita un objeto Person.")

        # Fuera de los edificios se conserva TODA la validacion original.
        if person.building_id is None:
            return super().add_person(person)

        if person.person_id in self.people:
            raise ValueError("Ya existe una persona con ese ID.")
        x, y = person.position
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError("Persona fuera del campus.")
        if self.building_at(x, y) != person.building_id:
            raise ValueError(
                f"La celda {person.position} no pertenece al edificio "
                f"{person.building_id}."
            )
        if any(other.position == person.position for other in self.people.values()):
            raise ValueError("La celda ya esta ocupada.")
        self.people[person.person_id] = person

    def move_person(self, person_id: str, dx: int, dy: int) -> tuple[int, int]:
        person = self.get_person(person_id)
        if person is not None and person.building_id is not None:
            raise ValueError(
                "El movimiento interior y las puertas se habilitaran en el Paso 8.12."
            )
        return super().move_person(person_id, dx, dy)
