"""Paso 15.2.3: ejemplo de intercambio LOCAL para el optimizador de Persona 3.

NO calcula rutas, NO usa la API de un servicio, NO acredita zonas seguras.
El camino ilustrativo de E1 existe solo para enseñar el contrato v1.0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from simulation.person import Person
from simulation.indoor_people import IndoorPersonManager
from integration.route_gateway import (
    ExternalRouteFollower, build_route_request, save_json
)

DESTINATION_ID = "PUNTO_DE_PRUEBA_E1"  # NO es una zona segura oficial


def create_example(root: Path = ROOT):
    """Devuelve (manager, solicitud, respuesta ilustrativa) usando E1 real."""
    root = Path(root)
    campus = json.loads((root / "data" / "campus.json").read_text(encoding="utf-8"))
    entrances = json.loads((root / "data" / "building_entrances.json").read_text(encoding="utf-8"))
    e1 = next(a for a in entrances["accesses"] if a["building"] == "E1")
    start = e1["exterior_cell"]
    x, y = start["x"], start["y"]

    manager = IndoorPersonManager.from_json(root / "data" / "campus.json")
    path = [{"x": x - i, "y": y} for i in range(4)]
    obstacle = {"x": x - 1, "y": y + 1}  # obstaculo ilustrativo, NO salida del motor de fuego

    if not all(manager.is_transitable(p["x"], p["y"]) for p in path):
        raise ValueError("El acceso E1 o el recorrido demostrativo cambiaron: actualizar el ejemplo.")
    if not manager.is_transitable(obstacle["x"], obstacle["y"]):
        raise ValueError("La celda de bloqueo demostrativa ya no es transitable.")
    if obstacle in path:
        raise ValueError("El bloqueo demostrativo intercepta la ruta.")

    manager.add_person(Person("P001", x, y, status="evacuando"))
    request = build_route_request(
        manager, campus["name"],
        {"P001": {"destination_id": DESTINATION_ID, "goal": path[-1]}},
        turn=12, blocked_cells=[obstacle],
    )
    response = {
        "schema_version": request["schema_version"],
        "route_id": "DEMO-E1-P001-001",
        "map_name": request["map_name"],
        "width": request["width"], "height": request["height"],
        "person_id": "P001", "destination_id": DESTINATION_ID,
        "goal": path[-1], "path": path,
    }

    # Validar la muestra real con el receptor existente, sin alterar motor alguno.
    follower = ExternalRouteFollower(manager, campus["name"])
    follower.set_request(request)
    follower.submit_route(response)
    if follower.route_status("P001") != "en_camino":
        raise AssertionError("El receptor no acepto la respuesta ilustrativa.")
    return manager, request, response


def generate(out_dir: Path, root: Path = ROOT):
    _, request, response = create_example(root)
    out_dir = Path(out_dir)
    req_path = save_json(out_dir / "solicitud_rutas.json", request)
    response_path = save_json(out_dir / "respuesta_mock.json", response)
    return req_path, response_path


def main():
    parser = argparse.ArgumentParser(description="Ejemplo v1.0 de solicitud y respuesta de rutas externas")
    parser.add_argument("--salida", default="exports/persona3_ejemplo",
                        help="Carpeta de salida para los dos JSON (default: exports/persona3_ejemplo)")
    args = parser.parse_args()
    req_path, resp_path = generate(Path(args.salida))
    print("=== PASO 15.2.3: ENTREGA DE EJEMPLO PARA PERSONA 3 ===")
    print(f"[OK] Solicitud: {req_path.resolve()}")
    print(f"[OK] Respuesta ilustrativa: {resp_path.resolve()}")
    print("[OK] Contrato 1.0, campus real, acceso exterior E1, una persona P001.")
    print("[OK] Ruta de demostracion validada por ExternalRouteFollower.")
    print("NOTA: bloqueo y turno ilustrativos; no se calculan rutas ni zonas seguras.")


if __name__ == "__main__":
    main()
