
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


print("=== PRUEBA DE CONFLICTOS ENTRE RUTAS ===")

# 1. Crear mapa
campus = CampusMap(5, 5)
campus.fill_terrain("floor")

graph = CampusGraph(campus)

manager = PersonManager(
    width=5,
    height=5,
    is_transitable=graph.is_valid,
)

# 2. Crear personas
person_a = Person(
    person_id="persona-A",
    x=0,
    y=2,
)

person_b = Person(
    person_id="persona-B",
    x=2,
    y=1,
)

manager.add_person(person_a)
manager.add_person(person_b)

# 3. Crear solicitud
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
            "destination_id": "salida-A",
            "goal": {"x": 4, "y": 2},
        },
        {
            "person_id": "persona-B",
            "start": {"x": 2, "y": 1},
            "destination_id": "salida-B",
            "goal": {"x": 2, "y": 3},
        },
    ],
    "blocked_cells": [],
}

# 4. Preparar controlador
follower = ExternalRouteFollower(
    manager=manager,
    map_name="Mapa de prueba",
)

follower.set_request(request)

# 5. Calcular ambas rutas
for person_id in ("persona-A", "persona-B"):

    response = calculate_route_response(
        graph,
        request,
        person_id=person_id,
        route_id=f"ruta-{person_id}",
    )

    assert response is not None
    follower.submit_route(response)

    print(f"Ruta {person_id}: {response['path']}")

# 6. Simular seis turnos
for turn in range(1, 7):

    moved = follower.step()

    print(
        f"Turno {turn}: "
        f"A={person_a.position}, "
        f"B={person_b.position}, "
        f"movimientos={moved}"
    )

    # Nunca deben ocupar la misma celda
    assert person_a.position != person_b.position

    # Cada persona puede avanzar como máximo
    # una celda por turno
    assert moved in (0, 1, 2)

# 7. Mostrar estados finales
print()
print("Estado A:", follower.route_status("persona-A"))
print("Estado B:", follower.route_status("persona-B"))

print("Sin colisiones: OK")
print("PRUEBA DE CONFLICTOS COMPLETADA")
