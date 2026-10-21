
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
from routing.routing_controller import RoutingController


print("=== PRUEBA DE RUTA INEXISTENTE ===")

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

# 2. Solicitud inicial
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
            "destination_id": "salida-001",
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

original = calculate_route_response(
    graph,
    request,
    person_id="persona-001",
    route_id="ruta-original",
)

assert original is not None
follower.submit_route(original)

controller = RoutingController(
    graph=graph,
    follower=follower,
    manager=manager,
    request=request,
)

# 3. Avanzar hasta (1,2)
result = controller.step(blocked_cells=[])

assert person.position == (1, 2)

print("1. Posición inicial avanzada:", person.position)

# 4. Bloquear las cuatro direcciones
blocked = [
    {"x": 2, "y": 2},
    {"x": 1, "y": 1},
    {"x": 1, "y": 3},
    {"x": 0, "y": 2},
]

result = controller.step(blocked_cells=blocked)

assert person.position == (1, 2)
assert result["moved"] == 0
assert result["replanned"] == []
assert controller.replanner.failed_attempts == 1

print("2. Persona rodeada por obstáculos: OK")
print("3. No existe ruta alternativa: OK")
print("4. Intentos fallidos:", controller.replanner.failed_attempts)

# 5. Ejecutar varios turnos sin cambios
for _ in range(3):
    result = controller.step()

    assert person.position == (1, 2)
    assert result["moved"] == 0
    assert result["replanned"] == []

assert controller.replanner.failed_attempts == 1

print("5. No se repiten búsquedas fallidas: OK")

# 6. Retirar los obstáculos
result = controller.step(blocked_cells=[])

# La persona puede reanudar la ruta original
# o continuar mediante una ruta recalculada.
for _ in range(8):
    if person.position == (4, 2):
        break

    controller.step()

assert person.position == (4, 2)
assert follower.route_status("persona-001") == "en_destino"

print("6. Obstáculos retirados: OK")
print("7. Destino alcanzado:", person.position)
print()
print("PRUEBA DE RECUPERACIÓN COMPLETADA")
