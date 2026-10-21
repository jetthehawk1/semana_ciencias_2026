"""Paso 8.12: salida desde interiores hasta accesos autorizados del campus.

Modelo discreto didactico. No modifica IndoorPersonManager: su move_person()
continua bloqueando el movimiento interior; solo ESTE controlador tiene permiso
para mover una persona dentro de SU edificio y cruzar la puerta registrada.

- 4 vecinos sin diagonales.
- Un ocupante por celda, tanto dentro como fuera.
- BFS precalculado por edificio hasta la puerta interior (sin riesgos).
- Las personas ya fuera despejan la puerta moviendose por suelo exterior.
- Cruzar la puerta NO significa 'a_salvo' (la zona segura es posterior).
"""
from __future__ import annotations

from collections import deque, defaultdict
import json
from pathlib import Path

from simulation.indoor_people import IndoorPersonManager

CARDINAL = ((0, -1), (1, 0), (0, 1), (-1, 0))


def _distance_field(starts, predicate):
    """Distancias enteras BFS en coordenadas enteras de la cuadrícula."""
    distances = {cell: 0 for cell in starts}
    queue = deque(sorted(starts))
    while queue:
        x, y = queue.popleft()
        for dx, dy in CARDINAL:
            cell = (x + dx, y + dy)
            if cell not in distances and predicate(*cell):
                distances[cell] = distances[x, y] + 1
                queue.append(cell)
    return distances


class IndoorEvacuationController:
    """Evacuacion interior simplificada con flujo continuo de salida."""

    def __init__(self, manager: IndoorPersonManager, entrances_path: str | Path,
                 *, exterior_distance: int = 40, manage_exterior: bool = True):
        if not isinstance(manager, IndoorPersonManager):
            raise ValueError('Se requiere IndoorPersonManager del Paso 8.10.')
        if type(exterior_distance) is not int or exterior_distance < 2:
            raise ValueError('exterior_distance debe ser entero de al menos 2.')
        self.manager = manager
        self.manage_exterior = manage_exterior
        try:
            data = json.loads(Path(entrances_path).read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError('No se pudo leer building_entrances.json.') from error
        if not isinstance(data, dict) or (data.get('width'), data.get('height')) != (manager.width, manager.height):
            raise ValueError('Los accesos tienen dimensiones distintas al mapa.')
        if not isinstance(data.get('accesses'), list):
            raise ValueError('Falta la lista de accesos.')

        self.doors: dict[str, dict[tuple[int, int], tuple[int, int]]] = defaultdict(dict)
        identifiers = set()
        exterior_door_cells = set()
        for item in data['accesses']:
            try:
                name, aid = item['building'], item['id']
                inside = (item['interior_cell']['x'], item['interior_cell']['y'])
                outside = (item['exterior_cell']['x'], item['exterior_cell']['y'])
            except (KeyError, TypeError) as error:
                raise ValueError('Un acceso tiene campos incompletos.') from error
            if (not isinstance(name, str) or name not in manager.building_ids
                    or not isinstance(aid, str) or not aid or aid in identifiers
                    or any(type(v) is not int for v in inside + outside)
                    or manager.building_at(*inside) != name
                    or not manager.is_transitable(*outside)
                    or abs(inside[0] - outside[0]) + abs(inside[1] - outside[1]) != 1
                    or inside in self.doors[name] or outside in exterior_door_cells):
                raise ValueError(f'Acceso invalido o duplicado: {name!r}.')
            identifiers.add(aid)
            exterior_door_cells.add(outside)
            self.doors[name][inside] = outside
        if set(self.doors) != manager.building_ids:
            raise ValueError('Todos los edificios deben tener al menos una puerta.')
        self.outside_doors = exterior_door_cells
        self.indoor_distance = {
            name: _distance_field(door_map, lambda x, y, n=name: manager.building_at(x, y) == n)
            for name, door_map in self.doors.items()
        }
        self.outdoor_distance = {
            name: _distance_field(set(door_map.values()), manager.is_transitable)
            for name, door_map in self.doors.items()
        } if manage_exterior else {}
        # Solo se controlan personas que INICIAN dentro; las exteriores previas
        # permanecen como obstaculos estaticos en esta demostracion.
        self.ids = tuple(sorted(pid for pid, person in manager.people.items()
                                if person.building_id is not None))
        for pid in self.ids:
            person = manager.people[pid]
            if person.building_id is None:
                continue  # Los exteriores previos son espectadores inmoviles.
            if person.building_id not in self.doors or person.position not in self.indoor_distance[person.building_id]:
                raise ValueError(f'{pid}: interior sin camino a su puerta.')
            if person.status == 'a_salvo':
                raise ValueError(f'{pid}: no se puede evacuar alguien ya a salvo.')
            person.change_status('evacuando')

        self.exterior_distance = exterior_distance
        self.exited: dict[str, str] = {}  # pid -> edificio de origen
        self.paused = False
        self.steps = 0
        self.total_moves = 0
        self.waiting_last_step = 0
        self._priority = 0

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused

    def _occupied(self):
        return {p.position for p in self.manager.people.values()}

    def step(self) -> int:
        """Ejecutar un turno; devuelve el número de pasos de una celda efectuados."""
        if self.paused:
            return 0
        occupied = self._occupied()
        moved = 0
        waiting = 0

        # Primero se despejan las salidas: el que esta MAS lejos de su puerta avanza antes.
        outdoor_ids = sorted(self.exited if self.manage_exterior else (), key=lambda pid: (
            -self.outdoor_distance[self.exited[pid]].get(self.manager.people[pid].position, -1), pid
        ))
        for pid in outdoor_ids:
            person = self.manager.people[pid]
            distance = self.outdoor_distance[self.exited[pid]]
            current = distance.get(person.position)
            if current is None or current >= self.exterior_distance:
                continue
            # Ir alejandose sin atravesar edificios ni puertas de otros edificios.
            candidates = []
            for dx, dy in CARDINAL:
                dest = (person.x + dx, person.y + dy)
                next_distance = distance.get(dest, -1)
                if (dest not in occupied and dest not in self.outside_doors
                        and next_distance > current):
                    candidates.append((dest, next_distance))
            # Desempate determinista: rotar preferencia para repartir la gente.
            candidates.sort(key=lambda v: (-v[1],
                (v[0][0] * 13 + v[0][1] * 7 + self.steps) % 17))
            if candidates:
                dest = candidates[0][0]
                previous = person.position
                # Validacion exterior centralizada en PersonManager.move_person().
                self.manager.move_person(pid, dest[0] - person.x, dest[1] - person.y)
                occupied.remove(previous)
                occupied.add(dest)
                moved += 1

        # Dentro: primero los mas proximos a su puerta (cola de salida).
        indoor_ids = [pid for pid in self.ids if self.manager.people[pid].building_id is not None]
        index_of = {pid: index for index, pid in enumerate(self.ids)}
        indoor_ids.sort(key=lambda pid: (
            self.indoor_distance[self.manager.people[pid].building_id][self.manager.people[pid].position],
            (index_of[pid] - self._priority) % max(1, len(self.ids))
        ))
        for pid in indoor_ids:
            person = self.manager.people[pid]
            name = person.building_id
            current = person.position
            if current in self.doors[name]:
                door_exit = self.doors[name][current]
                if door_exit in occupied:
                    waiting += 1
                    continue
                occupied.remove(current)
                occupied.add(door_exit)
                person.x, person.y = door_exit
                person.building_id = None
                self.exited[pid] = name
                moved += 1
                continue
            distance = self.indoor_distance[name]
            current_distance = distance[current]
            candidates = []
            for dx, dy in CARDINAL:
                dest = (person.x + dx, person.y + dy)
                if dest not in occupied and distance.get(dest, current_distance) < current_distance:
                    candidates.append(dest)
            if not candidates:
                waiting += 1
                continue
            # Todas son adyacentes y en el mismo edificio (por el mapa de distancias).
            next_pos = candidates[(self.steps + self._priority) % len(candidates)]
            occupied.remove(current)
            occupied.add(next_pos)
            person.x, person.y = next_pos
            moved += 1
        self._priority = (self._priority + 1) % max(1, len(self.ids))
        self.steps += 1
        self.total_moves += moved
        self.waiting_last_step = waiting
        return moved

    @property
    def inside_count(self):
        return sum(self.manager.people[pid].building_id is not None for pid in self.ids)

    @property
    def exited_count(self):
        return len(self.exited)

    def summary(self) -> dict:
        return {
            'initial_people': len(self.ids),
            'inside': self.inside_count,
            'outside_after_door': self.exited_count,
            'waiting': self.waiting_last_step,
            'turns': self.steps,
            'moves': self.total_moves,
        }
