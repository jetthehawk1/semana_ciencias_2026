"""Disaster Command Center - Paso 14.3.6A: respaldo y pruebas PREVIAS.

COMANDOS:
  python preparar_respaldo_14_3_6.py preparar
  python preparar_respaldo_14_3_6.py verificar "RUTA_AL_RESPALDO.zip"

NO reemplaza archivos del proyecto ni habilita el administrador experimental.
- Ejecuta la integracion aislada y 10 regresiones del Paso 14.3.5.
- Si todo pasa, crea un ZIP de codigo, datos, pruebas y recursos (sin .venv/.git)
  FUERA del proyecto, junto a su carpeta.
- Comprueba SHA-256 archivo por archivo y revisa que el proyecto no cambió.
- El ZIP sirve para restauración MANUAL controlada. No restaura automáticamente.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import uuid
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
EXCLUDE_DIRS = {
    '.git', '.venv', 'venv', 'env', 'node_modules', '__pycache__',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', '.tox',
    'build', 'dist', 'exports', 'reports', '.idea', 'backups', 'respaldos',
}
EXCLUDE_FILES = {'.env', '.env.local', '.env.production', 'id_rsa', 'id_ed25519'}
SECRET_EXTENSIONS = {'.pem', '.key', '.p12', '.pfx'}
PREFIX = 'proyecto/'
MARKER = 'Paso 14.3.5 APROBADO EN COPIA.'


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inventory() -> dict[str, dict]:
    """Inventario de archivos reales, no enlaces simbolicos.

    Se respaldan todos los recursos, excepto entornos, cachés, outputs
    regenerables, llaves y carpetas de control de versiones.
    """
    found = {}
    for folder, dirs, files in os.walk(ROOT, topdown=True, followlinks=False):
        base = Path(folder)
        dirs[:] = sorted(d for d in dirs
                         if d not in EXCLUDE_DIRS
                         and not (base / d).is_symlink())
        for name in sorted(files):
            file = base / name
            if (file.is_symlink() or not file.is_file()
                    or name in EXCLUDE_FILES
                    or file.suffix.lower() in SECRET_EXTENSIONS):
                continue
            relative = file.relative_to(ROOT).as_posix()
            found[relative] = {'sha256': sha256(file), 'bytes': file.stat().st_size}
    return found


def check_needed():
    required = (
        'src/simulation/person_manager.py',
        'src/simulation/indoor_people.py',
        'src/simulation/evacuation_control.py',
        'src/simulation/hazard_impact.py',
        'data/campus.json',
        'data/building_entrances.json',
        'data/ocupacion_ejemplo.json',
        'data/sensores_paso_13.json',
        'indexed_indoor_people.py',
        'adaptador_indice_14_3_5.py',
        'test_integracion_aislada_14_3_5.py',
        'ensayar_integracion_14_3_5.py',
        'medir_rendimiento_14_3_3.py',
    )
    missing = [item for item in required if not (ROOT / item).is_file()]
    if missing:
        raise RuntimeError('Faltan archivos necesarios: ' + ', '.join(missing))


def run_preflight():
    print('\n[1/3] Pruebas PREVIAS en copia temporal (Paso 14.3.5)...', flush=True)
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONUTF8'] = '1'
    env.pop('PYTHONPATH', None)
    completed = subprocess.run(
        [sys.executable, '-B', 'ensayar_integracion_14_3_5.py'],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', timeout=600,
        check=False,
    )
    print(completed.stdout.rstrip(), flush=True)
    if completed.returncode != 0 or MARKER not in completed.stdout:
        raise RuntimeError('Las pruebas previas NO fueron aprobadas. No se creará el respaldo.')
    print('[OK] Integracion y 10 regresiones aprobadas en copia.', flush=True)


def validate_backup(path: Path) -> dict:
    with zipfile.ZipFile(path, 'r') as zf:
        bad = zf.testzip()
        if bad:
            raise RuntimeError(f'ZIP dañado: {bad}')
        members = zf.namelist()
        if 'manifest.json' not in members:
            raise RuntimeError('Respaldo sin manifest.json')
        manifest = json.loads(zf.read('manifest.json'))
        if manifest.get('formato') != 'DCC-1436-v1':
            raise RuntimeError('Formato de respaldo desconocido.')
        files = manifest['archivos']
        if not isinstance(files, dict) or not files:
            raise RuntimeError('Manifiesto vacío.')
        expected = set()
        for rel, info in files.items():
            pure = PurePosixPath(rel)
            if not rel or pure.is_absolute() or '..' in pure.parts or rel.startswith('/'):
                raise RuntimeError('Ruta no segura en el manifiesto.')
            stored = PREFIX + rel
            expected.add(stored)
            if stored not in members:
                raise RuntimeError(f'Archivo ausente en respaldo: {rel}')
            content = zf.read(stored)
            if len(content) != info['bytes']:
                raise RuntimeError(f'Tamaño diferente: {rel}')
            if hashlib.sha256(content).hexdigest() != info['sha256']:
                raise RuntimeError(f'SHA-256 diferente: {rel}')
        extras = set(members) - expected - {'manifest.json'}
        if extras:
            raise RuntimeError(f'Archivos inesperados en ZIP: {len(extras)}')
        return manifest


def prepare():
    print('=== PASO 14.3.6A: PRUEBAS PREVIAS Y RESPALDO ===', flush=True)
    print('Proyecto:', ROOT, flush=True)
    print('Este paso NO activa la optimizacion ni modifica los modulos.', flush=True)
    check_needed()
    before = inventory()
    print('Archivos a proteger (codigo, datos y recursos):', len(before), flush=True)
    run_preflight()
    mid = inventory()
    if before != mid:
        raise RuntimeError('Se detectaron cambios en el proyecto durante las pruebas. Se aborta.')
    print('\n[2/3] Creando respaldo FUERA del proyecto...', flush=True)
    target_dir = ROOT.parent / (ROOT.name + '_respaldos')
    target_dir.mkdir(parents=True, exist_ok=True)
    moment = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_UTC')
    target = target_dir / f'DCC_ESTABLE_14_3_6_{moment}_{uuid.uuid4().hex[:8]}.zip'
    pending = target.with_suffix('.zip.parcial')
    manifest = {
        'formato': 'DCC-1436-v1',
        'creado_utc': datetime.now(timezone.utc).isoformat(),
        'proyecto': ROOT.name,
        'alcance': 'Codigo, datos y recursos; no entornos, git, caches, reportes ni secretos',
        'archivos': before,
    }
    try:
        with zipfile.ZipFile(pending, 'x', compression=zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as zf:
            for rel in before:
                zf.write(ROOT / Path(rel), arcname=PREFIX + rel)
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False,
                                                   indent=2, sort_keys=True))
        verified = validate_backup(pending)
        if verified['archivos'] != before:
            raise RuntimeError('Diferencia de manifiesto al verificar respaldo.')
        after = inventory()
        if after != before:
            raise RuntimeError('El proyecto cambió mientras se creaba el respaldo.')
        pending.rename(target)
    except BaseException:
        pending.unlink(missing_ok=True)
        raise
    print(f'[OK] Respaldo SHA-256 verificado: {len(before)} archivos.', flush=True)
    print('Archivo de respaldo:', target, flush=True)
    print('\n[3/3] Estado final:', flush=True)
    print('[OK] Codigo y JSON de origen sin cambios.', flush=True)
    print('[OK] Pruebas antes del respaldo: APROBADAS.', flush=True)
    print('[OK] Respaldo recuperable verificado (extraccion manual a una carpeta NUEVA).', flush=True)
    print('OPTIMIZACION: NO ACTIVADA. Original: sigue siendo el modo del proyecto.', flush=True)
    print('Paso 14.3.6A COMPLETADO: espera confirmacion antes de activar.', flush=True)


def main():
    parser = argparse.ArgumentParser(description='DCC - Paso 14.3.6A')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('preparar', help='Pruebas previas + ZIP verificado fuera del proyecto')
    check = sub.add_parser('verificar', help='Verifica SHA-256 de un respaldo')
    check.add_argument('archivo_zip', type=Path)
    args = parser.parse_args()
    if args.command == 'preparar':
        prepare()
    else:
        verified = validate_backup(args.archivo_zip)
        print('[OK] Respaldo integro:', args.archivo_zip)
        print('[OK] Archivos verificados:', len(verified['archivos']))
        print('Fecha UTC:', verified['creado_utc'])
        print('NO se extrajo ni se modifico ningun archivo.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile,
            subprocess.TimeoutExpired) as error:
        print('\n[ERROR]', error, flush=True)
        print('No se activa la optimizacion. Revisa el error antes de continuar.', flush=True)
        sys.exit(1)
    except KeyboardInterrupt:
        print('\nInterrumpido; optimizacion no activada.', flush=True)
        sys.exit(130)
