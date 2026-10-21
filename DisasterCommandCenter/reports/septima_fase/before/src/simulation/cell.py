
from dataclasses import dataclass


@dataclass
class Cell:
    """Representa una celda del campus en la simulación."""

    x: int
    y: int
    terrain_type: str = "floor"
    walkable: bool = True
    occupant_id: str | None = None
    fire_level: float = 0.0
    smoke_level: float = 0.0
    temperature: float = 25.0

    def __post_init__(self):
        if self.x < 0 or self.y < 0:
            raise ValueError("Las coordenadas no pueden ser negativas.")

        if not 0.0 <= self.fire_level <= 1.0:
            raise ValueError("fire_level debe estar entre 0 y 1.")

        if not 0.0 <= self.smoke_level <= 1.0:
            raise ValueError("smoke_level debe estar entre 0 y 1.")

    def is_occupied(self) -> bool:
        """Indica si hay una persona en esta celda."""
        return self.occupant_id is not None
