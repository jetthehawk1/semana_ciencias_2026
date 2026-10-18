"""Pruebas read-only del selector: ejecutar SOLO en una copia temporal."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from selector_modo_14_3_6B import FORMATO, crear_centro, leer_modo
from indexed_indoor_people import IndexedIndoorPersonManager
from simulation.hazard_impact import FireEvacuationControlCenter
from simulation.sensor_simulation import VirtualSensorNetwork

ROOT = Path(__file__).resolve().parent
MAP = ROOT / 'data/campus.json'
DOORS = ROOT / 'data/building_entrances.json'
POP = ROOT / 'data/ocupacion_ejemplo.json'
SENSORS = ROOT / 'data/sensores_paso_13.json'


def signature(c):
    key = (c.phase, c.summary(), tuple((p.person_id, p.position, p.building_id,
                                        p.status, p.speed) for p in c.people), c.log)
    if isinstance(c, FireEvacuationControlCenter):
        env = c.environment
        key += (tuple(sorted(env.fire.burning)), tuple(sorted(env.fire.burned)),
                env.smoke.concentrations,
                tuple((pid, v.dose, v.level, v.fire_contact, v.peak_smoke)
                      for pid, v in sorted(c.tracker.records.items())))
    return key


def pair(kind: str, config: Path):
    kw = {'ignition': (78, 55), 'direction': 'E', 'intensity': 0.75, 'seed': 2026} if kind == 'emergencia' else {}
    # La configuracion por defecto selecciona modo normal.
    a = crear_centro(kind, MAP, DOORS, POP, modo='original', **kw)
    b = crear_centro(kind, MAP, DOORS, POP, configuracion=config, **kw)
    assert not isinstance(a.manager, IndexedIndoorPersonManager)
    assert isinstance(b.manager, IndexedIndoorPersonManager)
    assert signature(a) == signature(b)
    for c in (a, b):
        c.start_alarm()
    assert signature(a) == signature(b)
    ns = None
    if kind == 'emergencia':
        ns = [VirtualSensorNetwork(c.environment, MAP, SENSORS,
                                   run_id='selector_1436B', seed=2026,
                                   temperature_noise=0.0, smoke_noise=0.0) for c in (a, b)]
        assert ns[0].sample() == ns[1].sample()
        count = 12
    else:
        count = 0
    iterations = 35 if ns else 90
    for turn in range(1, iterations + 1):
        if a.phase == 'completado':
            break
        assert a.step() == b.step()
        assert signature(a) == signature(b), f'Los modos divergen: {kind} turno {turn}'
        b.manager.assert_index_consistent()
        assert len({p.position for p in b.people}) == len(b.people)
        if ns:
            assert ns[0].sample() == ns[1].sample()
            count += 12
    info = a.summary()
    if ns:
        assert (info['turnos'], info['salieron'], info['dentro']) == (35, 91, 9), info
        assert count == 432
    else:
        assert (info['turnos'], info['salieron'], info['dentro']) == (31, 100, 0), info
    print(f'[OK] {kind}: estados por turno iguales; '
          f'turnos={info["turnos"]}; salieron={info["salieron"]}; sensores={count}.')
    for c in (a, b):
        c.reset()
    assert signature(a) == signature(b)
    b.manager.assert_index_consistent()
    print(f'[OK] {kind}: reinicio y sincronizacion equivalentes.')


def main():
    print('=== TEST SELECTOR 14.3.6B EN COPIA ===')
    with tempfile.TemporaryDirectory(prefix='dcc_config_selector_') as td:
        config = Path(td) / 'modo.json'
        assert leer_modo(config) == 'original'
        default = crear_centro('normal', MAP, DOORS, POP, configuracion=config)
        assert not isinstance(default.manager, IndexedIndoorPersonManager)
        assert len(default.people) == 100
        config.write_text(json.dumps({'formato': FORMATO, 'modo': 'optimizado'}), encoding='utf-8')
        assert leer_modo(config) == 'optimizado'
        pair('normal', config)
        pair('emergencia', config)
        config.unlink()  # REVERSION del selector, no de las clases originales
        assert leer_modo(config) == 'original'
        reverted = crear_centro('normal', MAP, DOORS, POP, configuracion=config)
        assert not isinstance(reverted.manager, IndexedIndoorPersonManager)
        assert len(reverted.people) == 100
        print('[OK] Activar optimizado y revertir a original sin sustituir modulos.')
        config.write_text('{corrupto', encoding='utf-8')
        try:
            leer_modo(config)
        except RuntimeError:
            pass
        else:
            raise AssertionError('La configuracion corrupta fue aceptada')
        for bad_mode in ('mix', 'automático'):
            try:
                crear_centro('normal', MAP, DOORS, POP, modo=bad_mode)
            except ValueError:
                pass
            else:
                raise AssertionError('Modo invalido aceptado')
        print('[OK] Configuracion corrupta y modos invalidos rechazados.')
    print('Paso 14.3.6B: SELECTOR APROBADO EN COPIA.')


if __name__ == '__main__':
    main()
