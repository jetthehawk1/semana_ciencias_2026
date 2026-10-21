"""Paso 14.4.4: seleccion de modo real para la nueva ventana Pygame.

Uso: python main_unificado_14_4_4.py [--modo-original] [--smoke-test]
Por defecto lee data/modo_ejecucion_14_3_6B.json al arrancar.
--modo-original usa el modo seguro SOLO en este proceso (no toca JSON).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from dcc_app.model import load_campus
from dcc_app.mode_application import ModeSensorDisasterApp


def main(argv=None):
    parser = argparse.ArgumentParser(description='Disaster Command Center | Paso 14.4.4')
    parser.add_argument('--modo-original', action='store_true',
                        help='Ignorar temporalmente modo optimizado; no cambia configuracion')
    parser.add_argument('--smoke-test', action='store_true',
                        help='Abrir Pygame durante 3 fotogramas para prueba sin pantalla')
    args = parser.parse_args(argv)
    snapshot = load_campus(ROOT/'data/campus.json', ROOT/'data/building_entrances.json')
    selected = 'original' if args.modo_original else None
    app = ModeSensorDisasterApp(snapshot, ROOT, mode=selected)
    if args.modo_original:
        print('[INFO] Modo ORIGINAL forzado solo para esta ventana; configuracion intacta.')
    app.run(smoke_test=args.smoke_test)


if __name__ == '__main__':
    main()
