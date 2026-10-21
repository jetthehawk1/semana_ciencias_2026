"""Paso 8.12: ejecutar desde la raiz: python test_salida_edificios.py"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from simulation.person import Person
from simulation.indoor_people import IndoorPersonManager
from simulation.indoor_population import IndoorPopulationDistributor, load_population_config
from simulation.indoor_evacuation import IndoorEvacuationController

MAP = ROOT / 'data' / 'campus.json'
DOORS = ROOT / 'data' / 'building_entrances.json'
CONFIG = ROOT / 'data' / 'ocupacion_ejemplo.json'


def must_fail(action, label):
    try:
        action()
    except ValueError:
        return
    raise AssertionError('Se acepto una operacion invalida: ' + label)


def build(counts=None):
    manager = IndoorPersonManager.from_json(MAP)
    config = load_population_config(CONFIG)
    dist = IndoorPopulationDistributor(manager, DOORS)
    people = dist.distribute(counts or config['building_counts'], seed=config['seed'])
    controller = IndoorEvacuationController(manager, DOORS)
    return manager, people, controller


manager, people, controller = build()
assert (manager.width, manager.height) == (160, 100)
assert len(manager.building_ids) == 55
assert len(people) == 100
assert Counter(p.building_id for p in people) == Counter({
    'E1': 30, 'E10': 20, 'E15': 25, 'E25': 15, 'E30': 10
})
assert all(p.status == 'evacuando' for p in people)
print('Campus: 160 x 100; accesos registrados: 55; personas: 100.')

# Pausar evita cualquier movimiento; reanudar vuelve a permitirlo.
initial = {p.person_id: p.position for p in people}
controller.pause()
assert controller.step() == 0
assert {p.person_id: p.position for p in people} == initial
controller.resume()

# Recorrer turnos con verificaciones por PERSONA (ningun salto o diagonal).
previous = initial
seen_exit = set()
for turn in range(250):
    controller.step()
    current = {p.person_id: p.position for p in people}
    assert len(set(current.values())) == len(people), f'Colision durante el turno {turn}'
    for p in people:
        old = previous[p.person_id]
        new = p.position
        assert abs(old[0]-new[0]) + abs(old[1]-new[1]) <= 1, (p.person_id, old, new)
        if p.building_id is not None:
            assert manager.building_at(*new) == p.building_id, p.person_id
        else:
            assert manager.is_transitable(*new), p.person_id
            seen_exit.add(p.person_id)
        assert p.status == 'evacuando', 'Salir del edificio NO es llegar a una zona segura.'
    previous = current
    if controller.inside_count == 0:
        break

assert len(seen_exit) == len(people), f'Faltan salidas: {len(people)-len(seen_exit)}'
assert controller.exited_count == 100
assert controller.inside_count == 0
assert all(p.building_id is None for p in people)
print(f'100 personas salieron por puertas registradas en {controller.steps} turnos.')
print('Sin colisiones, teletransportes, diagonales ni paredes atravesadas.')
print('Estado al salir: evacuando (NO a_salvo), correcto.')

# Caso especifico: puerta ocupada -> espera sin atravesar ni desplazar al ocupante.
small = IndoorPersonManager.from_json(MAP)
doors = json.loads(DOORS.read_text(encoding='utf-8'))
entry = next(a for a in doors['accesses'] if a['building'] == 'E1')
inner = (entry['interior_cell']['x'], entry['interior_cell']['y'])
outer = (entry['exterior_cell']['x'], entry['exterior_cell']['y'])
small.add_person(Person('I001', *inner, building_id='E1'))
small.add_person(Person('O001', *outer))
blocker = small.get_person('O001')
blocked = IndoorEvacuationController(small, DOORS)
assert blocked.step() == 0
assert small.get_person('I001').position == inner
assert small.get_person('I001').building_id == 'E1'
assert blocker.position == outer
# El movimiento interior general sigue restringido.
must_fail(lambda: small.move_person('I001', outer[0]-inner[0], outer[1]-inner[1]),
          'puerta con move_person normal')
# Despejar la salida por un paso exterior valido.
ox, oy = outer
moved = False
for dx, dy in ((-1, 0), (1, 0), (0, 1), (0, -1)):
    try:
        small.move_person('O001', dx, dy)
        moved = True
        break
    except ValueError:
        continue
assert moved
assert blocked.step() == 1
assert small.get_person('I001').position == outer
assert small.get_person('I001').building_id is None
print('Puerta ocupada: espera; puerta libre: cruce permitido.')

# Un archivo con un acceso mal ubicado debe rechazarse.
bad_data = json.loads(DOORS.read_text(encoding='utf-8'))
bad_data['accesses'][0]['exterior_cell'] = dict(bad_data['accesses'][0]['interior_cell'])
with tempfile.TemporaryDirectory() as temp:
    path = Path(temp) / 'bad_doors.json'
    path.write_text(json.dumps(bad_data), encoding='utf-8')
    invalid_manager = IndoorPersonManager.from_json(MAP)
    must_fail(lambda: IndoorEvacuationController(invalid_manager, path),
              'acceso mal ubicado')
print('Validacion de puertas incorrectas: correcta.')
print('Paso 8.12 completado correctamente.')
