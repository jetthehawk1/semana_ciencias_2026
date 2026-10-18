
from collections.abc import Callable

from simulation.person import Person


class PersonManager:
    def __init__(
        self,
        width: int,
        height: int,
        is_transitable: Callable[[int, int], bool],
    ):
        if width <= 0 or height <= 0:
            raise ValueError("Dimensiones de mapa invalidas.")

        if not callable(is_transitable):
            raise ValueError("Se necesita una funcion de transitabilidad.")

        self.width = width
        self.height = height
        self.is_transitable = is_transitable
        self.people: dict[str, Person] = {}

    def add_person(self, person: Person):
        if not isinstance(person, Person):
            raise ValueError("Se necesita un objeto Person.")

        if person.person_id in self.people:
            raise ValueError("Ya existe una persona con ese ID.")

        x, y = person.position

        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError("Persona fuera del campus.")

        # En esta etapa solo se permiten ubicaciones exteriores.
        if person.building_id is not None:
            raise ValueError(
                "La colocacion dentro de edificios aun no esta habilitada."
            )

        if not self.is_transitable(x, y):
            raise ValueError("La celda no es transitable.")

        for existing in self.people.values():
            if existing.position == (x, y):
                raise ValueError("La celda ya esta ocupada.")

        self.people[person.person_id] = person

    def get_person(self, person_id: str):
        return self.people.get(person_id)

    def remove_person(self, person_id: str):
        if person_id not in self.people:
            raise ValueError("La persona no existe.")

        del self.people[person_id]

    def list_people(self):
        return list(self.people.values())

    def count(self):
        return len(self.people)


    def move_person(self, person_id: str, dx: int, dy: int) -> tuple[int, int]:
        # Comprobar que la persona existe.
        if not isinstance(person_id, str) or person_id not in self.people:
            raise ValueError("La persona no existe.")

        # Comprobar que el movimiento es valido.
        if type(dx) is not int or type(dy) is not int:
            raise ValueError("El desplazamiento debe ser entero.")

        if abs(dx) + abs(dy) != 1:
            raise ValueError(
                "Solo se permite un paso horizontal o vertical."
            )

        person = self.people[person_id]

        new_x = person.x + dx
        new_y = person.y + dy

        # Impedir que salga del mapa.
        if not (0 <= new_x < self.width and 0 <= new_y < self.height):
            raise ValueError("Movimiento fuera del campus.")

        # Impedir que atraviese edificios u otros obstaculos.
        if not self.is_transitable(new_x, new_y):
            raise ValueError("La celda de destino no es transitable.")

        # Evitar colisiones con otras personas.
        for other_id, other in self.people.items():
            if other_id != person_id:
                if other.position == (new_x, new_y):
                    raise ValueError("La celda de destino esta ocupada.")

        # Actualizar la posicion solo si el movimiento es valido.
        person.x = new_x
        person.y = new_y

        return person.position
