
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


print("=== INTEGRACIÓN PERSONA 1 + PERSONA 3 ===")

# 1. Crear mapa de prueba
campus = CampusMap(5, 5)
campus.fill_terrain("floor")

graph = CampusGraph(campus)

# 2. Crear administrador y persona
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

print("1. Persona creada:", person.position)

# 3. Crear solicitud de evacuación
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
    "blocked_cells": [
        {"x": 2, "y": 2}
    ],
}

# 4. Crear controlador de Persona 1
follower = ExternalRouteFollower(
    manager=manager,
    map_name="Mapa de prueba",
)

follower.set_request(request)
follower.set_blocked_cells(request["blocked_cells"])

print("2. Solicitud registrada: OK")

# 5. Calcular ruta con A* de Persona 3
response = calculate_route_response(
    graph,
    request,
    person_id="persona-001",
    route_id="ruta-integracion-001",
)

assert response is not None

print("3. Ruta A* calculada:", response["path"])

# 6. Entregar la ruta a Persona 1
follower.submit_route(response)

assert follower.route_status("persona-001") == "en_camino"

print("4. Ruta aceptada por Persona 1: OK")

# 7. Ejecutar movimientos
expected_path = [
    (cell["x"], cell["y"])
    for cell in response["path"]
]

for turn, expected_position in enumerate(
    expected_path[1:], start=1
):
    previous_position = person.position

    moved = follower.step()

    assert moved == 1, (
        f"No hubo movimiento en turno {turn}"
    )

    assert person.position == expected_position, (
        f"Posición incorrecta en turno {turn}"
    )

    distance = (
        abs(person.x - previous_position[0])
        + abs(person.y - previous_position[1])
    )

    assert distance == 1, (
        "La persona avanzó más de una celda"
    )

    assert person.position != (2, 2), (
        "La persona atravesó el obstáculo"
    )

    print(
        f"Turno {turn}: "
        f"persona en {person.position}"
    )

# 8. Verificar llegada al destino
assert person.position == (4, 2)

assert follower.route_status("persona-001") == "en_destino"

snapshot = follower.route_snapshot("persona-001")

assert snapshot["steps_done"] == len(expected_path) - 1
assert snapshot["steps_total"] == len(expected_path) - 1

# Llegar al destino no cambia automáticamente
# el estado de la persona a "a_salvo".
assert person.status != "a_salvo"

print()
print("5. Destino alcanzado: OK")
print("6. Estado de ruta:", follower.route_status("persona-001"))
print("7. Movimientos totales:", follower.total_moves)
print("8. Estado de la persona:", person.status)

print()
print("INTEGRACIÓN COMPLETADA CORRECTAMENTE")
