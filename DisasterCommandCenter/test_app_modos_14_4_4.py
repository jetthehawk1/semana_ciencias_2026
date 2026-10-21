"""Paso 14.4.4: equivalencia del selector + sensores + reversion sin modificar codigo.

Se usa configuracion temporal EXTERNA. No activa ni revierte el modo global.
Si Pygame esta instalado, abre dos ventanas SDL dummy de tres fotogramas.
"""
from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'src'))

from selector_modo_14_3_6B import FORMATO, leer_modo
from dcc_app.model import load_campus
from dcc_app.mode_scene import ModeSensorScene
from dcc_app.sensor_scene import SensorLiveScene

NEW = {
    'src/dcc_app/mode_scene.py', 'src/dcc_app/mode_application.py',
    'main_unificado_14_4_4.py', 'test_app_modos_14_4_4.py',
}


def original_hashes():
    files = list(ROOT.glob('*.py'))
    for name in ('src', 'data'):
        for ext in ('*.py', '*.json'):
            files += list((ROOT/name).rglob(ext))
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(set(files)) if p.is_file()
        and str(p.relative_to(ROOT)).replace('\\','/') not in NEW
    }


def state(scene):
    c = scene.center
    people = tuple((p.person_id,p.x,p.y,p.status,p.building_id) for p in scene.people)
    fire = (frozenset(scene.environment.fire.burning),
            frozenset(scene.environment.fire.burned)) if scene.is_emergency else None
    smoke = (tuple(tuple(row) for row in scene.environment.smoke.concentrations)
             if scene.is_emergency else None)
    exposure = (tuple(sorted((key, record.level, record.dose)
                             for key, record in scene.exposure.records.items()))
                if scene.is_emergency else None)
    return (scene.info,people,fire,smoke,exposure,scene.sensor_stats,
            scene.current_readings)


def compare_runs(kind, mode):
    controlled = ModeSensorScene(ROOT, kind=kind, mode=mode)
    baseline = SensorLiveScene(ROOT, kind=kind)
    assert controlled.mode == mode
    assert type(controlled.center).__name__.startswith('Indexed') == (mode == 'optimizado')
    assert state(controlled) == state(baseline)
    controlled.start(); baseline.start()
    assert state(controlled) == state(baseline)
    if kind == 'emergencia':
        assert len(controlled.reading_history) == 12
        assert controlled.sensor_stats['alarms'] >= 1
    controlled.toggle_pause(); baseline.toggle_pause()
    controlled.step(); baseline.step()
    assert state(controlled) == state(baseline), 'Pausa sin avance'
    controlled.step(manual=True); baseline.step(manual=True)
    assert state(controlled) == state(baseline), 'Turno manual'
    controlled.toggle_pause(); baseline.toggle_pause()
    end = 35 if kind == 'emergencia' else 31
    for i in range(1,end):
        controlled.step(); baseline.step()
        assert state(controlled) == state(baseline), f'Divergencia en {mode}/{kind} turno {i+1}'
    assert controlled.reading_history == baseline.reading_history
    assert controlled.info['turnos'] == end
    if kind == 'emergencia':
        assert controlled.info['salieron'] == 91 and controlled.info['dentro'] == 9
        assert controlled.info['riesgo']['incapacitada'] == 9
        assert controlled.sensor_stats['total_records'] == 432
        assert len({(r['turn'],r['sensor_id']) for r in controlled.reading_history}) == 432
    else:
        assert controlled.info['salieron'] == 100
        assert controlled.sensor_stats['total_records'] == 0
    controlled.reset()
    assert controlled.mode == mode and controlled.info['fase'] == 'preparado'
    assert controlled.sensor_stats['total_records'] == 0
    if mode == 'optimizado':
        controlled.center.manager.assert_index_consistent()
    return end, 432 if kind == 'emergencia' else 0


def reversibility(temp: Path):
    config = temp/'modo_ejecucion_14_3_6B.json'
    assert leer_modo(config) == 'original'
    config.write_text(json.dumps({'formato': FORMATO, 'modo':'optimizado'}),encoding='utf-8')
    scene = ModeSensorScene(ROOT, configuracion=config)
    assert scene.mode == 'optimizado'
    assert type(scene.center).__name__ == 'IndexedFireEvacuationControlCenter'
    assert scene.cycle_mode() == 'original'
    assert scene.sensor_stats['total_records'] == 0
    assert json.loads(config.read_text())['modo'] == 'optimizado', 'La app no debe tocar config'
    assert scene.cycle_mode() == 'optimizado'
    scene.start()
    try:
        scene.set_mode('original')
    except ValueError as exc:
        assert 'reinicia' in str(exc)
    else:
        raise AssertionError('Se permitio cambiar modo durante emergencia')
    scene.step()
    scene.reset()
    assert scene.mode == 'optimizado' and scene.sensor_stats['total_records'] == 0
    assert scene.cycle_mode() == 'original'
    scene.start()
    assert scene.sensor_stats['total_records'] == 12
    next_scene = ModeSensorScene(ROOT, configuracion=config)
    assert next_scene.mode == 'optimizado', 'Solo una ventana nueva relee config'
    config.unlink()
    assert leer_modo(config) == 'original'
    scene.reset()  # no cambiar a mitad de alarma
    try:
        scene.cycle_mode()  # escena actualmente original; no elevar sin respaldo validado
    except ValueError as exc:
        assert 'no autorizado' in str(exc)
    else:
        raise AssertionError('Se permitio optimizar tras revertir la configuracion')
    assert ModeSensorScene(ROOT, configuracion=config).mode == 'original'
    config.write_text('{roto', encoding='utf-8')
    try:
        ModeSensorScene(ROOT, configuracion=config)
    except RuntimeError:
        pass
    else:
        raise AssertionError('Se acepto una configuracion corrupta')


def main():
    print('=== PASO 14.4.4: SELECTOR Y APP UNIFICADA ===',flush=True)
    before = original_hashes()
    for rel in NEW:
        p = ROOT/rel
        assert p.is_file(), f'Falta archivo nuevo: {rel}'
        ast.parse(p.read_text(encoding='utf-8'), filename=str(p))
    for req in ('selector_modo_14_3_6B.py','adaptador_indice_14_3_5.py',
                'indexed_indoor_people.py','src/dcc_app/sensor_scene.py',
                'src/dcc_app/sensor_application.py'):
        assert (ROOT/req).is_file(), f'Falta dependencia: {req}'
    snapshot = load_campus(ROOT/'data/campus.json',ROOT/'data/building_entrances.json')
    assert (snapshot.width,snapshot.height,len(snapshot.entrances)) == (160,100,55)
    print('[OK] Archivos nuevos y campus: 160x100, 55 accesos.',flush=True)

    for mode in ('original', 'optimizado'):
        for kind in ('normal','emergencia'):
            turns, readings = compare_runs(kind,mode)
            print(f'[OK] {mode}/{kind}: 100 personas, {turns} turnos, '
                  f'{readings} lecturas; equivalencia exacta de estados y sensores.',flush=True)

    with tempfile.TemporaryDirectory(prefix='dcc_14_4_4_') as folder:
        tmp = Path(folder)
        reversibility(tmp)
        print('[OK] Modo visible por instancia; alternar antes de alarma; '
              'reversion, config intacta y config corrupta rechazada.',flush=True)
        scene=ModeSensorScene(ROOT, mode='optimizado')
        scene.start()
        for i in range(3): scene.step()
        output=scene.export_readings(tmp/'datos')
        with output['csv'].open(newline='',encoding='utf-8') as f:
            rows=list(csv.DictReader(f))
        assert len(rows) == 48
        assert (len(rows),len(output)) == (48,3)
        manifest=json.loads(output['manifest'].read_text(encoding='utf-8'))
        assert manifest['records'] == 48 and manifest['sensor_count'] == 12
        assert manifest['metadata']['person_manager_mode'] == 'optimizado'
        assert manifest['metadata']['application_step'] == '14.4.4'
        print('[OK] Exportacion en modo optimizado: CSV/JSONL/manifiesto, '
              '48 muestras sin duplicar.',flush=True)

    try:
        import pygame  # noqa
    except ImportError:
        print('[AVISO] Pygame no instalado aqui: verificar ventana en Windows.',flush=True)
    else:
        env = os.environ.copy()
        env.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy',
                   PYTHONDONTWRITEBYTECODE='1')
        for extra in (['--modo-original'], []):
            cmd = [sys.executable,'-B',str(ROOT/'main_unificado_14_4_4.py'),
                   '--smoke-test'] + extra
            proc = subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,
                                  text=True,timeout=45)
            assert proc.returncode == 0, proc.stdout+'\n'+proc.stderr
            assert '14.4.4: arranque grafico de 3 fotogramas' in proc.stdout
            expected = 'original' if extra else leer_modo(ROOT/'data'/'modo_ejecucion_14_3_6B.json')
            assert f'modo={expected}' in proc.stdout
            print(f'[OK] Pygame sin pantalla: 3 fotogramas en modo {expected}.',flush=True)

    assert before == original_hashes(), 'Archivos protegidos han cambiado'
    print(f'[OK] Archivos anteriores sin cambios: {len(before)}.',flush=True)
    print('Paso 14.4.4: PRUEBAS APROBADAS. No se modifico el modo guardado.',flush=True)


if __name__ == '__main__':
    main()
