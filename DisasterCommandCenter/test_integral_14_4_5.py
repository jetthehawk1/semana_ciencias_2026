"""Pruebas adicionales del Paso 14.4.5, ejecutadas SOLO en copia temporal.

Verifica paridad real entre modos, invariantes de ocupacion, pausa/manual,
cambios de viento, foco adicional, aislamiento de sesiones, exportacion y
reversion de configuracion por instancia. No importa Pygame.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from dcc_app.model import load_campus
from dcc_app.mode_scene import ModeSensorScene
from selector_modo_14_3_6B import FORMATO, leer_modo


def signature(s):
    people = tuple((p.person_id, p.x, p.y, p.building_id, p.status)
                   for p in s.people)
    result = (s.info, people, s.sensor_stats, s.current_readings,
              tuple(s.reading_history))
    if s.is_emergency:
        e = s.environment
        result += (tuple(sorted(e.fire.burning.items())),
                   tuple(sorted(e.fire.burned)),
                   tuple(tuple(r) for r in e.smoke.concentrations),
                   tuple((pid, r.dose, r.level, r.peak_smoke, r.fire_contact)
                         for pid, r in sorted(s.exposure.records.items())))
    return result


def invariant(s, snap):
    coords = [(p.x, p.y) for p in s.people]
    assert len(s.people) == 100 and len(set(coords)) == 100, 'Personas duplicadas o colision'
    assert all(0 <= x < snap.width and 0 <= y < snap.height for x,y in coords)
    assert s.info['salieron'] + s.info['dentro'] == 100, 'Conteo inconsistente'
    assert all(p.status != 'a_salvo' for p in s.people), 'Salida no implica zona segura'
    for p in s.people:
        if p.building_id is None:
            assert s.center.manager.is_transitable(p.x, p.y)
        else:
            assert s.center.manager.building_at(p.x, p.y) == p.building_id
    if s.mode == 'optimizado':
        s.center.manager.assert_index_consistent()
    if s.is_emergency:
        assert len(s.sensor_positions) == 12
        assert s.sensor_stats['total_records'] == len(s.reading_history)
        assert len({(r['turn'],r['sensor_id']) for r in s.reading_history}) == len(s.reading_history)


def pair(kind, snap):
    first = ModeSensorScene(ROOT, kind=kind, mode='original')
    second = ModeSensorScene(ROOT, kind=kind, mode='optimizado')
    assert signature(first) == signature(second)
    for scene in (first, second):
        invariant(scene, snap)
        scene.start()
    assert signature(first) == signature(second)

    # Pausar NO ejecuta turnos ni genera registros; paso manual ejecuta UNO.
    for scene in (first, second):
        scene.toggle_pause()
        before = signature(scene)
        scene.step()
        assert signature(scene) == before, 'Pausa altero el estado'
        scene.step(manual=True)
        assert scene.info['turnos'] == 1
    assert signature(first) == signature(second)
    for scene in (first, second):
        scene.toggle_pause()
    target = 35 if kind == 'emergencia' else 31
    for turn in range(2, target+1):
        for scene in (first, second):
            scene.step()
            invariant(scene, snap)
        assert signature(first) == signature(second), f'Diferencia {kind} en turno {turn}'
    assert first.info['turnos'] == target
    if kind == 'normal':
        assert first.info['salieron'] == 100
        assert first.sensor_stats['total_records'] == 0
    else:
        assert (first.info['salieron'], first.info['dentro']) == (91, 9)
        assert first.info['riesgo']['incapacitada'] == 9
        assert first.sensor_stats['total_records'] == 432
        assert set(r['turn'] for r in first.reading_history) == set(range(36))
        # Exportar ambos modos por separado, sin escribir archivos del proyecto.
        with tempfile.TemporaryDirectory(prefix='dcc_export_1445_') as temp:
            for scene in (first, second):
                out = scene.export_readings(Path(temp) / scene.mode)
                assert set(out) == {'csv','jsonl','manifest'}
                with out['csv'].open(newline='', encoding='utf-8') as f:
                    csv_rows = list(csv.DictReader(f))
                with out['jsonl'].open(encoding='utf-8') as f:
                    rows = [json.loads(line) for line in f]
                manifest = json.loads(out['manifest'].read_text(encoding='utf-8'))
                assert len(csv_rows) == len(rows) == manifest['records'] == 432
                assert manifest['sensor_count'] == 12 and manifest['turn_count'] == 36
                assert manifest['metadata']['person_manager_mode'] == scene.mode
                assert rows == scene.reading_history, 'JSONL perdio campos o datos'
    for scene in (first, second):
        scene.reset()
        assert scene.info['fase'] == 'preparado'
        assert scene.sensor_stats['total_records'] == 0
        scene.start()
        if kind == 'emergencia':
            assert scene.sensor_stats['total_records'] == 12
    assert signature(first) == signature(second)
    print(f'[OK] Final {kind}: original/optimizado iguales, {target} turnos, '
          f'fuera={100 if kind == "normal" else 91}, sensores={0 if kind == "normal" else 432}; '
          'pausa, avance manual, exportacion y reinicio.', flush=True)


def change_hazards(snap):
    a = ModeSensorScene(ROOT, kind='emergencia', mode='original')
    b = ModeSensorScene(ROOT, kind='emergencia', mode='optimizado')
    for s in (a,b): s.start()
    ignition = None
    for y in range(snap.height):
        for x in range(snap.width):
            if a.environment.fire.can_ignite(x,y) and (x,y) != (78,55):
                ignition = (x,y)
                break
        if ignition: break
    assert ignition is not None, 'No hay combustible para segundo foco'
    for s in (a,b):
        s.ignite(*ignition)
        s.set_wind('N', 0.55)
        assert s.direction == 'N' and s.intensity == .55
    for turn in range(1,11):
        for s in (a,b):
            s.step()
            invariant(s, snap)
        assert signature(a) == signature(b), f'Diferencia con segundo foco en {turn}'
    assert a.sensor_stats['total_records'] == 12*11
    print('[OK] Segundo foco y cambio de viento: equivalencia, 10 turnos y 132 lecturas.',flush=True)


def checks_modes():
    with tempfile.TemporaryDirectory(prefix='dcc_modos_1445_') as temp:
        config = Path(temp)/'modo_ejecucion_14_3_6B.json'
        # Ausente: original, aun cuando el proyecto tiene optimizado activo.
        assert leer_modo(config) == 'original'
        scene = ModeSensorScene(ROOT, configuracion=config)
        assert scene.mode == 'original'
        try:
            scene.cycle_mode()
        except ValueError:
            pass
        else:
            raise AssertionError('Se activo optimizado sin autorizacion')
        config.write_text(json.dumps({'formato':FORMATO,'modo':'optimizado'}),encoding='utf-8')
        other = ModeSensorScene(ROOT, configuracion=config)
        assert other.mode == 'optimizado'
        assert other.cycle_mode() == 'original'
        assert json.loads(config.read_text(encoding='utf-8'))['modo'] == 'optimizado'
        assert other.cycle_mode() == 'optimizado'
        other.start()
        try:
            other.set_mode('original')
        except ValueError:
            pass
        else:
            raise AssertionError('Permitio cambiar modo tras activar alarma')
        other.reset()
        assert other.mode == 'optimizado'
        config.unlink()
        assert leer_modo(config) == 'original'
        assert ModeSensorScene(ROOT, configuracion=config).mode == 'original'
        config.write_text('JSON corrupto', encoding='utf-8')
        try:
            ModeSensorScene(ROOT, configuracion=config)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Config corrupta no rechazada')
    print('[OK] Reversion: config temporal original, autorizacion, bloqueo en alarma, reset y rechazo de JSON corrupto.',flush=True)


def original_hashes():
    files = list(ROOT.glob('*.py'))
    for folder in ('src','data'):
        files.extend((ROOT/folder).rglob('*.py'))
        files.extend((ROOT/folder).rglob('*.json'))
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in set(files) if p.is_file()}


def main():
    before = original_hashes()
    print('=== PASO 14.4.5: ENSAYO FUNCIONAL FINAL ===', flush=True)
    snap = load_campus(ROOT/'data/campus.json', ROOT/'data/building_entrances.json')
    assert (snap.width,snap.height,snap.building_count,len(snap.entrances)) == (160,100,55,55)
    print('[OK] Campus 160x100, 55 edificios y 55 accesos.',flush=True)
    pair('normal', snap)
    pair('emergencia', snap)
    change_hazards(snap)
    checks_modes()
    assert before == original_hashes(), 'Un archivo Python/JSON original ha cambiado'
    print(f'[OK] Codigo y JSON originales sin cambios: {len(before)}.',flush=True)
    print('Paso 14.4.5: ENSAYO FUNCIONAL APROBADO EN COPIA.',flush=True)

if __name__ == '__main__':
    main()
