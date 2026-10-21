
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


print("=== PRUEBA DEL CONTROLADOR DE RUTAS ===")

# 1. Crear mapa
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

# 2. Crear solicitud inicial
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

# 3. Configurar controlador de Persona 1
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

# 4. Crear controlador de Persona 3
controller = RoutingController(
    graph=graph,
    follower=follower,
    manager=manager,
    request=request,
)

print("1. Ruta inicial:", original["path"])

# 5. Primer turno sin obstáculos
result = controller.step(blocked_cells=[])

assert result["moved"] == 1
assert person.position == (1, 2)

print("2. Turno 1:", result)
print("   Posición:", person.position)

# 6. Aparece un obstáculo
result = controller.step(
    blocked_cells=[{"x": 2, "y": 2}]
)

assert result["moved"] == 0
assert result["replanned"] == ["persona-001"]
assert result["replan_count"] == 1
assert person.position == (1, 2)

print("3. Turno 2:", result)
print("   Recálculo automático: OK")

# 7. Continuar la simulación
for _ in range(7):
    result = controller.step()

    print(
        f"Turno {result['turn']}: "
        f"posición={person.position}, "
        f"movimientos={result['moved']}"
    )

    assert person.position != (2, 2)

    if person.position == (4, 2):
        break

# 8. Verificar llegada
assert person.position == (4, 2)
assert follower.route_status("persona-001") == "en_destino"

assert controller.replanner.replan_count == 1

print()
print("Recálculos:", controller.replanner.replan_count)
print("Destino alcanzado: OK")
print("PRUEBA DEL CONTROLADOR COMPLETADA")
