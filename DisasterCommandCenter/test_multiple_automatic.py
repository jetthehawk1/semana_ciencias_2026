
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


print("=== PRUEBA DE MOVIMIENTO AUTOMÁTICO ===")

# 1. Crear el mapa
campus = CampusMap(5, 5)
campus.fill_terrain("floor")

graph = CampusGraph(campus)

manager = PersonManager(
    width=5,
    height=5,
    is_transitable=graph.is_valid,
)

# 2. Crear las personas
person_a = Person(
    person_id="persona-A",
    x=0,
    y=2,
)

person_b = Person(
    person_id="persona-B",
    x=0,
    y=3,
)

manager.add_person(person_a)
manager.add_person(person_b)

# 3. Crear solicitud para ambas personas
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
            "start": {"x": 0, "y": 3},
            "destination_id": "salida-B",
            "goal": {"x": 4, "y": 3},
        },
    ],
    "blocked_cells": [],
}

# 4. Preparar el controlador
follower = ExternalRouteFollower(
    manager=manager,
    map_name="Mapa de prueba",
)

follower.set_request(request)

# 5. Calcular y registrar ambas rutas
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

# 6. Ejecutar cuatro turnos automáticos
for turn in range(1, 5):

    moved = follower.step()

    print(
        f"Turno {turn}: "
        f"A={person_a.position}, "
        f"B={person_b.position}, "
        f"movimientos={moved}"
    )

    # Ambas personas deben permanecer separadas
    assert person_a.position != person_b.position

    # Ambas avanzan una celda por turno
    assert moved == 2

    assert person_a.position == (turn, 2)
    assert person_b.position == (turn, 3)

# 7. Comprobar destinos y estados
assert person_a.position == (4, 2)
assert person_b.position == (4, 3)

assert follower.route_status("persona-A") == "en_destino"
assert follower.route_status("persona-B") == "en_destino"

print()
print("Ambas personas llegaron a sus destinos: OK")
print("No hubo colisiones: OK")
print("PRUEBA AUTOMÁTICA COMPLETADA")
