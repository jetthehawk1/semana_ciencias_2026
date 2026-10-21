"""Pruebas Paso 12: desde la carpeta principal: python test_efectos_personas.py"""
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))

from simulation.person import Person
from simulation.hazard_impact import (
    ExposureTracker, FireEvacuationControlCenter,
)

MAP = ROOT / 'data' / 'campus.json'
DOORS = ROOT / 'data' / 'building_entrances.json'
POP = ROOT / 'data' / 'ocupacion_ejemplo.json'


def new(**kwargs):
    return FireEvacuationControlCenter(MAP, DOORS, POP, **kwargs)


def must_fail(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError('Se acepto una operacion invalida.')


# 1) Comportamiento numerico puro (sin editar Person).
p = Person('PTEST', 0, 0)
t = ExposureTracker([p], warning=.3, slow=1., blocked=2.)
smoke = [[0.4]]
t.update([p], set(), smoke)
assert t.records['PTEST'].level == 'alerta'
t.update([p], set(), smoke)
assert t.records['PTEST'].level == 'alerta'
t.update([p], set(), smoke)
assert t.records['PTEST'].level == 'ralentizada'
t.update([p], set(), smoke)
t.update([p], set(), smoke)
assert t.records['PTEST'].level == 'incapacitada'
assert p.status == 'normal'  # Riesgo independiente de estado de evacuacion.
t.update([p], set(), [[0.0]])
assert t.records['PTEST'].level == 'incapacitada'  # Estado absorbente.
must_fail(lambda: ExposureTracker([p], warning=2, slow=1, blocked=3))
must_fail(lambda: ExposureTracker([p, p]))
f = ExposureTracker([p])
f.update([p], {(0, 0)}, [[0.0]])
assert f.records['PTEST'].fire_contact
assert f.records['PTEST'].level == 'incapacitada'
print('Exposicion acumulada, lentitud y contacto con fuego: correctos.')


# 2) En ausencia de fuego, no se altera la evacuacion de referencia.
quiet = new(ignition=None, intensity=0)
assert quiet.phase == 'preparado'
assert all(p.status == 'normal' for p in quiet.people)
assert quiet.step() == 0
quiet.start_alarm()
for turn in range(70):
    if quiet.phase == 'completado':
        break
    quiet.step()
assert quiet.phase == 'completado'
assert quiet.summary()['salieron'] == 100
assert quiet.summary()['dentro'] == 0
assert quiet.summary()['riesgo']['normal'] == 100
assert quiet.summary()['turnos'] == 31
assert all(p.status == 'evacuando' for p in quiet.people)
print('Sin incendio: 100 personas cruzaron puertas en 31 turnos, como en Paso 8.13.')


# 3) Integracion real, con viento y fuego inicial en E30.
a = new(direction='E', intensity=.75)
b = new(direction='E', intensity=.75)
assert len(a.people) == 100
assert (a.manager.width, a.manager.height) == (160, 100)
assert a.environment.fire.can_ignite(78, 55)
must_fail(lambda: a.ignite(78, 55))  # Antes de alarma.
a.start_alarm()
b.start_alarm()
assert (78,55) in a.environment.fire.burning
assert all(p.status == 'evacuando' for p in a.people)
for n in range(55):
    result_a = a.step()
    result_b = b.step()
    assert result_a == result_b
    assert a.summary() == b.summary()
    assert [(p.person_id, p.position, p.building_id) for p in a.people] == [
        (p.person_id, p.position, p.building_id) for p in b.people]
    assert len({p.position for p in a.people}) == 100
    for p in a.people:
        assert 0 <= p.x < 160 and 0 <= p.y < 100
        if p.building_id:
            assert a.manager.building_at(*p.position) == p.building_id
        else:
            assert a.manager.is_transitable(*p.position)
        assert p.status != 'a_salvo'
    if a.phase == 'completado':
        break
assert a.environment.fire.total_ignitions > 1
assert a.environment.smoke.stats()['smoky_cells'] > 0
assert sum(a.summary()['riesgo'].values()) == 100
print('Incendio E30, humo, viento, 100 personas y ausencia de colisiones: correctos.')

# 3b) Contacto con fuego: se inmoviliza y la posicion continua ocupada.
d = new(ignition=None, intensity=0)
d.start_alarm()
victim = d.people[0]
initial = victim.position
d.ignite(*initial)
d.step()
assert d.tracker.records[victim.person_id].fire_contact
assert d.tracker.records[victim.person_id].level == 'incapacitada'
assert victim.position == initial
assert len({p.position for p in d.people}) == 100
# Movimiento ralentizado: no avanza en un turno impar.
slower = new(ignition=None, intensity=0)
slower.start_alarm()
slower.step()  # pasos=1
candidate = next(p for p in slower.people if p.building_id is not None)
previous = candidate.position
slower.tracker.records[candidate.person_id].level = 'ralentizada'
slower.step()  # pasos=1 -> turno de descanso para esta persona
assert candidate.position == previous
print('Inmovilizacion por fuego, ocupacion y movimiento lento: correctos.')


# 4) Pausa e intervalo manual: no hay exposicion en pausa.
c = new()
c.start_alarm()
c.step()
c.pause()
old = c.summary()
assert c.step() == 0
assert c.summary() == old
c.step(manual=True)
assert c.summary()['turnos'] == old['turnos'] + 1
assert c.phase == 'pausado'
c.resume()
assert c.phase == 'en_curso'
c.set_wind('W', .4)
assert c.environment.wind.direction == 'W'
must_fail(lambda: c.set_wind('ZZ', .5))
assert c.environment.wind.direction == 'W'
c.step()
print('Pausa, avance manual, reanudacion y cambio de viento: correctos.')


# 5) Reinicio, dos escenarios separados, exportacion del reporte.
with TemporaryDirectory() as tmp:
    out = Path(tmp) / 'reporte.json'
    saved = c.save_report(out)
    report = json.loads(saved.read_text(encoding='utf-8'))
    assert report['paso'] == '12'
    assert len(report['por_persona']) == 100
    assert len(report['historial']) == c.summary()['turnos']+1
    assert report['resumen']['fuego']['turn'] == report['resumen']['humo']['turn']
c.reset()
assert c.phase == 'preparado'
assert all(p.status == 'normal' for p in c.people)
assert all(value.level == 'normal' for value in c.tracker.records.values())
assert not c.environment.fire.burning
assert c.summary()['turnos'] == 0
assert c.environment.wind.direction == 'W' and c.environment.wind.intensity == .4
print('Reporte JSON, reinicio y compatibilidad con pasos anteriores: correctos.')
print('Paso 12 completado correctamente.')
