
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from simulation.campus_map import CampusMap
from simulation.person import Person
from simulation.person_manager import PersonManager
from integration.route_gateway import ExternalRouteFollower

from routing.graph import CampusGraph
from routing.route_adapter import calculate_route_response


print("=== PRUEBA DE MÚLTIPLES PERSONAS ===")

# 1. Crear el mapa
campus = CampusMap(5, 5)
campus.fill_terrain("floor")

graph = CampusGraph(campus)

manager = PersonManager(
    width=5,
    height=5,
    is_transitable=graph.is_valid,
)

# 2. Crear dos personas
person_a = Person(
    person_id="persona-A",
    x=0,
    y=2,
)

person_b = Person(
    person_id="persona-B",
    x=1,
    y=2,
)

manager.add_person(person_a)
manager.add_person(person_b)

print("1. Posición inicial A:", person_a.position)
print("2. Posición inicial B:", person_b.position)

# 3. Crear una solicitud de ruta para A
request = {
    "schema_version": "1.0",
    "map_name": "Mapa de prueba",
    "width": 5,
    "height": 5,
    "turn": 0,
    "people": [
        {
            "person_id": "persona-A",
            "start": {"x": 0, "y": 2},
            "destination_id": "zona-segura-001",
            "goal": {"x": 4, "y": 2},
        }
    ],
    "blocked_cells": [],
}

follower = ExternalRouteFollower(
    manager=manager,
    map_name="Mapa de prueba",
)

follower.set_request(request)

response = calculate_route_response(
    graph,
    request,
    person_id="persona-A",
    route_id="ruta-persona-A",
)

assert response is not None
follower.submit_route(response)

print("3. Ruta de A:", response["path"])

# 4. Intentar avanzar con B ocupando la celda
moved = follower.step()

assert moved == 0
assert person_a.position == (0, 2)
assert person_b.position == (1, 2)

print("4. A espera porque B ocupa (1, 2): OK")

# 5. Mover B para liberar la celda
moved_b = manager.move_person(
    "persona-B",
    1,
    0,
)

assert person_b.position == (2, 2)

print("5. B avanza a:", person_b.position)

# 6. A puede ocupar la celda liberada
moved = follower.step()

assert moved == 1
assert person_a.position == (1, 2)

print("6. A avanza a:", person_a.position)

# 7. Verificar que no comparten posición
assert person_a.position != person_b.position

print("7. Sin colisiones: OK")
print()
print("PRUEBA DE MÚLTIPLES PERSONAS COMPLETADA")
