"""Crea (opcionalmente) un paquete de ejemplo de sensores para Persona 2.

No edita ni configura el simulador. Usar desde la raiz de DisasterCommandCenter.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from dcc_app.mode_scene import ModeSensorScene
from integration.persona2_contract_15_1 import read_sensor_package, OBSERVABLE_FIELDS


def produce(output: Path):
    # original evita depender de que otro PC tenga autorizacion local para optimizado.
    scene = ModeSensorScene(ROOT, kind="emergencia", mode="original")
    scene.start()
    for _ in range(35):
        scene.step()
    if len(scene.reading_history) != 432:
        raise AssertionError("Se esperaban 432 lecturas (12 sensores x 36 turnos).")
    scene.export_readings(output)
    parsed = read_sensor_package(output, sensors_path=ROOT / 'data' / 'sensores_paso_13.json')
    if len(parsed['observables']) != 432:
        raise AssertionError('El contrato no devolvio 432 lecturas observables.')
    return parsed


def main():
    parser = argparse.ArgumentParser(description="Paso 15.1: ejemplo sin base de datos")
    parser.add_argument("--salida", type=Path,
                        help="Directorio donde guardar CSV/JSONL/manifiesto; por defecto, prueba temporal")
    opts = parser.parse_args()
    print('=== PASO 15.1: ENTREGA DE DATOS PARA PERSONA 2 ===')
    if opts.salida is None:
        with TemporaryDirectory(prefix="dcc_persona2_15_1_") as tmp:
            info = produce(Path(tmp))
            print('[OK] Paquete validado en carpeta temporal (se borra al terminar).')
    else:
        if opts.salida.resolve().is_relative_to(ROOT / 'src') or opts.salida.resolve().is_relative_to(ROOT / 'data'):
            parser.error('No guardes exportaciones dentro de src/ ni data/.')
        info = produce(opts.salida)
        print(f'[OK] CSV, JSONL y manifiesto exportados en: {opts.salida.resolve()}')
    print(f"[OK] Registros: {len(info['observables'])}; sensores: {info['manifest']['sensor_count']}; turnos: {info['manifest']['turn_count']}.")
    print('[OK] Campos observables para IA:', ', '.join(OBSERVABLE_FIELDS))
    print('[OK] Etiqueta fire_within_2_cells separada de las observaciones.')
    print('NOTA: datos sinteticos; los turnos no son segundos ni fechas.')


if __name__ == '__main__':
    main()
