"""Paso 14.1 — Contrato y ejecutor de rutas EXTERNAS (Persona 3 -> Persona 1).

Solo consume y valida rutas. NO calcula rutas ni decide zonas seguras.
Las personas pueden seguir rutas una vez FUERA de los edificios; el cruce
interior/exterior pertenece al controlador del Paso 8.12.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA_VERSION = "1.0"


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} debe ser un texto no vacío.")
    return value


def _position(value, name):
    if not isinstance(value, dict) or set(value) != {"x", "y"}:
        raise ValueError(f"{name} requiere exactamente x, y.")
    x, y = value["x"], value["y"]
    if type(x) is not int or type(y) is not int:
        raise ValueError(f"{name} debe tener coordenadas enteras.")
    return (x, y)


def _point(cell):
    return {"x": cell[0], "y": cell[1]}


def _outdoor(manager, pos):
    x, y = pos
    return (0 <= x < manager.width and 0 <= y < manager.height
            and bool(manager.is_transitable(x, y)))


def _blocked_set(manager, blocked_cells):
    result = set()
    for index, item in enumerate(blocked_cells):
        if isinstance(item, dict):
            pos = _position(item, f"blocked_cells[{index}]")
        elif (isinstance(item, (tuple, list)) and len(item) == 2
              and all(type(v) is int for v in item)):
            pos = tuple(item)
        else:
            raise ValueError(f"blocked_cells[{index}] inválida.")
        if not (0 <= pos[0] < manager.width and 0 <= pos[1] < manager.height):
            raise ValueError(f"blocked_cells[{index}] fuera del mapa.")
        result.add(pos)
    return result


def build_route_request(manager, map_name: str, destinations: dict,
                        *, turn: int = 0, blocked_cells=()):
    """Snapshot para Persona 3. destinos: {id: {'destination_id':str,'goal':{'x':int,'y':int}}}.

    El proveedor necesita además campus.json (terreno) para calcular rutas.
    """
    _text(map_name, "map_name")
    if type(turn) is not int or turn < 0:
        raise ValueError("turn debe ser un entero no negativo.")
    if not isinstance(destinations, dict) or not destinations:
        raise ValueError("destinations debe contener al menos una persona.")
    obstacles = _blocked_set(manager, blocked_cells)
    people = []
    for pid in sorted(destinations):
        if not isinstance(pid, str):
            raise ValueError("Identificador de persona inválido.")
        person = manager.get_person(pid)
        if person is None:
            raise ValueError(f"Persona no registrada: {pid}.")
        if person.building_id is not None:
            raise ValueError(f"{pid} está dentro de un edificio; aún no necesita ruta exterior.")
        if person.status == "a_salvo":
            raise ValueError(f"{pid} ya está marcado a salvo.")
        if not _outdoor(manager, person.position):
            raise ValueError(f"{pid} no ocupa una celda exterior transitable.")
        target = destinations[pid]
        if not isinstance(target, dict):
            raise ValueError(f"Destino de {pid} inválido.")
        name = _text(target.get("destination_id"), "destination_id")
        goal = _position(target.get("goal"), "goal")
        if not _outdoor(manager, goal):
            raise ValueError(f"Destino de {pid} no transitable.")
        people.append({"person_id": pid, "start": _point(person.position),
                       "destination_id": name, "goal": _point(goal)})
    return {
        "schema_version": SCHEMA_VERSION,
        "map_name": map_name,
        "width": manager.width,
        "height": manager.height,
        "turn": turn,
        "people": people,
        "blocked_cells": [_point(cell) for cell in sorted(obstacles)],
    }


def read_route_file(path: str | Path) -> dict:
    """Lee una respuesta JSON; la validación completa ocurre en submit_route."""
    try:
        response = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("No se pudo leer el archivo de ruta JSON.") from error
    if not isinstance(response, dict):
        raise ValueError("La respuesta debe ser un objeto JSON.")
    return response


def save_json(path: str | Path, data: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return path


class ExternalRouteFollower:
    """Reproduce rutas recibidas sin calcular una ruta propia.

    Una actualización = máximo una celda por persona. No cambia el estado
    a 'a_salvo': el identificador de destino no acredita una zona segura.
    """

    def __init__(self, manager, map_name: str):
        self.manager = manager
        self.map_name = _text(map_name, "map_name")
        self._expected = {}  # persona -> objetivo autorizado por una solicitud
        self._routes = {}  # id -> {'path':tuple, 'index':int, ...}
        self.paused = False
        self.turns = 0
        self.total_moves = 0
        self._blocked = set()
        self._priority = 0

    def set_blocked_cells(self, blocked_cells):
        """Actualizar riesgo por turno; celdas con fuego/humo alto, por ejemplo."""
        self._blocked = _blocked_set(self.manager, blocked_cells)

    def set_request(self, request: dict):
        """Registrar objetivos solicitados para impedir respuestas con destino distinto.

        Una nueva solicitud puede reemplazar los objetivos autorizados de las
        personas enumeradas. No elimina rutas que ya estén en curso.
        """
        if not isinstance(request, dict) or request.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Versión del contrato de solicitud incorrecta.")
        if (request.get("map_name") != self.map_name or
                type(request.get("width")) is not int or
                type(request.get("height")) is not int or
                (request["width"], request["height"]) !=
                (self.manager.width, self.manager.height)):
            raise ValueError("Solicitud correspondiente a otro mapa.")
        if type(request.get("turn")) is not int or request["turn"] < 0:
            raise ValueError("Turno de solicitud inválido.")
        cells = request.get("blocked_cells")
        if not isinstance(cells, list):
            raise ValueError("La solicitud debe contener blocked_cells.")
        _blocked_set(self.manager, cells)
        raw_people = request.get("people")
        if not isinstance(raw_people, list) or not raw_people:
            raise ValueError("La solicitud debe contener personas.")
        new = {}
        for i, item in enumerate(raw_people):
            if not isinstance(item, dict):
                raise ValueError(f"people[{i}] inválido.")
            pid = _text(item.get("person_id"), "person_id")
            destination_id = _text(item.get("destination_id"), "destination_id")
            start = _position(item.get("start"), "start")
            goal = _position(item.get("goal"), "goal")
            person = self.manager.get_person(pid)
            if pid in new or person is None or person.building_id is not None or person.status == "a_salvo":
                raise ValueError(f"Persona duplicada, ausente o no exterior: {pid}.")
            if person.position != start or not _outdoor(self.manager, goal):
                raise ValueError(f"Solicitud desactualizada o destino bloqueado: {pid}.")
            new[pid] = {"start": start, "goal": goal,
                        "destination_id": destination_id}
        self._expected.update(new)

    def submit_route(self, data: dict):
        """Validar COMPLETA la respuesta antes de cambiar el estado anterior."""
        if not isinstance(data, dict):
            raise ValueError("La respuesta de rutas debe ser un objeto JSON.")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Versión de contrato de rutas incompatible.")
        if (data.get("map_name") != self.map_name or
                type(data.get("width")) is not int or
                type(data.get("height")) is not int or
                (data["width"], data["height"]) !=
                (self.manager.width, self.manager.height)):
            raise ValueError("La ruta pertenece a otro mapa.")
        route_id = _text(data.get("route_id"), "route_id")
        pid = _text(data.get("person_id"), "person_id")
        destination_id = _text(data.get("destination_id"), "destination_id")
        person = self.manager.get_person(pid)
        if person is None:
            raise ValueError(f"Persona no registrada: {pid}.")
        if person.building_id is not None:
            raise ValueError("No se admiten rutas exteriores para personas dentro.")
        if person.status == "a_salvo":
            raise ValueError("Persona ya marcada a salvo.")
        expected = self._expected.get(pid)
        if expected is None:
            raise ValueError("Falta registrar la solicitud de esta persona.")
        if destination_id != expected["destination_id"]:
            raise ValueError("El ID de destino no coincide con el solicitado.")

        raw_path = data.get("path")
        if (not isinstance(raw_path, list) or not raw_path or
                len(raw_path) > self.manager.width * self.manager.height):
            raise ValueError("path debe ser una lista de longitud válida.")
        path = tuple(_position(item, f"path[{i}]") for i, item in enumerate(raw_path))
        if path[0] != person.position or path[0] != expected["start"]:
            raise ValueError("Ruta desactualizada: el inicio no coincide con la solicitud.")
        if not all(_outdoor(self.manager, cell) for cell in path):
            raise ValueError("La ruta cruza edificios, césped o el exterior del campus.")
        if len(set(path)) != len(path):
            raise ValueError("La ruta repite celdas.")
        if any(abs(x1 - x2) + abs(y1 - y2) != 1
               for (x1, y1), (x2, y2) in zip(path, path[1:])):
            raise ValueError("La ruta tiene diagonales o saltos no contiguos.")
        goal = _position(data.get("goal"), "goal")
        if path[-1] != goal or goal != expected["goal"]:
            raise ValueError("La ruta no termina en el destino solicitado.")

        # Commit: rechazo de ruta inválida jamás elimina una ruta anterior.
        self._routes[pid] = {
            "route_id": route_id,
            "destination_id": destination_id,
            "goal": goal,
            "path": path,
            "index": 0,
            "status": "en_destino" if len(path) == 1 else "en_camino",
            "waits": 0,
        }

    def route_status(self, person_id: str):
        route = self._routes.get(person_id)
        return route["status"] if route else "sin_ruta"

    def route_snapshot(self, person_id: str):
        route = self._routes.get(person_id)
        if route is None:
            return None
        person = self.manager.get_person(person_id)
        return {
            "person_id": person_id,
            "route_id": route["route_id"],
            "destination_id": route["destination_id"],
            "goal": _point(route["goal"]),
            "current": _point(person.position) if person else None,
            "steps_done": route["index"],
            "steps_total": len(route["path"]) - 1,
            "status": route["status"],
            "waits": route["waits"],
        }

    def step(self, *, eligible_person_ids=None, before_step=None) -> int:
        """Intenta un paso por persona con ruta; evita atravesar riesgo u ocupantes.

        No se ejecuta junto al controlador interior sobre el mismo individuo.
        """
        if self.paused:
            return 0
        moved = 0
        ids = sorted(self._routes)
        if not ids:
            self.turns += 1
            return 0
        rotated = ids[self._priority:] + ids[:self._priority]
        for pid in rotated:
            if eligible_person_ids is not None and pid not in eligible_person_ids:
                continue
            route = self._routes[pid]
            person = self.manager.get_person(pid)
            if person is None or person.building_id is not None:
                route["status"] = "ruta_desfasada"
                continue
            if person.status == "a_salvo":
                route["status"] = "detenida"
                continue
            if person.position != route["path"][route["index"]]:
                route["status"] = "ruta_desfasada"
                continue
            if route["index"] == len(route["path"]) - 1:
                route["status"] = "en_destino"
                continue
            nx, ny = route["path"][route["index"] + 1]
            # Optional decision-layer watchdog. The gateway still enforces the
            # unchanged physical contract and never computes a route itself.
            if before_step is not None and not before_step(person, (nx, ny)):
                route["status"] = "bloqueada_por_riesgo"
                route["waits"] += 1
                continue
            if (nx, ny) in self._blocked or not _outdoor(self.manager, (nx, ny)):
                route["status"] = "bloqueada_por_riesgo"
                route["waits"] += 1
                continue
            try:
                self.manager.move_person(pid, nx - person.x, ny - person.y)
            except ValueError:
                route["status"] = "esperando_ocupacion"
                route["waits"] += 1
                continue
            route["index"] += 1
            route["status"] = ("en_destino" if route["index"] == len(route["path"]) - 1
                               else "en_camino")
            moved += 1
        self._priority = (self._priority + 1) % len(ids)
        self.total_moves += moved
        self.turns += 1
        return moved
