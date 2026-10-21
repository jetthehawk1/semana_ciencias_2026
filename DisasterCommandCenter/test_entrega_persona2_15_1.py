"""Validaciones del contrato Persona 2: sin cambiar codigo ni datos existentes."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from generar_entrega_persona2_15_1 import produce
from integration.persona2_contract_15_1 import read_sensor_package, OBSERVABLE_FIELDS


def sha_snapshot():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in ROOT.rglob('*')
            if p.is_file() and p.suffix in ('.py', '.json')
            and '.venv' not in p.parts and 'exports' not in p.parts
            and '__pycache__' not in p.parts}


def must_fail(callback, what):
    try:
        callback()
    except ValueError:
        return
    raise AssertionError(f'Dataset invalido aceptado: {what}')


def main():
    print('=== PASO 15.1: PRUEBA DE CONTRATO PARA PERSONA 2 ===')
    before = sha_snapshot()
    with TemporaryDirectory(prefix='dcc_persona2_test_') as tmp:
        base = Path(tmp) / 'base'
        info = produce(base)
        manifest = info['manifest']
        obs = info['observables']
        assert len(obs) == 432 and manifest['records'] == 432
        assert manifest['sensor_count'] == 12 and manifest['turn_count'] == 36
        assert manifest['first_turn'] == 0 and manifest['last_turn'] == 35
        assert all(set(r) == set(OBSERVABLE_FIELDS) for r in obs)
        assert all('fire_within_2_cells' not in r for r in obs)
        assert any(r['alarm'] for r in obs)
        assert any(r['smoke_index'] > .3 for r in obs)
        assert len(info['labelled_rows']) == len(obs)
        print('[OK] Exportacion real: 432 lecturas, 12 sensores, turnos 0..35; CSV/JSONL/manifiesto coinciden.')
        print('[OK] Canal observable sin la etiqueta de verdad-terreno.')

        def copied(tag):
            target = Path(tmp) / tag
            shutil.copytree(base, target)
            return target

        # Modificaciones deliberadas sobre copias en carpeta temporal:
        dup = copied('duplicado')
        jsonl = dup / 'lecturas_sensores.jsonl'
        lines = jsonl.read_text(encoding='utf-8').splitlines()
        lines[1] = lines[0]
        jsonl.write_text('\n'.join(lines)+'\n', encoding='utf-8')
        must_fail(lambda: read_sensor_package(dup), 'lectura repetida')

        wrong = copied('manifiesto_falso')
        path = wrong / 'manifiesto_sensores.json'
        data = json.loads(path.read_text(encoding='utf-8'))
        data['records'] = 999
        path.write_text(json.dumps(data), encoding='utf-8')
        must_fail(lambda: read_sensor_package(wrong), 'recuento del manifiesto')

        leaked = copied('dato_modificado')
        path = leaked / 'lecturas_sensores.jsonl'
        records = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines()]
        records[0]['smoke_index'] = 1.5
        path.write_text(''.join(json.dumps(r)+'\n' for r in records), encoding='utf-8')
        must_fail(lambda: read_sensor_package(leaked), 'valor fuera de rango')

        mismatched = copied('identidad')
        path = mismatched / 'lecturas_sensores.csv'
        with path.open(encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            content = list(reader)
        content[0]['sensor_id'] = 'INVENTADO'
        with path.open('w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(content)
        must_fail(lambda: read_sensor_package(mismatched), 'CSV distinto del JSONL')
        print('[OK] Paquetes alterados rechazados: duplicados, recuentos, rangos y formatos divergentes.')

        # Escenario normal no debe inventar muestras de fuego/humo.
        from dcc_app.mode_scene import ModeSensorScene
        normal = ModeSensorScene(ROOT, kind='normal', mode='original')
        normal.start()
        for _ in range(3):
            normal.step()
        assert normal.reading_history == []
        must_fail(lambda: normal.export_readings(Path(tmp) / 'normal'), 'exportacion vacia')
        print('[OK] Escenario normal: cero muestras; exportacion vacia rechazada.')

    after = sha_snapshot()
    assert before == after, 'Se modificaron archivos de codigo o datos durante la prueba.'
    print(f'[OK] Integridad: {len(before)} archivos .py/.json sin cambios.')
    print('PASO 15.1: CONTRATO CON PERSONA 2 APROBADO. Simulador intacto.')


if __name__ == '__main__':
    main()
