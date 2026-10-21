"""Disaster Command Center - PASO 14.3.5 - integración segura en COPIA.

Copia exclusivamente src/, data/ y las pruebas necesarias a un directorio
TEMPORAL del sistema. Allí prueba el adaptador opt-in con el índice de ocupación
para 500 personas y ejecuta 10 regresiones del sistema original.

NO toca src/simulation/ del proyecto de trabajo, no sustituye ninguna clase
ni parchea importaciones globales. Al terminar destruye la copia temporal.

Uso: python ensayar_integracion_14_3_5.py
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent

REGRESSIONS = [
    'test_personas_interiores.py',
    'test_distribucion_personas.py',
    'test_salida_edificios.py',
    'test_centro_evacuacion.py',
    'test_simulacion_fuego.py',
    'test_simulacion_humo.py',
    'test_simulacion_viento.py',
    'test_efectos_personas.py',
    'test_sensores.py',
    'test_interfaz_rutas.py',
]
STAGING_FILES = [
    'indexed_indoor_people.py',
    'adaptador_indice_14_3_5.py',
    'test_integracion_aislada_14_3_5.py',
    'medir_rendimiento_14_3_3.py',
]
EXCLUDE = {
    '.git', '.venv', 'venv', '__pycache__', '.pytest_cache',
    'build', 'dist', 'reports', 'exports', '.idea', '.vscode',
}


def snapshot() -> dict[str, str]:
    paths = set(ROOT.glob('*.py'))
    for directory in ('src', 'data'):
        folder = ROOT / directory
        if folder.exists():
            paths.update(folder.rglob('*.py'))
            paths.update(folder.rglob('*.json'))
    return {
        str(path.relative_to(ROOT)):
            hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths) if path.is_file()
    }


def copy_ignore(_dir, names):
    return set(names).intersection(EXCLUDE)


def execute(name: str, directory: Path, timeout: int):
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONUTF8'] = '1'
    env.pop('PYTHONPATH', None)
    started = time.perf_counter()
    try:
        result = subprocess.run(
            [sys.executable, '-B', name], cwd=directory, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding='utf-8', errors='replace', text=True,
            timeout=timeout, check=False,
        )
        return result.returncode, time.perf_counter() - started, result.stdout
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or b''
        if isinstance(output, bytes):
            output = output.decode('utf-8', errors='replace')
        return 124, time.perf_counter() - started, output + '\nTIEMPO AGOTADO'


def main() -> int:
    print('=== PASO 14.3.5: INTEGRACION AISLADA Y REVERSIBLE ===', flush=True)
    print('Python:', sys.executable, flush=True)
    print('Proyecto original: SOLO LECTURA. Adaptador: OPT-IN en copia temporal.', flush=True)
    required = ['src', 'data'] + REGRESSIONS + STAGING_FILES
    missing = [name for name in required if not (ROOT / name).exists()]
    if missing:
        print('[ERROR] Faltan:', ', '.join(missing))
        print('No se creó una copia ni se modificaron módulos.')
        return 2
    before = snapshot()
    failed = None
    ok_count = 0
    try:
        with tempfile.TemporaryDirectory(prefix='dcc_integracion_14_3_5_') as temp:
            copy = Path(temp) / 'DisasterCommandCenter'
            copy.mkdir()
            for folder in ('src', 'data'):
                shutil.copytree(ROOT / folder, copy / folder, ignore=copy_ignore)
            for name in REGRESSIONS + STAGING_FILES:
                shutil.copy2(ROOT / name, copy / name)
            print('[OK] Copia temporal creada con módulos, datos y pruebas.', flush=True)
            print('\n[1/2] Comparando integración opt-in con 500 personas...', flush=True)
            code, elapsed, output = execute('test_integracion_aislada_14_3_5.py', copy, 240)
            print(output.rstrip(), flush=True)
            print(f'Resultado de integración: {"OK" if code == 0 else "FALLO"} ({elapsed:.2f}s)', flush=True)
            if code != 0:
                failed = 'integración (ver traceback arriba)'
            if failed is None:
                print('\n[2/2] Regresiones originales en la misma copia...', flush=True)
                for i, name in enumerate(REGRESSIONS, 1):
                    code, elapsed, output = execute(name, copy, 240)
                    print(f'  [{i:02d}/10] {name}: {"OK" if code == 0 else "FALLO"} '
                          f'({elapsed:.2f}s)', flush=True)
                    if code != 0:
                        failed = name
                        for line in output.splitlines()[-35:]:
                            print('    ' + line, flush=True)
                        break
                    ok_count += 1
            print('\n[OK] Al salir se elimina automáticamente la copia temporal.', flush=True)
    except (OSError, shutil.Error) as exc:
        print('[ERROR] Falló la creación/eliminación de la copia:', exc)
        failed = 'operación de copia'
    after = snapshot()
    unchanged = before == after
    print('\n=== RESUMEN 14.3.5 ===', flush=True)
    print(f'Prueba de integración: {"OK" if failed is None else "REVISAR"}.', flush=True)
    print(f'Regresiones del proyecto original: {ok_count}/10 aprobadas.', flush=True)
    print(f'Archivos Python/JSON originales verificados: {len(before)}.', flush=True)
    print('[OK] Archivos originales sin cambios.' if unchanged
          else '[ALERTA] Se detectaron cambios de archivos originales.', flush=True)
    if not unchanged:
        altered = sorted(set(before) ^ set(after) |
                         {k for k in before.keys() & after.keys() if before[k] != after[k]})
        for name in altered:
            print('  CAMBIO:', name, flush=True)
    if failed is None and ok_count == 10 and unchanged:
        print('Paso 14.3.5 APROBADO EN COPIA. OPTIMIZACION NO INSTALADA EN PRODUCCION.', flush=True)
        return 0
    print('Paso 14.3.5 PENDIENTE: compartir resultados antes de integrar.', flush=True)
    return 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Interrumpido. La copia temporal se limpiará; originales sin sustitución.')
        raise SystemExit(130)
