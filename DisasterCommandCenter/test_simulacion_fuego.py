"""Disaster Command Center — Paso 9: pruebas de fuego.
Ejecutar desde la raiz del proyecto: python test_simulacion_fuego.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from simulation.fire_simulation import FireSimulation


def must_fail(callback):
    try:
        callback()
    except ValueError:
        return
    raise AssertionError('La operacion invalida no produjo ValueError.')


# TEST 1: reglas basicas, solamente vecinos cardinales y fuego nuevo diferido.
terrain = [
    ['floor', 'floor', 'floor', 'floor', 'floor'],
    ['floor', 'floor', 'building', 'floor', 'floor'],
    ['floor', 'building', 'building', 'building', 'floor'],
    ['floor', 'floor', 'building', 'floor', 'floor'],
    ['floor', 'floor', 'floor', 'floor', 'floor'],
]
test_fire = FireSimulation(terrain, seed=42,
    spread_chances={'building': 1.0, 'grass': 1.0},
    burn_durations={'building': 3, 'grass': 2})
test_fire.ignite(2, 2)
assert test_fire.state_at(2, 2) == 'burning'
result = test_fire.step()
assert result['new_fires'] == 4, result
assert result['burning'] == 5
assert all(test_fire.state_at(*p) == 'burning'
           for p in [(2, 2), (1, 2), (3, 2), (2, 1), (2, 3)])
assert test_fire.state_at(1, 1) == 'unburned'  # diagonal
assert test_fire.state_at(0, 2) == 'unburned'  # floor
for _ in range(3):
    test_fire.step()
assert test_fire.stats()['burning'] == 0
assert test_fire.stats()['burned'] == 5
assert test_fire.stats()['total_ignitions'] == 5
print('Ignicion, propagacion cardinal y agotamiento: correctos.')

# TEST 2: no propagar sin probabilidad y proteger piso/calle.
flat = FireSimulation([['road', 'building', 'building', 'floor']], seed=4,
    spread_chances={'building': 0, 'grass': 0},
    burn_durations={'building': 2, 'grass': 2})
flat.ignite(1, 0)
flat.step()
assert flat.stats()['burning'] == 1
flat.step()
assert flat.stats()['burning'] == 0 and flat.stats()['burned'] == 1
assert flat.state_at(2, 0) == 'unburned'
assert flat.state_at(0, 0) == 'unburned'
assert flat.state_at(3, 0) == 'unburned'
print('Calles, pisos y probabilidad de propagacion: correctos.')

# TEST 3: errores rechazados, modelo no modifica la malla.
must_fail(lambda: flat.ignite(-1, 0))
must_fail(lambda: flat.ignite(0, 0))
must_fail(lambda: flat.ignite(1, 0))  # consumida
must_fail(lambda: flat.ignite(True, 0))
must_fail(lambda: flat.state_at(4, 0))
must_fail(lambda: FireSimulation([['building'], ['floor', 'floor']]))
must_fail(lambda: FireSimulation([['road']], combustible=[[True]]))
must_fail(lambda: FireSimulation([['building']], spread_chances={'building': 1.4, 'grass': .3}))
must_fail(lambda: FireSimulation([['building']], burn_durations={'building': 0, 'grass': 2}))
assert terrain[2][2] == 'building'  # no se modifica la entrada
print('Validacion de coordenadas, terreno y parametros: correcta.')

# TEST 4: mapa real 160 x 100, reconociendo jardines explicitos.
campus_path = ROOT / 'data' / 'campus.json'
data = json.loads(campus_path.read_text(encoding='utf-8'))
fire = FireSimulation.from_campus_json(campus_path, seed=2026)
assert (fire.width, fire.height) == (160, 100)
assert len(data['zones']) == 502
counts = {
    key: sum(cell == key for row in fire.terrain for cell in row)
    for key in ('building', 'grass', 'floor', 'road')
}
assert counts == {'building': 3306, 'grass': 2428, 'floor': 8765, 'road': 1501}, counts
fuel = sum(sum(row) for row in fire.combustible)
assert fuel == 3469, f'Se esperaban 3306 edificios + 163 jardines: {fuel}'
assert sum(fire.terrain[y][x] == 'grass' and fire.combustible[y][x]
           for y in range(fire.height) for x in range(fire.width)) == 163
assert fire.terrain[0][0] == 'grass' and not fire.combustible[0][0]
assert fire.terrain[55][78] == 'building', 'El inicio de demostracion E30 no es un edificio.'
assert fire.terrain[5][151] == 'building', 'La zona E1 no coincide.'

# Dos copias con misma semilla han de producir el mismo fuego.
fire_copy = FireSimulation.from_campus_json(campus_path, seed=2026)
fire.ignite(78, 55)
fire_copy.ignite(78, 55)
for i in range(35):
    result1 = fire.step()
    result2 = fire_copy.step()
    assert result1 == result2
    assert fire.burning == fire_copy.burning and fire.burned == fire_copy.burned
    assert all(fire.combustible[y][x] for x, y in fire.burning)
    assert all(fire.combustible[y][x] for x, y in fire.burned)
    assert len(fire.burning) + len(fire.burned) == fire.total_ignitions
assert fire.total_ignitions > 1, 'El fuego inicial no se propago.'
print('Mapa real: 160 x 100, 502 zonas, 3306 edificios y 163 jardines combustibles.')
print('Semilla reproducible y propagacion dentro del terreno combustible: correctas.')
print('Fuego inicial E30 (78, 55); turnos:', fire.turn,
      '; afectados:', fire.total_ignitions)
print('Paso 9 completado correctamente.')
