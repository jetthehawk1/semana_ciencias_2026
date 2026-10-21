"""Paso 13: ejecutar en la carpeta del proyecto con python test_sensores.py"""
from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from simulation.hazard_impact import FireEvacuationControlCenter
from simulation.sensor_simulation import VirtualSensorNetwork
from integration.sensor_export import COLUMNS, export_sensor_dataset

MAP = ROOT / "data" / "campus.json"
DOORS = ROOT / "data" / "building_entrances.json"
POPULATION = ROOT / "data" / "ocupacion_ejemplo.json"
SENSORS = ROOT / "data" / "sensores_paso_13.json"


def scenario():
    return FireEvacuationControlCenter(MAP, DOORS, POPULATION,
                                      direction="E", intensity=0.75, seed=2026)


def network(s):
    return VirtualSensorNetwork(s.environment, MAP, SENSORS,
                                run_id="prueba_13", seed=99,
                                temperature_noise=0.10, smoke_noise=0.004)


def must_fail(f):
    try:
        f()
    except ValueError:
        return
    raise AssertionError("Se aceptó un dato o un movimiento inválido.")


s = scenario()
n = network(s)
assert len(n.sensors) == 12
assert len({p.sensor_id for p in n.sensors}) == 12
assert len({(p.x,p.y) for p in n.sensors}) == 12
assert all(s.manager.building_at(p.x, p.y) == p.building_id
           for p in n.sensors if p.building_id is not None)
assert all(s.manager.is_transitable(p.x,p.y) for p in n.sensors
           if p.building_id is None)
print("Mapa: 160 x 100; 12 sensores colocados y validados.")

s.start_alarm()
before = (s.environment.fire.stats(), s.environment.smoke.stats(),
          tuple((p.person_id, p.position) for p in s.people))
first = n.sample()
after = (s.environment.fire.stats(), s.environment.smoke.stats(),
         tuple((p.person_id, p.position) for p in s.people))
assert before == after, "Leer sensores no debe alterar la simulación."
assert len(first) == 12 and set(first[0]) == set(COLUMNS)
assert {r["turn"] for r in first} == {0}
assert any(r["fire_within_2_cells"] for r in first)
assert any(r["temperature_c"] > 55 for r in first)
assert all(r["smoke_index"] <= .00401 for r in first)
must_fail(n.sample)  # Una sola lectura por turno

rows = list(first)
for _ in range(35):
    s.step()
    sample = n.sample()
    assert len(sample) == 12
    rows.extend(sample)
assert len(rows) == 12 * 36
assert {r["turn"] for r in rows} == set(range(36))
assert any(r["smoke_index"] > .3 for r in rows)
assert any(r["alarm"] for r in rows)
assert all(0 <= r["smoke_index"] <= 1 for r in rows)
assert all(r["temperature_c"] > 0 for r in rows)
print("Muestreo de 36 turnos: 432 lecturas sin duplicados, alarma y humo: correctos.")

# Repetibilidad: misma semilla + mismo escenario => mismo dataset.
s2 = scenario()
n2 = network(s2)
s2.start_alarm()
replay = n2.sample()
for _ in range(35):
    s2.step()
    replay.extend(n2.sample())
assert rows == replay
print("Reproducibilidad de semillas y sincronización de humo/fuego: correctas.")

with TemporaryDirectory() as temp:
    folder = Path(temp)
    paths = export_sensor_dataset(rows, folder, metadata={"ignition": "E30"})
    csv_rows = list(csv.DictReader(paths["csv"].open(encoding="utf-8", newline="")))
    json_rows = [json.loads(line) for line in paths["jsonl"].read_text(
        encoding="utf-8").splitlines()]
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert len(csv_rows) == len(json_rows) == 432
    assert json_rows == rows
    assert set(csv_rows[0]) == set(COLUMNS)
    assert csv_rows[0]["turn"] == "0"
    assert manifest["records"] == 432
    assert manifest["sensor_count"] == 12
    assert manifest["turn_count"] == 36
    assert manifest["dataset_kind"] == "synthetic_simulation"
    must_fail(lambda: export_sensor_dataset(rows + rows[0:1], folder))
    must_fail(lambda: export_sensor_dataset([{}], folder))
    config = json.loads(SENSORS.read_text(encoding="utf-8"))
    for edited in (
        lambda t: t[1].update(sensor_id=t[0]["sensor_id"]),
        lambda t: t[0].update(x=160),
        lambda t: t[0].update(building_id="E30"),
        lambda t: t[0].update(x=True),
    ):
        copy = json.loads(json.dumps(config))
        edited(copy["sensors"])
        invalid = folder / "sensores_invalidos.json"
        invalid.write_text(json.dumps(copy), encoding="utf-8")
        must_fail(lambda: VirtualSensorNetwork(s2.environment, MAP, invalid))
    must_fail(lambda: VirtualSensorNetwork(s2.environment, MAP, SENSORS,
                                          temperature_noise=-.1))
print("Exportación CSV/JSONL/manifiesto y rechazo de configuraciones inválidas: correctos.")
print("No se alteraron los módulos de fuego, humo, personas ni evacuación.")
print("Paso 13 completado correctamente (contrato propuesto para Persona 2).")
