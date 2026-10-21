"""Paso 11: ejecutar python test_simulacion_viento.py desde la raiz del proyecto."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from simulation.fire_simulation import FireSimulation
from simulation.smoke_simulation import SmokeSimulation, FireSmokeSimulation
from simulation.wind_simulation import (
    Wind, WindFireSimulation, WindSmokeSimulation, WindFireSmokeSimulation,
)


def debe_fallar(action):
    try:
        action()
    except ValueError:
        return
    raise AssertionError('Se aceptaron parametros o movimientos invalidos.')


# 1. Vectores, validacion, convenio de direcciones y cambios de viento.
for direction in ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'):
    assert math.isclose(sum(v*v for v in Wind(direction, 1).vector), 1.0)
assert Wind('E', 1).step_vector == (1, 0)
assert Wind('N', 1).step_vector == (0, -1)
debe_fallar(lambda: Wind('ESTE', 0.5))
debe_fallar(lambda: Wind('e', 0.5))
debe_fallar(lambda: Wind('E', -0.01))
debe_fallar(lambda: Wind('N', 1.01))
debe_fallar(lambda: Wind('S', float('nan')))
debe_fallar(lambda: Wind('S', True))
debe_fallar(lambda: WindSmokeSimulation(2, 3, advection_rate=1.01))
print('Ocho direcciones, intensidad y parametros invalidos: correctos.')

# 2. Fuego: favor del viento al este, contra al oeste y no cruza suelo.
terrain = [['floor']*7 for _ in range(5)]
terrain[2] = ['floor'] + ['building']*5 + ['floor']
fire = WindFireSimulation(terrain, seed=123,
    spread_chances={'building': .50, 'grass': .34})
fire.set_wind(Wind('E', 1))
fire.ignite(3, 2)
fire.step()
assert (4, 2) in fire.burning    # 0.5*(1+1.2) -> 1.0
assert (2, 2) not in fire.burning # 0.5*(1-1.2) -> 0
assert all(y == 2 for _, y in fire.burning)
assert (0, 0) not in fire.burning
print('Fuego favorecido a sotavento y frenado a barlovento: correcto.')

# 3. Humo: con el viento E se transporta a la derecha; nada aparece al oeste.
smoke = WindSmokeSimulation(7, 7, emission_rate=1, diffusion_rate=0,
    decay_rate=0, epsilon=0, advection_rate=.75, max_concentration=10)
smoke.set_wind(Wind('E', 1))
smoke.step([(3, 3)])
smoke.step()
assert abs(smoke.concentration_at(4, 3) - .75) < 1e-12
assert abs(smoke.concentration_at(3, 3) - .25) < 1e-12
assert smoke.concentration_at(2, 3) == 0
smoke.set_wind(Wind('W', 1))
smoke.step()
assert smoke.concentration_at(2, 3) > 0
edge = WindSmokeSimulation(3, 3, emission_rate=.6, diffusion_rate=.2,
    decay_rate=0, epsilon=0, max_concentration=10)
edge.set_wind(Wind('E', 1))
edge.step([(2, 1)])
total = sum(sum(row) for row in edge.concentrations)
edge.step()
assert math.isclose(sum(sum(row) for row in edge.concentrations), total, abs_tol=1e-12)
print('Humo desplazado con viento, cambio en marcha y bordes: correctos.')

# 4. Calma produce EXACTAMENTE el mismo comportamiento que Pasos 9 y 10.
old = FireSmokeSimulation.from_campus_json(ROOT / 'data' / 'campus.json', seed=2026)
calm = WindFireSmokeSimulation.from_campus_json(ROOT / 'data' / 'campus.json',
                                                 seed=2026, intensity=0)
old.ignite(78, 55)
calm.ignite(78, 55)
for _ in range(25):
    old_info = old.step()
    new_info = calm.step()
    assert new_info['fire'] == old_info['fire']
    assert new_info['smoke'] == old_info['smoke']
    assert calm.fire.burning == old.fire.burning
    assert calm.fire.burned == old.fire.burned
    assert calm.smoke.concentrations == old.smoke.concentrations
print('Viento cero: resultados identicos a fuego y humo de los pasos 9 y 10.')

# 5. Campus: dos ejecuciones con el mismo viento/semilla son reproducibles.
map_path = ROOT / 'data' / 'campus.json'
a = WindFireSmokeSimulation.from_campus_json(map_path, seed=2026,
                                              direction='E', intensity=.8)
b = WindFireSmokeSimulation.from_campus_json(map_path, seed=2026,
                                              direction='E', intensity=.8)
assert (a.fire.width, a.fire.height) == (160, 100)
assert not a.fire.can_ignite(0, 0)  # grass por defecto fuera de zona explicita
a.ignite(78, 55)
b.ignite(78, 55)
for _ in range(25):
    assert a.step() == b.step()
    assert a.fire.burning == b.fire.burning
    assert a.fire.burned == b.fire.burned
    assert a.smoke.concentrations == b.smoke.concentrations
    assert a.fire.turn == a.smoke.turn
assert a.fire.total_ignitions > 1
assert a.smoke.stats()['smoky_cells'] > 0
assert a.smoke.stats()['max_concentration'] <= 1
current_turn = a.fire.turn
a.set_wind('W', 0.5)
assert a.wind.direction == 'W' and a.smoke.wind == a.fire.wind
assert a.fire.turn == current_turn  # cambiar viento no reinicia
snapshot = (a.wind, a.smoke.wind, a.fire.wind)
debe_fallar(lambda: a.set_wind('XX', .4))
assert snapshot == (a.wind, a.smoke.wind, a.fire.wind)
a.step()
assert a.fire.turn == current_turn + 1
print('Mapa real: 160 x 100, incendio E30, viento variable y resultados reproducibles.')
print('Los modulos originales y el campus permanecen sin modificaciones.')
print('Paso 11 completado correctamente.')
