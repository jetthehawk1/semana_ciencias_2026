"""Paso 14.3.6B: selector reversible, instalado POR CONFIG, nunca parchea módulos.

  python gestionar_modo_14_3_6B.py estado
  python gestionar_modo_14_3_6B.py probar
  python gestionar_modo_14_3_6B.py activar optimizado
  python gestionar_modo_14_3_6B.py revertir

Activar: exige ZIP íntegro de 14.3.6A y ensayos previos en copias.
Revertir: borra SOLO data/modo_ejecucion_14_3_6B.json.
Los visores antiguos no leen el selector: su comportamiento NO cambia.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
from selector_modo_14_3_6B import CONFIG, FORMATO, leer_modo

# Baseline controlada: clases y datos originales sin modificaciones.
PROTECTED = (
    'src/simulation/person_manager.py',
    'src/simulation/indoor_people.py',
    'src/simulation/evacuation_control.py',
    'src/simulation/hazard_impact.py',
    'data/campus.json',
    'data/building_entrances.json',
    'data/ocupacion_ejemplo.json',
    'data/sensores_paso_13.json',
)
STAGING = (
    'selector_modo_14_3_6B.py', 'test_selector_modo_14_3_6B.py',
    'indexed_indoor_people.py', 'adaptador_indice_14_3_5.py',
)
SOURCE = (
    'src/simulation/person_manager.py', 'src/simulation/indoor_people.py',
    'src/simulation/evacuation_control.py', 'src/simulation/hazard_impact.py',
)
EXCLUDED = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache',
            'reports', 'exports', '.idea', '.vscode', 'build', 'dist'}


def hashes() -> dict[str, str]:
    paths = set(ROOT.glob('*.py'))
    for folder in ('src', 'data'):
        for ext in ('*.py', '*.json'):
            paths.update((ROOT / folder).rglob(ext))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def require_files():
    required = STAGING + ('ensayar_integracion_14_3_5.py',
                           'preparar_respaldo_14_3_6.py')
    missing = [name for name in required if not (ROOT / name).is_file()]
    missing += [name for name in PROTECTED if not (ROOT / name).is_file()]
    if missing:
        raise RuntimeError('Faltan archivos: ' + ', '.join(missing))


def run(cmd: list[str], cwd: Path, timeout: int = 600):
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONUTF8'] = '1'
    env.pop('PYTHONPATH', None)
    completed = subprocess.run([sys.executable, '-B'] + cmd, cwd=cwd, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding='utf-8', errors='replace',
                               timeout=timeout, check=False)
    print(completed.stdout.rstrip(), flush=True)
    if completed.returncode:
        raise RuntimeError(f'Prueba fallida {cmd[0]} (codigo {completed.returncode}).')
    return completed.stdout


def _copy_ignore(_path, names):
    return set(names) & EXCLUDED


def preflight():
    require_files()
    before = hashes()
    print('=== 14.3.6B: PRUEBAS EN COPIAS TEMPORALES ===', flush=True)
    with tempfile.TemporaryDirectory(prefix='dcc_14_3_6B_') as dirname:
        dest = Path(dirname) / 'DisasterCommandCenter'
        dest.mkdir()
        for folder in ('src', 'data'):
            shutil.copytree(ROOT / folder, dest / folder, ignore=_copy_ignore)
        for item in STAGING:
            shutil.copy2(ROOT / item, dest / item)
        print('[1/2] Selector, equivalencia y reversion en copia...', flush=True)
        output = run(['test_selector_modo_14_3_6B.py'], dest, 240)
        if 'SELECTOR APROBADO EN COPIA.' not in output:
            raise RuntimeError('Falta marca de aprobacion del selector.')
        print('[2/2] Integracion 14.3.5 y 10 regresiones en otra copia...', flush=True)
        output = run(['ensayar_integracion_14_3_5.py'], ROOT, 600)
        if ('Paso 14.3.5 APROBADO EN COPIA.' not in output or
                'Regresiones del proyecto original: 10/10 aprobadas.' not in output):
            raise RuntimeError('Integracion anterior no aprobada.')
    after = hashes()
    if before != after:
        changed = sorted(set(before) ^ set(after) |
                         {k for k in before.keys() & after.keys() if before[k] != after[k]})
        raise RuntimeError('Se detectaron cambios durante la prueba: ' + str(changed))
    print(f'[OK] Copias eliminadas; {len(before)} Python/JSON originales sin cambios.', flush=True)
    print('Paso 14.3.6B: PRUEBA PREVIA APROBADA. NO SE CAMBIO EL MODO.', flush=True)


def find_and_verify_backup(path: Path | None = None) -> Path:
    from preparar_respaldo_14_3_6 import validate_backup
    if path is not None:
        candidates = [path]
    else:
        folder = ROOT.parent / (ROOT.name + '_respaldos')
        candidates = sorted(folder.glob('DCC_ESTABLE_14_3_6_*.zip'), reverse=True)
    if not candidates:
        raise RuntimeError('No se encontro un respaldo. Ejecuta el Paso 14.3.6A.')
    for p in candidates:
        try:
            manifest = validate_backup(p)
        except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError):
            if path is not None:
                raise
            continue
        recorded = manifest['archivos']
        if any(rel not in recorded for rel in PROTECTED):
            if path is not None:
                raise RuntimeError('Respaldo no contiene todos los archivos protegidos.')
            continue
        drift = [rel for rel in PROTECTED
                 if not (ROOT / rel).is_file() or
                    hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() !=
                    recorded[rel]['sha256']]
        if drift:
            raise RuntimeError('Archivos importantes cambiaron desde el respaldo: '
                               + ', '.join(drift))
        print('[OK] Respaldo integro y modulos protegidos coinciden:', p, flush=True)
        return p
    raise RuntimeError('No hay respaldo verificable del Paso 14.3.6A.')


def _validate_config_target():
    data = ROOT / 'data'
    if data.is_symlink() or not data.is_dir() or CONFIG.is_symlink():
        raise RuntimeError('Ruta de configuracion insegura.')
    if CONFIG.exists():
        leer_modo()  # Abortamos si alguien creo un JSON con otro esquema.


def activate(backup: Path | None):
    _validate_config_target()
    # Verificar respaldo ANTES de empezar pruebas, y volver a comprobar al final.
    find_and_verify_backup(backup)
    preflight()
    find_and_verify_backup(backup)
    _validate_config_target()
    # Solo escribe UN archivo nuevo de configuracion. No toca codigo original.
    payload = json.dumps({'formato': FORMATO, 'modo': 'optimizado'}, indent=2)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8',
                                     dir=CONFIG.parent, prefix='.modo_14_3_6B_',
                                     suffix='.tmp', delete=False) as file:
        temporary = Path(file.name)
        try:
            file.write(payload + '\n')
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, CONFIG)
    finally:
        temporary.unlink(missing_ok=True)
    assert leer_modo() == 'optimizado'
    print('[OK] Modo OPTIMIZADO activado para NUEVAS simulaciones del selector.', flush=True)
    print('Los visores anteriores SIGUEN usando sus clases originales.', flush=True)
    print('Reversion: python gestionar_modo_14_3_6B.py revertir', flush=True)


def revert():
    _validate_config_target()
    CONFIG.unlink(missing_ok=True)  # Ausencia = original, el estado más seguro.
    assert leer_modo() == 'original'
    print('[OK] Selector revertido a ORIGINAL; no se altero ningun modulo.', flush=True)
    print('Las simulaciones ya iniciadas NO cambian de modo retroactivamente.', flush=True)


def main():
    p = argparse.ArgumentParser(description='Paso 14.3.6B: selector opt-in')
    sub = p.add_subparsers(dest='comando', required=True)
    sub.add_parser('estado')
    sub.add_parser('probar')
    a = sub.add_parser('activar')
    a.add_argument('modo', choices=['optimizado'])
    a.add_argument('--respaldo', type=Path, help='ZIP verificado del Paso 14.3.6A')
    sub.add_parser('revertir')
    args = p.parse_args()
    if args.comando == 'estado':
        print('Modo configurado:', leer_modo())
        print('Ruta de config:', CONFIG)
        print('NOTA: solo nuevas instancias creadas mediante selector_modo_14_3_6B leen este modo.')
    elif args.comando == 'probar':
        preflight()
    elif args.comando == 'activar':
        activate(args.respaldo)
    else:
        revert()


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print('[ERROR]', exc, flush=True)
        print('No se ha confirmado ningun cambio de modo.', flush=True)
        sys.exit(1)
    except KeyboardInterrupt:
        print('Interrumpido. Revisa el estado antes de continuar.', flush=True)
        sys.exit(130)
