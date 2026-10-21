"""Paso 15.2.3: valida el ejemplo de Persona 3 sin modificar src/ ni data/."""
from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from integration.route_gateway import ExternalRouteFollower, read_route_file
from generar_ejemplo_persona3_15_2_3 import create_example, generate


def expect_rejection(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError("El receptor acepto datos incompatibles.")


def main():
    before = {p.relative_to(ROOT): p.read_bytes()
              for folder in (ROOT / "src", ROOT / "data")
              for p in folder.rglob("*") if p.is_file() and p.suffix in {".py", ".json"}}
    print("=== PASO 15.2.3: PRUEBA DEL EJEMPLO DE RUTAS PARA PERSONA 3 ===")
    manager, request, response = create_example()
    assert request["schema_version"] == "1.0" and response["schema_version"] == "1.0"
    assert request["width"] == 160 and request["height"] == 100
    assert len(request["people"]) == 1 and request["people"][0]["person_id"] == "P001"
    assert request["people"][0]["start"] == response["path"][0]
    assert request["people"][0]["goal"] == response["goal"] == response["path"][-1]
    assert all(p not in request["blocked_cells"] for p in response["path"])
    print("[OK] Solicitud v1.0: E1 exterior, 160x100, identificadores y bloqueo de ejemplo.")

    with tempfile.TemporaryDirectory(prefix="dcc_persona3_15_2_3_") as tmp:
        p1, p2 = generate(Path(tmp))
        assert read_route_file(p1) == request
        assert read_route_file(p2) == response
        assert json.loads(p1.read_text(encoding="utf-8")) == request
        assert json.loads(p2.read_text(encoding="utf-8")) == response
    print("[OK] JSON de solicitud/respuesta generado y leido sin divergencias.")

    follower = ExternalRouteFollower(manager, request["map_name"])
    expect_rejection(lambda: follower.submit_route(response))  # exige solicitud previa
    follower.set_request(request)
    follower.set_blocked_cells(request["blocked_cells"])
    follower.submit_route(response)

    for edited in (
        {**response, "destination_id": "NO_AUTORIZADO"},
        {**response, "goal": {"x": 0, "y": 0}},
        {**response, "schema_version": "2.0"},
        {**response, "map_name": "Campus distinto"},
        {**response, "path": response["path"][1:]},
        {**response, "path": [response["path"][0], response["path"][-1]]},
    ):
        expect_rejection(lambda edited=edited: follower.submit_route(edited))
    assert follower.route_status("P001") == "en_camino"
    print("[OK] Respuestas invalidas rechazadas; ruta valida conservada.")

    follower.paused = True
    assert follower.step() == 0
    assert manager.get_person("P001").position == tuple(response["path"][0].values())
    follower.paused = False
    next_cell = response["path"][1]
    follower.set_blocked_cells([next_cell])
    assert follower.step() == 0
    assert follower.route_status("P001") == "bloqueada_por_riesgo"
    follower.set_blocked_cells([])
    for _ in range(len(response["path"]) - 1):
        assert follower.step() == 1
    assert follower.route_status("P001") == "en_destino"
    assert manager.get_person("P001").status == "evacuando"
    print("[OK] Pausa, bloqueo dinamico, reanudacion y llegada SIN marcar a salvo.")

    after = {p.relative_to(ROOT): p.read_bytes()
             for folder in (ROOT / "src", ROOT / "data")
             for p in folder.rglob("*") if p.is_file() and p.suffix in {".py", ".json"}}
    assert before == after, "Se modificaron los motores o datos originales."
    print(f"[OK] Integridad de src/ y data/: {len(before)} archivos sin cambios.")
    print("PASO 15.2.3: EJEMPLO COMPATIBLE APROBADO. PERSONA 3 NO CONECTADA TODAVIA.")


if __name__ == "__main__":
    main()
