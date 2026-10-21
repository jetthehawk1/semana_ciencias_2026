"""Pruebas Paso 14.1 — sin Pygame, usando archivos reales del campus."""
from copy import deepcopy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from simulation.person import Person
from simulation.indoor_people import IndoorPersonManager
from integration.route_gateway import (
    ExternalRouteFollower, build_route_request, read_route_file, save_json
)

MAP = json.loads((ROOT / "data" / "campus.json").read_text(encoding="utf-8"))
ENTRANCES = json.loads((ROOT / "data" / "building_entrances.json").read_text(encoding="utf-8"))
E1 = next(a for a in ENTRANCES["accesses"] if a["building"] == "E1")
START = E1["exterior_cell"]
X, Y = START["x"], START["y"]
PATH = [{"x": X - dx, "y": Y} for dx in range(4)]


def manager_with_p001():
    manager = IndoorPersonManager.from_json(ROOT / "data" / "campus.json")
    manager.add_person(Person("P001", X, Y, status="evacuando"))
    return manager


def mock_response():
    return {"schema_version": "1.0", "route_id": "MOCK-E1-001",
            "map_name": MAP["name"], "width": MAP["width"],
            "height": MAP["height"], "person_id": "P001",
            "destination_id": "PUNTO_DE_PRUEBA_E1",
            "goal": PATH[-1], "path": deepcopy(PATH)}


def must_fail(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("Una ruta u operación inválida fue aceptada.")


def main():
    manager = manager_with_p001()
    follower = ExternalRouteFollower(manager, MAP["name"])
    request = build_route_request(manager, MAP["name"],
                                  {"P001": {"destination_id": "PUNTO_DE_PRUEBA_E1", "goal": PATH[-1]}},
                                  blocked_cells=[(10, 10)], turn=12)
    assert request["schema_version"] == "1.0"
    assert request["width"] == 160 and request["height"] == 100
    assert request["people"][0]["start"] == START
    assert request["blocked_cells"] == [{"x": 10, "y": 10}]
    with tempfile.TemporaryDirectory() as directory:
        p = Path(directory) / "ruta.json"
        save_json(p, mock_response())
        assert read_route_file(p) == mock_response()
        p.write_text("no-json", encoding="utf-8")
        must_fail(lambda: read_route_file(p))
    print("Contrato de solicitud/respuesta y archivos JSON: correctos.")

    response = mock_response()
    must_fail(lambda: follower.submit_route(response))  # Sin solicitud previa
    follower.set_request(request)
    follower.submit_route(response)
    for invalid in (
        {**response, "schema_version": "2.0"},
        {**response, "width": 159},
        {**response, "map_name": "Mapa distinto"},
        {**response, "person_id": "NO_EXISTE"},
        {**response, "destination_id": "DESTINO_NO_SOLICITADO"},
        {**response, "goal": {"x": X - 2, "y": Y}, "path": PATH[:3]},
        {**response, "path": PATH[1:]},
        {**response, "goal": PATH[1]},
        {**response, "path": [PATH[0], {"x": X - 2, "y": Y}, PATH[-1]]},
        {**response, "path": [PATH[0], PATH[1], PATH[0], PATH[1], PATH[2], PATH[3]]},
        {**response, "path": [PATH[0], {"x": 151, "y": 5}, PATH[-1]]},
        {**response, "path": [PATH[0], {"x": True, "y": Y}, PATH[-1]]},
    ):
        must_fail(lambda wrong=invalid: follower.submit_route(wrong))
        assert follower.route_snapshot("P001")["route_id"] == "MOCK-E1-001"
    print("Validación de destino solicitado, mapa incorrecto, ruta obsoleta, diagonales y paredes: correcta.")

    follower.paused = True
    assert follower.step() == 0 and manager.get_person("P001").position == (X, Y)
    follower.paused = False
    follower.set_blocked_cells([(X - 1, Y)])
    assert follower.step() == 0
    assert follower.route_status("P001") == "bloqueada_por_riesgo"
    assert manager.get_person("P001").position == (X, Y)
    follower.set_blocked_cells([])
    assert follower.step() == 1
    assert manager.get_person("P001").position == (X - 1, Y)
    assert follower.step() == 1
    assert follower.step() == 1
    assert follower.step() == 0
    assert manager.get_person("P001").position == (X - 3, Y)
    assert follower.route_status("P001") == "en_destino"
    assert manager.get_person("P001").status == "evacuando"
    print("Pausa, bloqueo por riesgo, reanudación y llegada sin a_salvo: correctos.")

    manager2 = manager_with_p001()
    manager2.add_person(Person("P002", X - 1, Y))
    follower2 = ExternalRouteFollower(manager2, MAP["name"])
    follower2.set_request(build_route_request(manager2, MAP["name"],
        {"P001": {"destination_id": "PUNTO_DE_PRUEBA_E1", "goal": PATH[-1]}}))
    follower2.submit_route(mock_response())
    assert follower2.step() == 0
    assert follower2.route_status("P001") == "esperando_ocupacion"
    manager2.move_person("P002", 0, -1)
    assert follower2.step() == 1
    assert manager2.get_person("P001").position == (X - 1, Y)
    # Si alguien mueve a la persona fuera de la ruta, NO se replantea automáticamente.
    manager2.move_person("P001", 0, 1)
    assert follower2.step() == 0
    assert follower2.route_status("P001") == "ruta_desfasada"
    print("Ocupación, espera y ruta desfasada: correctas.")

    manager3 = manager_with_p001()
    manager3.add_person(Person("P003", 151, 5, building_id="E1"))
    follower3 = ExternalRouteFollower(manager3, MAP["name"])
    inside_response = {**mock_response(), "person_id": "P003",
                       "path": [{"x": 151, "y": 5}], "goal": {"x": 151, "y": 5}}
    must_fail(lambda: follower3.submit_route(inside_response))
    must_fail(lambda: build_route_request(
        manager3, MAP["name"],
        {"P003": {"destination_id": "TEST", "goal": PATH[-1]}}))
    must_fail(lambda: follower3.set_blocked_cells([(160, 100)]))
    print("Persona interior no aceptada y límites validados: correctos.")

    print("Paso 14.1 completado correctamente. Persona 3 NO está conectada aún.")


if __name__ == "__main__":
    main()
