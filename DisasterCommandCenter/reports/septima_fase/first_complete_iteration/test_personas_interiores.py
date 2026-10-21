"""Paso 8.10: prueba de personas ubicadas dentro de edificios.
Ejecutar en la raiz: python test_personas_interiores.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from simulation.person import Person
from simulation.person_manager import PersonManager
from simulation.indoor_people import IndoorPersonManager


def debe_fallar(action, label):
    try:
        action()
    except ValueError:
        return
    raise AssertionError(f"Se acepto una operacion invalida: {label}")


manager = IndoorPersonManager.from_json(ROOT / "data" / "campus.json")
entrances = json.loads(
    (ROOT / "data" / "building_entrances.json").read_text(encoding="utf-8")
)
assert (manager.width, manager.height) == (160, 100)
assert (entrances["width"], entrances["height"]) == (manager.width, manager.height)
assert len(manager.building_ids) == 55
assert len(entrances["accesses"]) == 55
n_interior = sum(owner is not None for row in manager.building_owners for owner in row)
assert n_interior == 3306, f"Se esperaban 3306 celdas building; hay {n_interior}"
print("Mapa:", manager.width, "x", manager.height)
print("Edificios identificados:", len(manager.building_ids))
print("Celdas interiores identificadas:", n_interior)

access = {item["building"]: item for item in entrances["accesses"]}
assert set(access) == manager.building_ids
for name, item in access.items():
    interior = item["interior_cell"]
    exterior = item["exterior_cell"]
    inside = (interior["x"], interior["y"])
    outside = (exterior["x"], exterior["y"])
    assert manager.building_at(*inside) == name, name
    assert manager.is_transitable(*outside), name
    assert manager.building_at(*outside) is None, name
    assert abs(inside[0] - outside[0]) + abs(inside[1] - outside[1]) == 1, name


def inside_of(name):
    cell = access[name]["interior_cell"]
    return cell["x"], cell["y"]


def outside_of(name):
    cell = access[name]["exterior_cell"]
    return cell["x"], cell["y"]


# Registrar personas de prueba en el interior de tres edificios.
manager.add_person(Person("P001", *inside_of("E1"), building_id="E1"))
manager.add_person(Person("P002", *inside_of("E30"), building_id="E30"))
manager.add_person(Person("P003", *inside_of("E61"), building_id="E61"))
# Registrar una persona adicional en el exterior de E1.
manager.add_person(Person("P004", *outside_of("E1")))
assert manager.count() == 4
print("Personas iniciales en edificios: 3")
print("Personas iniciales en exterior: 1")
for person in manager.list_people():
    print(f"{person.person_id}: {person.position}, edificio={person.building_id}")

# Una celda de edificio sin ID, o un ID que no corresponde, debe rechazarse.
debe_fallar(lambda: manager.add_person(Person("X001", *inside_of("E1"))),
            "edificio sin building_id")
debe_fallar(lambda: manager.add_person(Person("X002", *inside_of("E1"),
                                               building_id="E30")), "edificio equivocado")
debe_fallar(lambda: manager.add_person(Person("X003", *outside_of("E30"),
                                               building_id="E30")), "exterior como interior")
debe_fallar(lambda: manager.add_person(Person("X004", *inside_of("E1"),
                                               building_id="E1")), "interior ocupado")
debe_fallar(lambda: manager.add_person(Person("P002", *inside_of("E1"),
                                               building_id="E1")), "ID duplicado")
debe_fallar(lambda: manager.add_person(Person("X005", 160, 0,
                                               building_id="E1")), "fuera del mapa")
print("Edificio correcto, ocupacion y limites: correctos.")

# En 8.10 no permitimos movimiento desde el interior, ni salida por la puerta.
inicio = manager.get_person("P001").position
ix, iy = inside_of("E1")
ex, ey = outside_of("E1")
debe_fallar(lambda: manager.move_person("P001", ex - ix, ey - iy),
            "cruzar puerta aun no habilitada")
assert manager.get_person("P001").position == inicio
print("Salida desde el interior bloqueada (hasta Paso 8.12): correcta.")

# Una persona exterior SI conserva el movimiento y las colisiones anteriores.
assert manager.move_person("P004", -1, 0) == (149, 5)
debe_fallar(lambda: manager.add_person(Person("X006", 149, 5)),
            "ocupacion exterior")
assert manager.get_person("P004").position == (149, 5)
# El PersonManager antiguo no cambia de comportamiento.
legacy = PersonManager(manager.width, manager.height, manager.is_transitable)
debe_fallar(lambda: legacy.add_person(Person("L001", *inside_of("E1"),
                                               building_id="E1")), "compatibilidad antigua")
print("Movimiento exterior y PersonManager original: correctos.")
print("Paso 8.10 completado correctamente.")
