"""Escenario funcional detallado; --legacy conserva el lanzador de Persona 1."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Disaster Command Center | Escenario detallado")
    parser.add_argument("--legacy", action="store_true", help="Ejecutar escenario integrado anterior 160x100")
    parser.add_argument("--modo-original", action="store_true", help="Usar administrador original solo en esta sesion")
    parser.add_argument("--smoke-test", action="store_true", help="Renderizar tres fotogramas y cerrar")
    parser.add_argument('--evacuation-mode', choices=('intelligent', 'traditional'), default=None,
                        help='Politica funcional; independiente del administrador original/optimizado')
    args = parser.parse_args(argv)
    if args.legacy:
        from main_unificado_14_4_4 import main as legacy_main
        return legacy_main((["--modo-original"] if args.modo_original else []) +
                           (["--smoke-test"] if args.smoke_test else []))
    from dcc_app.functional_application import FunctionalDisasterApp
    from dcc_app.model import load_campus
    assets = ROOT / "data/functional"
    snapshot = load_campus(assets / "campus.json", assets / "building_entrances.json")
    app = FunctionalDisasterApp(snapshot, ROOT, mode="original" if args.modo_original else None,
                               evacuation_mode=args.evacuation_mode)
    app.run(smoke_test=args.smoke_test)


if __name__ == "__main__":
    main()
