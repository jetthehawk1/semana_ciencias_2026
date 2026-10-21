"""Paso 8.9: mover personas hacia accesos EXTERIORES de edificios.

No abre puertas, no permite interiores, no calcula rutas optimizadas de evacuacion.
El BFS de 4 vecinos es provisional y puede reemplazarse por el enrutador de Persona 3.
No necesita Pygame y conserva la validacion de PersonManager.move_person().
"""
from __future__ import annotations

from collections import deque
import json
import math
from pathlib import Path

DIRECTIONS = ((0, -1), (1, 0), (0, 1), (-1, 0))
MAX_STEPS = 6


def load_access_points(map_data: dict, terrain: list[list[str]], entrances_path: str | Path):
    """Valida y devuelve {edificio: (x_exterior, y_exterior)}.

    Las entradas se validan contra las celdas FINALES del mapa, respetando
    el orden de superposicion de las zonas del archivo campus.json.
    """
    path = Path(entrances_path)
    with path.open('r', encoding='utf-8') as file:
        data = json.load(file)
    w, h = map_data['width'], map_data['height']
    if (data.get('width'), data.get('height')) != (w, h):
        raise ValueError('Las dimensiones de building_entrances.json no coinciden.')
    if data.get('map_name') != map_data.get('name'):
        raise ValueError('Los accesos pertenecen a otro mapa del campus.')
    if len(terrain) != h or any(len(row) != w for row in terrain):
        raise ValueError('Matriz de terreno incompatible con campus.json.')

    owners = [[None] * w for _ in range(h)]
    for zone in map_data['zones']:
        name = zone['name'] if zone['terrain_type'] == 'building' else None
        for y in range(zone['y'], zone['y'] + zone['height']):
            owners[y][zone['x']:zone['x'] + zone['width']] = [name] * zone['width']

    buildings = {name for row in owners for name in row if name is not None}
    result = {}
    ids = set()
    exteriors = set()
    for access in data['accesses']:
        name = access['building']
        ix, iy = access['interior_cell']['x'], access['interior_cell']['y']
        ex, ey = access['exterior_cell']['x'], access['exterior_cell']['y']
        if access['id'] in ids or name in result:
            raise ValueError(f'Acceso duplicado: {name}')
        if not all(type(v) is int for v in (ix, iy, ex, ey)):
            raise ValueError(f'Coordenada no entera: {name}')
        if not (0 <= ix < w and 0 <= iy < h and 0 <= ex < w and 0 <= ey < h):
            raise ValueError(f'Acceso fuera del campus: {name}')
        if (owners[iy][ix] != name or terrain[iy][ix] != 'building'
                or terrain[ey][ex] not in {'floor', 'road'}
                or abs(ix - ex) + abs(iy - ey) != 1):
            raise ValueError(f'Acceso mal ubicado: {name}')
        if (ex, ey) in exteriors:
            raise ValueError(f'Acceso exterior compartido: {name}')
        if access.get('status') != 'provisional':
            raise ValueError(f'Acceso no marcado como provisional: {name}')
        ids.add(access['id'])
        exteriors.add((ex, ey))
        result[name] = (ex, ey)
    if result.keys() != buildings:
        raise ValueError('Faltan o sobran edificios en building_entrances.json.')
    return result


def basic_path(start, goal, is_transitable, width: int, height: int):
    """BFS demostrativo, devuelve celdas despues de start, o None si no hay camino.

    No analiza fuego, humo, peligro ni congestion. No sustituye Persona 3.
    La ocupacion se valida AL MOVER por medio de PersonManager.
    """
    start, goal = tuple(start), tuple(goal)
    for x, y in (start, goal):
        if not (0 <= x < width and 0 <= y < height and is_transitable(x, y)):
            return None
    if start == goal:
        return []
    queue = deque([start])
    parent = {start: None}
    while queue:
        x, y = queue.popleft()
        for dx, dy in DIRECTIONS:
            pos = (x + dx, y + dy)
            nx, ny = pos
            if (not (0 <= nx < width and 0 <= ny < height)
                    or pos in parent or not is_transitable(nx, ny)):
                continue
            parent[pos] = (x, y)
            if pos == goal:
                route = []
                current = goal
                while current != start:
                    route.append(current)
                    current = parent[current]
                route.reverse()
                return route
            queue.append(pos)
    return None


class AccessMovementController:
    """Movimiento a objetivos exteriores, con reloj independiente del renderizado."""

    def __init__(self, manager, access_points: dict, person_ids=None, pathfinder=basic_path):
        self.manager = manager
        self.access_points = dict(access_points)
        self.ids = list(person_ids if person_ids is not None else manager.people.keys())
        if not self.ids or len(set(self.ids)) != len(self.ids):
            raise ValueError('Se necesitan IDs de personas unicos.')
        if any(manager.get_person(pid) is None for pid in self.ids):
            raise ValueError('Persona no registrada en PersonManager.')
        if not callable(pathfinder):
            raise ValueError('Se necesita una funcion para buscar caminos.')
        self.pathfinder = pathfinder
        self.paused = False
        self.time_scale = 1.0
        self.total_moves = 0
        self.moves_by_person = {pid: 0 for pid in self.ids}
        self._credit = {pid: 0.0 for pid in self.ids}
        self._targets = {pid: None for pid in self.ids}
        self._routes = {pid: [] for pid in self.ids}
        self._status = {pid: 'sin_destino' for pid in self.ids}
        self._priority = 0

    def target_for(self, pid):
        return self._targets[pid]

    def status_for(self, pid):
        return self._status[pid]

    def route_for(self, pid):
        return list(self._routes[pid])

    def set_target(self, pid: str, building: str):
        if pid not in self._targets:
            raise ValueError(f'Persona no registrada: {pid}')
        if building not in self.access_points:
            raise ValueError(f'Edificio sin acceso registrado: {building}')
        person = self.manager.get_person(pid)
        if person is None:
            raise ValueError(f'Persona ausente: {pid}')
        goal = self.access_points[building]
        route = self.pathfinder(
            person.position, goal, self.manager.is_transitable,
            self.manager.width, self.manager.height,
        )
        if route is None:
            raise ValueError(f'No existe camino exterior hacia {building} desde {person.position}')
        # No cambiar el objetivo si la busqueda falla.
        self._targets[pid] = building
        self._routes[pid] = list(route)
        self._credit[pid] = 0.0
        self._status[pid] = 'en_acceso' if not route else 'en_camino'
        return goal

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def toggle_pause(self):
        self.paused = not self.paused
        return self.paused

    def set_time_scale(self, value):
        if (type(value) is bool or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0.25 <= value <= 4.0):
            raise ValueError('Velocidad global permitida: x0.25 a x4.00.')
        self.time_scale = float(value)

    def _attempt_step(self, pid):
        person = self.manager.get_person(pid)
        goal_name = self._targets[pid]
        if goal_name is None or person.status == 'a_salvo':
            return False
        goal = self.access_points[goal_name]
        if person.position == goal:
            self._routes[pid] = []
            self._status[pid] = 'en_acceso'
            return False
        route = self._routes[pid]
        # Replanificar si se movio manualmente fuera de la ruta durante la pausa.
        if not route or sum(abs(a-b) for a, b in zip(person.position, route[0])) != 1:
            new_route = self.pathfinder(
                person.position, goal, self.manager.is_transitable,
                self.manager.width, self.manager.height,
            )
            if new_route is None:
                self._status[pid] = 'sin_camino'
                return False
            self._routes[pid] = route = list(new_route)
        next_x, next_y = route[0]
        try:
            self.manager.move_person(pid, next_x-person.x, next_y-person.y)
        except ValueError:
            # Otro ocupante puede estar temporalmente en el siguiente paso.
            # Esperar, sin permitir atravesarlo ni teletransportarse.
            self._status[pid] = 'esperando'
            return False
        route.pop(0)
        self._status[pid] = 'en_acceso' if person.position == goal else 'en_camino'
        return True

    def update(self, dt_seconds):
        if (type(dt_seconds) is bool or not isinstance(dt_seconds, (int, float))
                or not math.isfinite(dt_seconds) or dt_seconds < 0):
            raise ValueError('dt_seconds debe ser finito y no negativo.')
        if self.paused or dt_seconds == 0:
            return 0
        for pid in self.ids:
            person = self.manager.get_person(pid)
            if person is None:
                raise ValueError(f'Persona ausente: {pid}')
            if self._targets[pid] is None or person.status == 'a_salvo':
                self._credit[pid] = 0.0
                continue
            if person.position == self.access_points[self._targets[pid]]:
                self._status[pid] = 'en_acceso'
                self._routes[pid] = []
                self._credit[pid] = 0.0
                continue
            if (type(person.speed) is bool or not isinstance(person.speed, (float, int))
                    or not math.isfinite(person.speed) or person.speed <= 0):
                raise ValueError(f'Velocidad invalida: {pid}')
            self._credit[pid] = min(float(MAX_STEPS),
                                    self._credit[pid] + dt_seconds * person.speed * self.time_scale)
        moved = 0
        count = len(self.ids)
        for _ in range(MAX_STEPS):
            pending = False
            for j in range(count):
                pid = self.ids[(self._priority + j) % count]
                if self._credit[pid] + 1e-10 < 1.0:
                    continue
                pending = True
                self._credit[pid] = max(0.0, self._credit[pid] - 1.0)
                if self._attempt_step(pid):
                    self.moves_by_person[pid] += 1
                    moved += 1
            self._priority = (self._priority + 1) % count
            if not pending:
                break
        self.total_moves += moved
        return moved
