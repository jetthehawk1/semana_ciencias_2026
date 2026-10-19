
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
from routing.dynamic_replanner import DynamicReplanner


print("=== PRUEBA DE RECÁLCULO AUTOMÁTICO ===")

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

follower = ExternalRouteFollower(
    manager=manager,
    map_name="Mapa de prueba",
)

follower.set_request(request)

# 3. Registrar ruta inicial
original = calculate_route_response(
    graph,
    request,
    person_id="persona-001",
    route_id="ruta-original",
)

assert original is not None
follower.submit_route(original)

replanner = DynamicReplanner(
    graph=graph,
    follower=follower,
    manager=manager,
)

print("1. Ruta original:", original["path"])

# 4. Primer movimiento
moved = follower.step()

assert moved == 1
assert person.position == (1, 2)

print("2. Posición inicial avanzada:", person.position)

# 5. Aparece un obstáculo
blocked_cells = [{"x": 2, "y": 2}]

request["turn"] = 1
request["blocked_cells"] = blocked_cells

follower.set_blocked_cells(blocked_cells)

print("3. Obstáculo detectado:", blocked_cells)

# 6. Detectar bloqueo
moved = follower.step()

assert moved == 0
assert follower.route_status("persona-001") == "bloqueada_por_riesgo"

print("4. Ruta bloqueada: OK")

# 7. Recálculo automático
replanned = replanner.replan_if_blocked(
    request,
    "persona-001",
)

assert replanned is True
assert replanner.replan_count == 1

print("5. Recálculo automático: OK")

# 8. Continuar la simulación
for turn in range(1, 8):

    moved = follower.step()

    print(
        f"Turno alternativo {turn}: "
        f"{person.position}"
    )

    assert person.position != (2, 2)

    if person.position == (4, 2):
        break

# 9. Comprobar llegada
assert person.position == (4, 2)
assert follower.route_status("persona-001") == "en_destino"

print()
print("Recálculos realizados:", replanner.replan_count)
print("Destino alcanzado: OK")
print("PRUEBA AUTOMÁTICA COMPLETADA")
