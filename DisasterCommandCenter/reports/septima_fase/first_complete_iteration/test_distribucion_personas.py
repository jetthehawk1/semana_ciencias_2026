"""Paso 8.11: ejecutar desde la raiz: python test_distribucion_personas.py"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from simulation.indoor_people import IndoorPersonManager
from simulation.indoor_population import IndoorPopulationDistributor, load_population_config
from simulation.person import Person

CAMPUS = ROOT / "data" / "campus.json"
ACCESOS = ROOT / "data" / "building_entrances.json"
CONFIG = ROOT / "data" / "ocupacion_ejemplo.json"


def build():
    manager = IndoorPersonManager.from_json(CAMPUS)
    distributor = IndoorPopulationDistributor(manager, ACCESOS)
    return manager, distributor


def should_fail(action, name):
    try:
        action()
    except ValueError:
        return
    raise AssertionError("Se acepto una solicitud invalida: " + name)


config = load_population_config(CONFIG)
counts = config["building_counts"]
assert counts == {"E1": 30, "E10": 20, "E15": 25, "E25": 15, "E30": 10}
assert sum(counts.values()) == 100

manager, population = build()
assert (manager.width, manager.height) == (160, 100)
assert len(manager.building_ids) == 55

print("Campus:", manager.width, "x", manager.height)
print("Edificios identificados:", len(manager.building_ids))
for building in counts:
    print(f"{building}: celdas disponibles={len(population.available_cells(building))}, "
          f"personas solicitadas={counts[building]}")

people = population.distribute(
    counts, seed=config["seed"], id_prefix=config["id_prefix"]
)
assert len(people) == 100
assert manager.count() == 100
assert len({p.person_id for p in people}) == 100
assert len({p.position for p in people}) == 100
assert Counter(p.building_id for p in people) == Counter(counts)
for person in people:
    assert manager.building_at(*person.position) == person.building_id
    assert person.position in population._cells[person.building_id]
    assert person.status == "normal"

print("Distribucion automatica: 100 personas colocadas.")
print("Sin IDs repetidos, celdas ocupadas ni ubicaciones fuera del edificio.")

# La misma semilla sobre un manager nuevo produce el mismo resultado.
manager2, distribution2 = build()
people2 = distribution2.distribute(counts, seed=config["seed"])
assert [(p.person_id, p.position, p.building_id) for p in people] == [
    (p.person_id, p.position, p.building_id) for p in people2
]
manager3, distribution3 = build()
people3 = distribution3.distribute(counts, seed=2027)
assert [p.position for p in people] != [p.position for p in people3]
print("Semilla reproducible y cambio de semilla: correctos.")

# Una solicitud imposible debe rechazarse sin registrar a nadie.
manager4, distribution4 = build()
should_fail(lambda: distribution4.distribute({"E1": 1, "E30": distribution4.capacity("E30") + 1}),
            "capacidad excedida")
assert manager4.count() == 0
should_fail(lambda: distribution4.distribute({"E999": 1}), "edificio desconocido")
should_fail(lambda: distribution4.distribute({"E1": -2}), "cantidad negativa")
should_fail(lambda: distribution4.distribute({"E1": 1.5}), "cantidad decimal")
should_fail(lambda: distribution4.distribute({"E1": True}), "cantidad booleana")
should_fail(lambda: distribution4.distribute({"E1": 1}, seed="2026"), "semilla invalida")
assert manager4.count() == 0
print("Capacidad, edificios desconocidos y valores invalidos: correctos.")

# Respetar personas ya registradas, celdas ocupadas e identificadores usados.
manager5, distribution5 = build()
occupied = distribution5.available_cells("E1")[0]
manager5.add_person(Person("P001", *occupied, building_id="E1"))
added = distribution5.distribute({"E1": 3}, seed=2026)
assert manager5.count() == 4
assert all(p.position != occupied for p in added)
assert [p.person_id for p in added] == ["P002", "P003", "P004"]
assert len(distribution5.available_cells("E1")) == distribution5.capacity("E1") - 4
# Completar toda la capacidad en el edificio, sin sobrepasarla.
free = len(distribution5.available_cells("E1"))
assert len(distribution5.distribute({"E1": free}, seed=2027)) == free
before = manager5.count()
should_fail(lambda: distribution5.distribute({"E1": 1}), "edificio completo")
assert manager5.count() == before
print("Ocupacion previa, IDs consecutivos y capacidad completa: correctos.")

# Aun no se activan puertas ni movimiento interior.
first = people[0]
should_fail(lambda: manager.move_person(first.person_id, 1, 0), "movimiento interior")
print("Las personas interiores permanecen inmoviles hasta el Paso 8.12.")
print("Paso 8.11 completado correctamente.")
