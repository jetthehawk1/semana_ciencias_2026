"""Paso 10: ejecutar python test_simulacion_humo.py desde la raiz."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from simulation.fire_simulation import FireSimulation
from simulation.smoke_simulation import SmokeSimulation, FireSmokeSimulation


def must_fail(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('Se acepto una operacion invalida.')


# 1. El fuego emite humo en su propia celda, sin afectar al fuego.
terrain = [
    ['floor'] * 5,
    ['floor'] * 5,
    ['floor', 'floor', 'building', 'floor', 'floor'],
    ['floor'] * 5,
    ['floor'] * 5,
]
fire = FireSimulation(terrain, seed=10,
    spread_chances={'building': 0, 'grass': 0},
    burn_durations={'building': 1, 'grass': 1})
engine = FireSmokeSimulation(fire, emission_rate=0.8,
    diffusion_rate=0.4, decay_rate=0.1, epsilon=0)
engine.ignite(2, 2)
engine.step()
assert fire.turn == engine.smoke.turn == 1
assert fire.stats()['burning'] == 0 and fire.stats()['burned'] == 1
assert abs(engine.smoke.concentration_at(2, 2) - 0.8) < 1e-10
assert engine.smoke.concentration_at(2, 1) == 0
assert engine.smoke.concentration_at(1, 1) == 0
engine.step()
assert fire.turn == engine.smoke.turn == 2
assert 0 < engine.smoke.concentration_at(2, 1) < 0.8
assert 0 < engine.smoke.concentration_at(3, 2) < 0.8
assert engine.smoke.concentration_at(1, 1) == 0  # sin difusion diagonal directa
assert fire.stats()['burning'] == 0
assert fire.terrain[2][3] == 'floor'   # el humo cruza piso NO combustible
print('Emision de humo por el fuego y dispersion cardinal: correctas.')

# 2. Cuando el incendio se apaga, el humo se disipa gradualmente.
initial_total = engine.smoke.stats()['total_concentration']
for _ in range(25):
    engine.step()
assert engine.smoke.stats()['total_concentration'] < initial_total
assert engine.smoke.stats()['max_concentration'] < 0.1
assert not fire.burning and len(fire.burned) == 1
print('Disipacion al apagarse el incendio: correcta.')

# 3. Conservacion de cantidad si no hay fuentes ni disipacion ni saturacion.
s = SmokeSimulation(3, 3, emission_rate=0.5,
    diffusion_rate=0.75, decay_rate=0, max_concentration=10, epsilon=0)
s.step([(0, 0)])
before = sum(sum(row) for row in s.concentrations)
s.step()
after = sum(sum(row) for row in s.concentrations)
assert abs(before-after) < 1e-9
assert s.concentration_at(1, 0) > 0 and s.concentration_at(0, 1) > 0
assert s.concentration_at(1, 1) == 0  # diagonal no en el segundo turno
s.reset()
assert s.turn == 0 and s.stats()['total_concentration'] == 0
print('Conservacion sin disipacion, bordes y reinicio: correctos.')

# 4. Limites de seguridad, normalizacion y entradas invalidas.
maxed = SmokeSimulation(1, 1, emission_rate=1, diffusion_rate=1, decay_rate=0)
for _ in range(6):
    maxed.step([(0, 0)])
assert maxed.concentration_at(0, 0) == 1.0
must_fail(lambda: maxed.concentration_at(-1, 0))
must_fail(lambda: maxed.concentration_at(True, 0))
must_fail(lambda: maxed.step([(1, 0)]))
must_fail(lambda: SmokeSimulation(0, 1))
must_fail(lambda: SmokeSimulation(2, False))
must_fail(lambda: SmokeSimulation(2, 2, diffusion_rate=1.1))
must_fail(lambda: SmokeSimulation(2, 2, decay_rate=-0.1))
must_fail(lambda: SmokeSimulation(2, 2, emission_rate=float('nan')))
must_fail(lambda: SmokeSimulation(2, 2, max_concentration=0))
must_fail(lambda: SmokeSimulation(2, 2, epsilon=2))
print('Limites de concentracion y parametros invalidos: correctos.')

# 5. Mapa real, foco inicial de E30, reproduccion determinista.
path = ROOT / 'data' / 'campus.json'
a = FireSmokeSimulation.from_campus_json(path, seed=2026)
b = FireSmokeSimulation.from_campus_json(path, seed=2026)
assert (a.fire.width, a.fire.height) == (160, 100)
assert a.fire.terrain[55][78] == 'building'
assert a.fire.terrain[0][0] == 'grass' and not a.fire.combustible[0][0]
a.ignite(78, 55)
b.ignite(78, 55)
spread_outside_fuel = False
for _ in range(35):
    assert a.step() == b.step()
    assert a.fire.burning == b.fire.burning and a.fire.burned == b.fire.burned
    assert a.smoke.concentrations == b.smoke.concentrations
    assert a.smoke.turn == a.fire.turn
    if any(a.smoke.concentrations[y][x] >= 0.05 and
           not a.fire.combustible[y][x]
           for y in range(a.fire.height) for x in range(a.fire.width)):
        spread_outside_fuel = True
assert spread_outside_fuel, 'El humo deberia cruzar celdas no combustibles.'
assert a.fire.total_ignitions == 289
assert a.smoke.stats()['smoky_cells'] > 0
assert a.smoke.stats()['max_concentration'] <= 1
print('Campus real: 160 x 100; E30 (78, 55); 35 turnos reproducibles.')
print('Humo sobre pisos/calles; incendio y mapa sin modificaciones: correctos.')
print('Celdas con humo:', a.smoke.stats()['smoky_cells'])
print('Concentracion maxima:', a.smoke.stats()['max_concentration'])
print('Paso 10 completado correctamente.')
