
import json
from pathlib import Path

from simulation.grid import Grid


TERRAIN_TYPES = {
    "floor",
    "road",
    "grass",
    "building",
    "wall",
}


class CampusMap:
    """Representa el mapa lógico del campus."""

    def __init__(self, width: int, height: int):
        self.grid = Grid(width, height)
        self.name = "Campus sin nombre"

    @property
    def width(self) -> int:
        return self.grid.width

    @property
    def height(self) -> int:
        return self.grid.height

    def set_terrain(
        self,
        x: int,
        y: int,
        terrain_type: str,
    ) -> None:
        """Asigna el tipo de terreno a una celda."""

        if terrain_type not in TERRAIN_TYPES:
            raise ValueError(
                f"Tipo de terreno desconocido: {terrain_type}"
            )

        cell = self.grid.get_cell(x, y)
        cell.terrain_type = terrain_type

        cell.walkable = terrain_type in {
            "floor",
            "road",
            "grass",
        }

    def get_cell(self, x: int, y: int):
        """Devuelve la celda indicada."""
        return self.grid.get_cell(x, y)

    def is_walkable(self, x: int, y: int) -> bool:
        """Indica si una celda permite el paso."""
        return self.get_cell(x, y).walkable

    def fill_terrain(self, terrain_type: str) -> None:
        """Llena todo el mapa con un terreno."""

        if terrain_type not in TERRAIN_TYPES:
            raise ValueError(
                f"Tipo de terreno desconocido: {terrain_type}"
            )

        for y in range(self.height):
            for x in range(self.width):
                self.set_terrain(x, y, terrain_type)

    def add_rectangle(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        terrain_type: str,
    ) -> None:
        """Coloca un terreno rectangular en el mapa."""

        values = (x, y, width, height)

        if any(
            type(value) is not int for value in values
        ):
            raise ValueError(
                "Las coordenadas y dimensiones deben ser enteras."
            )

        if width <= 0 or height <= 0:
            raise ValueError(
                "El rectángulo debe tener dimensiones positivas."
            )

        if (
            x < 0
            or y < 0
            or x + width > self.width
            or y + height > self.height
        ):
            raise ValueError(
                "El rectángulo está fuera del mapa."
            )

        if terrain_type not in TERRAIN_TYPES:
            raise ValueError(
                f"Tipo de terreno desconocido: {terrain_type}"
            )

        for row in range(y, y + height):
            for col in range(x, x + width):
                self.set_terrain(
                    col,
                    row,
                    terrain_type,
                )

    @classmethod
    def from_json(cls, file_path):
        """Construye un CampusMap desde un archivo JSON."""

        path = Path(file_path)

        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(
                "El JSON debe contener un objeto principal."
            )

        try:
            width = data["width"]
            height = data["height"]
            default_terrain = data["default_terrain"]
            zones = data["zones"]
        except KeyError as error:
            raise ValueError(
                f"Falta un campo obligatorio: {error.args[0]}"
            ) from error

        if (
            type(width) is not int
            or type(height) is not int
        ):
            raise ValueError(
                "Las dimensiones del mapa deben ser enteras."
            )

        if not isinstance(zones, list):
            raise ValueError(
                "El campo zones debe ser una lista."
            )

        if default_terrain not in TERRAIN_TYPES:
            raise ValueError(
                "Terreno inicial no permitido."
            )

        campus = cls(width, height)
        campus.name = data.get(
            "name",
            "Campus sin nombre",
        )
        campus.fill_terrain(default_terrain)

        for index, zone in enumerate(zones):
            if not isinstance(zone, dict):
                raise ValueError(
                    f"La zona {index} debe ser un objeto."
                )

            try:
                campus.add_rectangle(
                    x=zone["x"],
                    y=zone["y"],
                    width=zone["width"],
                    height=zone["height"],
                    terrain_type=zone["terrain_type"],
                )
            except KeyError as error:
                raise ValueError(
                    f"Falta el campo {error.args[0]} "
                    f"en la zona {index}."
                ) from error

        return campus
