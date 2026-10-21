"""Paso 14.3.5: prueba integrada en COPIA (ejecutada por el lanzador).

Compara centro normal y emergencia E30 con versiones originales.
Incluye pausa, paso manual, reinicio, personas, humo y sensores.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from adaptador_indice_14_3_5 import (  # noqa
    IndexedEvacuationControlCenter,
    IndexedFireEvacuationControlCenter,
)
from indexed_indoor_people import IndexedIndoorPersonManager
from medir_rendimiento_14_3_3 import DISTRIBUCION_500
from simulation.evacuation_control import EvacuationControlCenter
from simulation.hazard_impact import FireEvacuationControlCenter
from simulation.sensor_simulation import VirtualSensorNetwork

MAP = ROOT / 'data' / 'campus.json'
DOORS = ROOT / 'data' / 'building_entrances.json'
SENSORS = ROOT / 'data' / 'sensores_paso_13.json'


def signature(center):
    result = (
        center.phase,
        center.summary(),
        tuple((p.person_id, p.position, p.building_id, p.status, p.speed)
              for p in center.people),
        center.log,
    )
    if isinstance(center, FireEvacuationControlCenter):
        env = center.environment
        result += (
            tuple(sorted(env.fire.burning)),
            tuple(sorted(env.fire.burned)),
            env.smoke.concentrations,
            tuple((pid, rec.dose, rec.level, rec.fire_contact, rec.peak_smoke)
                  for pid, rec in sorted(center.tracker.records.items())),
        )
    return result


def validate(center):
    people = center.people
    assert len(people) == 500
    assert len({p.person_id for p in people}) == 500
    assert len({p.position for p in people}) == 500, 'Colision de celdas'
    assert all(p.status != 'a_salvo' for p in people)
    if isinstance(center.manager, IndexedIndoorPersonManager):
        center.manager.assert_index_consistent()
    for p in people:
        if p.building_id is None:
            assert center.manager.is_transitable(*p.position), p.person_id
        else:
            assert center.manager.building_at(*p.position) == p.building_id, p.person_id


def new_center(kind: str, indexed: bool, config: Path):
    if kind == 'normal':
        cls = IndexedEvacuationControlCenter if indexed else EvacuationControlCenter
        instance = cls(MAP, DOORS, config)
    else:
        cls = IndexedFireEvacuationControlCenter if indexed else FireEvacuationControlCenter
        instance = cls(MAP, DOORS, config, ignition=(78, 55), direction='E',
                       intensity=0.75, seed=2026)
    assert isinstance(instance.manager, IndexedIndoorPersonManager) == indexed
    validate(instance)
    return instance


def network(center):
    return VirtualSensorNetwork(center.environment, MAP, SENSORS,
                                run_id='integracion_14_3_5', seed=2026,
                                temperature_noise=0.0, smoke_noise=0.0)


def compare_pair(a, b, turn: int):
    validate(a)
    validate(b)
    assert signature(a) == signature(b), f'Estados distintos en turno {turn}'


def step_pair(a, b, turn, sensor_a=None, sensor_b=None, manual=False):
    before_turn = a.summary()['turnos']
    assert a.step(manual=manual) == b.step(manual=manual), f'Movimientos diferentes {turn}'
    compare_pair(a, b, turn)
    if sensor_a and a.summary()['turnos'] > before_turn:
        ra = sensor_a.sample()
        rb = sensor_b.sample()
        assert ra == rb, f'Sensores diferentes turno {turn}'
        assert len(ra) == 12
    return 12 if sensor_a and a.summary()['turnos'] > before_turn else 0


def scenario(kind: str, config: Path):
    a = new_center(kind, False, config)
    b = new_center(kind, True, config)
    compare_pair(a, b, 0)
    for center in (a, b):
        center.start_alarm()
    compare_pair(a, b, 0)
    na, nb = (network(a), network(b)) if kind == 'emergencia' else (None, None)
    reads = 0
    if na:
        assert na.sample() == nb.sample()
        reads = 12
    # Pausa, paso manual y reanudación antes del resto de la evacuación.
    for center in (a, b):
        center.pause()
    compare_pair(a, b, 0)
    reads += step_pair(a, b, 0, na, nb)  # No cambia turno, tampoco mueve.
    assert a.summary()['turnos'] == 0
    reads += step_pair(a, b, 1, na, nb, manual=True)
    assert a.summary()['turnos'] == 1
    for center in (a, b):
        center.resume()
    compare_pair(a, b, 1)
    limit = 35 if na else 250
    while a.summary()['turnos'] < limit:
        if kind == 'normal' and a.phase == 'completado':
            break
        next_turn = a.summary()['turnos'] + 1
        reads += step_pair(a, b, next_turn, na, nb)
    info = a.summary()
    assert info['turnos'] == (35 if na else 48), info
    assert info['salieron'] == (455 if na else 500), info
    assert info['dentro'] == (45 if na else 0), info
    if na:
        assert info['riesgo']['incapacitada'] == 9
        assert reads == 12 * (35 + 1), reads  # inicial y 35 turnos (no leer en pausa)
        # Reset mantiene misma geometría, estado de peligro y reindexación.
    print(f'[OK] {kind}: 500 personas; {info["turnos"]} turnos; '
          f'salieron={info["salieron"]}; dentro={info["dentro"]}; '
          'pausa/manual y estados idénticos por turno.', flush=True)
    for center in (a, b):
        center.reset()
    compare_pair(a, b, 0)
    assert a.phase == 'preparado' and len(a.people) == 500
    assert all(p.status == 'normal' for p in a.people)
    for center in (a, b):
        center.start_alarm()
    for turn in range(1, 4):
        step_pair(a, b, turn)
    print(f'[OK] {kind}: reset, reactivacion y sincronizacion del indice.', flush=True)


def main():
    print('=== INTEGRACION OPT-IN EN COPIA AISLADA ===', flush=True)
    assert sum(DISTRIBUCION_500.values()) == 500
    with tempfile.TemporaryDirectory(prefix='dcc_ocupacion_14_3_5_') as td:
        path = Path(td) / 'ocupacion_500.json'
        path.write_text(json.dumps({'seed': 2026, 'id_prefix': 'P',
                                    'building_counts': DISTRIBUCION_500}),
                        encoding='utf-8')
        scenario('normal', path)
        scenario('emergencia', path)
    print('[OK] Integracion aislada: equivalencia, alarmas, reinicios y 12 sensores.')
    print('Paso 14.3.5 - prueba integrada aprobada, no instalada en proyecto principal.')


if __name__ == '__main__':
    main()
