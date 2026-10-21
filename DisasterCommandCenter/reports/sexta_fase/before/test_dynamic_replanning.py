
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from simulation.campus_map import CampusMap
from routing.graph import CampusGraph
from routing.route_adapter import calculate_route_response


print("=== PRUEBA DE RECÁLCULO DINÁMICO ===")

# 1. Crear mapa
campus = CampusMap(5, 5)
campus.fill_terrain("floor")

graph = CampusGraph(campus)

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

# 3. Calcular ruta original
original = calculate_route_response(
    graph,
    request,
    person_id="persona-001",
    route_id="ruta-original",
)

assert original is not None

print("1. Ruta original:", original["path"])

# 4. Simular que la persona ya avanzó
current_position = {"x": 1, "y": 2}

# 5. Aparece un obstáculo
request["turn"] = 1
request["blocked_cells"] = [
    {"x": 2, "y": 2}
]

# Actualizar el inicio de la ruta
request["people"][0]["start"] = current_position

print("2. Posición actual:", current_position)
print("3. Obstáculo:", request["blocked_cells"])

# 6. Calcular nueva ruta
new_route = calculate_route_response(
    graph,
    request,
    person_id="persona-001",
    route_id="ruta-alternativa",
)

assert new_route is not None

print("4. Ruta alternativa:", new_route["path"])

# 7. Verificar ruta alternativa
path = new_route["path"]

assert path[0] == current_position
assert path[-1] == {"x": 4, "y": 2}
assert {"x": 2, "y": 2} not in path

# Cada movimiento debe ser cardinal
for previous, current in zip(path, path[1:]):
    distance = (
        abs(previous["x"] - current["x"])
        + abs(previous["y"] - current["y"])
    )
    assert distance == 1

print("5. La ruta evita el obstáculo: OK")
print("6. La ruta comienza en la posición actual: OK")
print("7. La ruta llega al destino: OK")
print()
print("PRUEBA DE RECÁLCULO DINÁMICO COMPLETADA")
