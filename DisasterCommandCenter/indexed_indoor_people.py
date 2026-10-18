"""Paso 14.3.4B. Administrador EXPERIMENTAL con indice de ocupacion.

No sustituye los archivos originales. Subclase de IndoorPersonManager.
IMPORTANTE: IndoorEvacuationController cambia posiciones interiores directamente.
Tras CADA turno controlado, invocar ``rebuild_index()`` ANTES de usar el
administrador en otro turno o por codigo externo. El banco de pruebas lo hace.
No instalar como sustitucion de produccion sin adaptar el controlador a notificar
TODOS los movimientos, incluidos los interiores y los cruces de puertas.
"""
from __future__ import annotations

from simulation.indoor_people import IndoorPersonManager
from simulation.person import Person


class IndexedIndoorPersonManager(IndoorPersonManager):
    """Ocupacion de celdas en dict[(x,y)] -> id; consulta O(1) promedio.

    Mantiene las mismas reglas publicas de alta, baja y movimiento exterior
    que IndoorPersonManager. No autoriza desplazamientos interiores por si solo.
    """

    def __init__(self, map_data: dict):
        super().__init__(map_data)
        self._by_cell: dict[tuple[int, int], str] = {}

    def add_person(self, person: Person):
        if not isinstance(person, Person):
            raise ValueError("Se necesita un objeto Person.")
        if person.person_id in self.people:
            raise ValueError("Ya existe una persona con ese ID.")
        x, y = person.position
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise ValueError("Persona fuera del campus.")
        if person.building_id is None:
            if not self.is_transitable(x, y):
                raise ValueError("La celda no es transitable.")
        elif self.building_at(x, y) != person.building_id:
            raise ValueError(f"La celda {(x, y)} no pertenece al edificio {person.building_id}.")
        if (x, y) in self._by_cell:
            raise ValueError("La celda ya esta ocupada.")
        self.people[person.person_id] = person
        self._by_cell[x, y] = person.person_id

    def remove_person(self, person_id: str):
        person = self.people.get(person_id)
        if person is None:
            raise ValueError("La persona no existe.")
        pos = person.position
        if self._by_cell.get(pos) != person_id:
            raise RuntimeError("Indice desincronizado antes de eliminar; ejecuta rebuild_index().")
        del self.people[person_id]
        del self._by_cell[pos]

    def move_person(self, person_id: str, dx: int, dy: int) -> tuple[int, int]:
        person = self.people.get(person_id)
        if person is not None and person.building_id is not None:
            raise ValueError("El movimiento interior solo se habilita con el controlador de evacuacion.")
        if not isinstance(person_id, str) or person is None:
            raise ValueError("La persona no existe.")
        if type(dx) is not int or type(dy) is not int or abs(dx) + abs(dy) != 1:
            raise ValueError("Solo se permite un paso horizontal o vertical.")
        old = person.position
        if self._by_cell.get(old) != person_id:
            raise RuntimeError("Indice desincronizado antes de mover; ejecuta rebuild_index().")
        destination = (person.x + dx, person.y + dy)
        if not (0 <= destination[0] < self.width and 0 <= destination[1] < self.height):
            raise ValueError("Movimiento fuera del campus.")
        if not self.is_transitable(*destination):
            raise ValueError("La celda de destino no es transitable.")
        occupant = self._by_cell.get(destination)
        if occupant is not None and occupant != person_id:
            raise ValueError("La celda de destino esta ocupada.")
        # Actualizar ambas estructuras tras pasar TODAS las comprobaciones.
        person.x, person.y = destination
        del self._by_cell[old]
        self._by_cell[destination] = person_id
        return person.position

    def rebuild_index(self) -> None:
        """Sincroniza tras movimientos interiores directos del controlador 8.12.

        Es O(N) por turno: mucho menos que O(N) por movimiento exterior.
        Si hay una colision, no instala un indice parcial.
        """
        fresh: dict[tuple[int, int], str] = {}
        for pid, person in self.people.items():
            pos = person.position
            if pos in fresh:
                raise AssertionError(f"Colision tras turno: {fresh[pos]} y {pid} en {pos}")
            fresh[pos] = pid
        self._by_cell = fresh

    def assert_index_consistent(self) -> None:
        """Solo para pruebas: verifica exhaustivamente el indice actual."""
        expected = {}
        for pid, person in self.people.items():
            pos = person.position
            if pos in expected:
                raise AssertionError(f"Colision de personas: {expected[pos]} y {pid}")
            expected[pos] = pid
        assert self._by_cell == expected, "El indice no corresponde a las posiciones reales"

    def occupied_by(self, x: int, y: int) -> str | None:
        return self._by_cell.get((x, y))
