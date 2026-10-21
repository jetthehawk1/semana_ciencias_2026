"""Ejecutar desde la raiz: python test_centro_evacuacion.py"""
from __future__ import annotations

from collections import Counter
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from simulation.evacuation_control import EvacuationControlCenter


def debe_fallar(accion):
    try:
        accion()
    except ValueError:
        return
    raise AssertionError('Se acepto una operacion no permitida')


def crear():
    return EvacuationControlCenter(
        ROOT / 'data/campus.json',
        ROOT / 'data/building_entrances.json',
        ROOT / 'data/ocupacion_ejemplo.json',
    )


sim = crear()
initial = {p.person_id: p.position for p in sim.people}
report = sim.summary()
assert report['fase'] == 'preparado'
assert report['inicial'] == report['dentro'] == 100
assert report['salieron'] == 0 and report['turnos'] == 0
assert (sim.manager.width, sim.manager.height) == (160, 100)
assert Counter(sim.origin.values()) == Counter({'E1':30, 'E10':20, 'E15':25, 'E25':15, 'E30':10})
assert all(p.status == 'normal' for p in sim.people)
assert sim.step() == 0
assert initial == {p.person_id: p.position for p in sim.people}
debe_fallar(sim.pause)
debe_fallar(lambda: sim.save_report(ROOT / 'reporte_no_debe_crearse.json'))
print('Poblacion inicial: 100 personas, todas dentro de sus edificios y en estado normal.')

sim.start_alarm()
assert sim.phase == 'en_curso'
assert all(p.status == 'evacuando' for p in sim.people)
debe_fallar(sim.start_alarm)
sim.pause()
assert sim.step() == 0
assert initial == {p.person_id: p.position for p in sim.people}
assert sim.step(manual=True) > 0
assert sim.phase == 'pausado'
assert sim.summary()['turnos'] == 1
sim.resume()
assert sim.phase == 'en_curso'
print('Alarma, pausa, paso manual y reanudacion: correctos.')

prev = {p.person_id: p.position for p in sim.people}
for _ in range(250):
    sim.step()
    now = {p.person_id: p.position for p in sim.people}
    assert len(now) == len(set(now.values())), 'Colision detectada'
    for pid in now:
        old, new = prev[pid], now[pid]
        assert abs(old[0]-new[0])+abs(old[1]-new[1]) <= 1, 'Movimiento invalido'
    prev = now
    if sim.phase == 'completado':
        break
stats = sim.summary()
assert stats['fase'] == 'completado' and stats['dentro'] == 0
assert stats['salieron'] == stats['inicial'] == 100
assert all(p.building_id is None and p.status == 'evacuando' for p in sim.people)
assert sum(x['salieron'] for x in stats['por_edificio'].values()) == 100
assert all(x['ultimo_cruce_turno'] is not None for x in stats['por_edificio'].values())
assert len(sim.log) == stats['turnos'] + 1
assert sim.step() == 0
print(f'Las 100 personas cruzaron sus puertas en {stats["turnos"]} turnos.')
print('Sin colisiones, diagonales ni personas marcadas erroneamente como a_salvo.')
print('Resumen por edificio:')
for name, row in stats['por_edificio'].items():
    print(f'  {name}: {row["salieron"]}/{row["inicial"]} salieron, ultimo cruce: turno {row["ultimo_cruce_turno"]}')

with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / 'reportes' / 'evacuacion.json'
    assert sim.save_report(path) == path
    exported = json.loads(path.read_text(encoding='utf-8'))
    assert exported['resumen'] == stats
    assert len(exported['historial']) == len(sim.log)
    assert exported['advertencia'].startswith('Los turnos no son segundos')
print('Reporte JSON e historial por turno: correctos.')

sim.reset()
assert sim.phase == 'preparado' and sim.summary()['turnos'] == 0
assert {p.person_id: p.position for p in sim.people} == initial
assert all(p.status == 'normal' for p in sim.people)
print('Reinicio reproducible: correcto.')
print('Paso 8.13 completado correctamente.')
