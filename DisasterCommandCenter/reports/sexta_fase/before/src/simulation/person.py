
from dataclasses import dataclass
from typing import ClassVar
import math


@dataclass
class Person:
    person_id: str
    x: int
    y: int
    status: str = "normal"
    speed: float = 1.0
    building_id: str | None = None

    VALID_STATUSES: ClassVar[set[str]] = {
        "normal",
        "evacuando",
        "a_salvo",
    }

    def __post_init__(self):
        # Validar identificador
        if not isinstance(self.person_id, str) or not self.person_id.strip():
            raise ValueError("La persona necesita un ID válido.")

        # Validar coordenadas
        if (
            type(self.x) is not int
            or type(self.y) is not int
            or self.x < 0
            or self.y < 0
        ):
            raise ValueError("Las coordenadas deben ser enteros no negativos.")

        # Validar velocidad
        if (
            isinstance(self.speed, bool)
            or not isinstance(self.speed, (int, float))
            or not math.isfinite(self.speed)
            or self.speed <= 0
        ):
            raise ValueError("La velocidad debe ser positiva y finita.")

        # Validar estado
        if (
            not isinstance(self.status, str)
            or self.status not in self.VALID_STATUSES
        ):
            raise ValueError("Estado de persona no válido.")

        # Validar edificio
        if self.building_id is not None:
            if (
                not isinstance(self.building_id, str)
                or not self.building_id.strip()
            ):
                raise ValueError("ID de edificio no válido.")

    @property
    def position(self):
        return (self.x, self.y)

    def change_status(self, new_status):
        if (
            not isinstance(new_status, str)
            or new_status not in self.VALID_STATUSES
        ):
            raise ValueError("Estado de persona no válido.")

        self.status = new_status
