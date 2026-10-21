
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


print("=== PRUEBA DE OBSTÁCULOS DINÁMICOS ===")

# 1. Crear mapa y persona
campus = CampusMap(5, 5)
campus.fill_terrain("floor")

graph = CampusGraph(campus)

manager = PersonManager(
    width=5,
    height=5,
    is_transitable=graph.is_valid,
)

person = Person(
    person_id="persona-001",
    x=0,
    y=2,
)

manager.add_person(person)

# 2. Crear solicitud sin obstáculos
request = {
    "schema_version": "1.0",
    "map_name": "Mapa de prueba",
    "width": 5,
    "height": 5,
    "turn": 0,
    "people": [
        {
            "person_id": "persona-001",
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
    person_id="persona-001",
    route_id="ruta-dinamica-001",
)

assert response is not None

follower.submit_route(response)

print("1. Ruta inicial:", response["path"])

# 3. Avanzar el primer turno
moved = follower.step()

assert moved == 1
assert person.position == (1, 2)

print("2. Primer movimiento:", person.position)

# 4. Aparece un obstáculo en la siguiente celda
follower.set_blocked_cells([
    {"x": 2, "y": 2}
])

print("3. Nuevo obstáculo en (2, 2)")

# 5. Intentar avanzar
moved = follower.step()

assert moved == 0
assert person.position == (1, 2)
assert follower.route_status("persona-001") == "bloqueada_por_riesgo"

print("4. Movimiento detenido correctamente: OK")

# 6. Desaparece el obstáculo
follower.set_blocked_cells([])

print("5. Obstáculo eliminado")

# 7. Continuar hasta el destino
for turn in range(3):
    moved = follower.step()
    assert moved == 1

    print(
        f"Movimiento después de liberar: "
        f"{person.position}"
    )

assert person.position == (4, 2)
assert follower.route_status("persona-001") == "en_destino"

print("6. Destino alcanzado: OK")
print()
print("PRUEBA DINÁMICA COMPLETADA")
