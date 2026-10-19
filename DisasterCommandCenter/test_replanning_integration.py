
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


print("=== PRUEBA DE RECÁLCULO INTEGRADO ===")

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

# 2. Solicitud inicial sin obstáculos
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

# 3. Calcular y registrar ruta original
original = calculate_route_response(
    graph,
    request,
    person_id="persona-001",
    route_id="ruta-original",
)

assert original is not None
follower.submit_route(original)

print("1. Ruta original:", original["path"])

# 4. Avanzar un turno
moved = follower.step()

assert moved == 1
assert person.position == (1, 2)

print("2. Posición después del primer turno:", person.position)

# 5. Aparece un obstáculo
blocked_cells = [{"x": 2, "y": 2}]

follower.set_blocked_cells(blocked_cells)

print("3. Obstáculo detectado:", blocked_cells)

# 6. Comprobar que la ruta queda bloqueada
moved = follower.step()

assert moved == 0
assert person.position == (1, 2)
assert follower.route_status("persona-001") == "bloqueada_por_riesgo"

print("4. Movimiento detenido: OK")

# 7. Actualizar solicitud con la posición actual
request["turn"] = 2
request["blocked_cells"] = blocked_cells
request["people"][0]["start"] = {
    "x": person.x,
    "y": person.y,
}

# 8. Calcular ruta alternativa
alternative = calculate_route_response(
    graph,
    request,
    person_id="persona-001",
    route_id="ruta-alternativa",
)

assert alternative is not None
assert {"x": 2, "y": 2} not in alternative["path"]

print("5. Ruta alternativa:", alternative["path"])

# 9. Registrar nueva solicitud y ruta
follower.set_request(request)
follower.submit_route(alternative)

print("6. Nueva ruta registrada: OK")

# 10. Seguir la ruta alternativa
for turn in range(1, len(alternative["path"])):

    moved = follower.step()

    print(
        f"Movimiento alternativo {turn}: "
        f"{person.position}"
    )

    assert moved == 1
    assert person.position != (2, 2)

# 11. Verificar llegada al destino
assert person.position == (4, 2)
assert follower.route_status("persona-001") == "en_destino"

print()
print("La persona evitó el obstáculo: OK")
print("La persona llegó al destino: OK")
print("PRUEBA DE RECÁLCULO INTEGRADO COMPLETADA")
