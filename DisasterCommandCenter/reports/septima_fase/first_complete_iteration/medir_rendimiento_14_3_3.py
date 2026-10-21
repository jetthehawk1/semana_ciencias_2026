"""Disaster Command Center — Paso 14.3.3: rendimiento con 500 personas.

No modifica ningun modulo ni archivo JSON del proyecto.
El escenario ficticio de 500 personas se define en un JSON *temporal*, fuera del proyecto.
Mide SOLO el motor (sin Pygame). Los turnos NO son segundos de evacuacion.
Python 3.10+ y biblioteca estandar; utiliza clases ya instaladas en el proyecto.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

# Evita crear archivos __pycache__ durante los imports.
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from simulation.evacuation_control import EvacuationControlCenter
from simulation.hazard_impact import FireEvacuationControlCenter
from simulation.indoor_people import IndoorPersonManager
from simulation.indoor_population import IndoorPopulationDistributor
from simulation.sensor_simulation import VirtualSensorNetwork

CAMPUS = ROOT / "data" / "campus.json"
ACCESOS = ROOT / "data" / "building_entrances.json"
SENSORES = ROOT / "data" / "sensores_paso_13.json"
OCUPACION_ORIGINAL = ROOT / "data" / "ocupacion_ejemplo.json"

# Personas ficticias repartidas entre dieciseis edificios; no son aforos reales.
# Se conserva el foco E30 con 10 personas para estudiar un caso comparable.
DISTRIBUCION_500 = {
    "E1": 40,
    "E3": 35,
    "E4": 30,
    "E5": 25,
    "E6": 25,
    "E9": 40,
    "E10": 25,
    "E14": 40,
    "E15": 35,
    "E16": 25,
    "E18": 25,
    "E25": 45,
    "E28": 25,
    "E30": 10,
    "E32": 35,
    "E40": 40,
}
PERSONAS = 500
SENSORES_N = 12
TURNOS_FUEGO = 35
TOPE_EVACUACION = 250
NS_MS = 1_000_000


def archivos_originales() -> list[Path]:
    """Archivos existentes que nunca debemos alterar."""
    files = [p for p in ROOT.glob("*.py") if p.is_file()]
    for folder, extension in ((ROOT / "src", "*.py"), (ROOT / "data", "*.json")):
        if folder.is_dir():
            files.extend(p for p in folder.rglob(extension) if p.is_file())
    return sorted(set(files))


def huellas(paths: list[Path]) -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


@dataclass
class Muestra:
    nombre: str
    preparacion_ms: float
    ejecucion_ms: float
    duraciones_turno_ms: list[float]
    sensores_ms: float
    turnos: int
    lecturas: int
    salieron: int
    dentro: int
    incapacitadas: int
    firma: tuple

    @property
    def tps(self) -> float:
        return self.turnos * 1000 / self.ejecucion_ms


def confirmar_poblacion(scenario) -> None:
    people = scenario.people
    summary = scenario.summary()
    assert len(people) == PERSONAS, "Cantidad de personas incorrecta"
    assert len({p.person_id for p in people}) == PERSONAS, "Identificadores repetidos"
    assert len({p.position for p in people}) == PERSONAS, "Colision entre personas"
    assert summary["salieron"] + summary["dentro"] == PERSONAS, "Conteo inconsistente"
    assert summary["dentro"] == sum(p.building_id is not None for p in people), (
        "Conteo de personas en edificios inconsistente"
    )
    assert all(p.status != "a_salvo" for p in people), (
        "Cruzar una puerta no equivale a llegar a una zona segura"
    )
    for person in people:
        if person.building_id is None:
            assert scenario.manager.is_transitable(*person.position), (
                f"Exterior bloqueado: {person.person_id}"
            )
        else:
            assert scenario.manager.building_at(*person.position) == person.building_id, (
                f"Interior incorrecto: {person.person_id}"
            )


def comprobar_capacidad() -> None:
    assert sum(DISTRIBUCION_500.values()) == PERSONAS
    manager = IndoorPersonManager.from_json(CAMPUS)
    distributor = IndoorPopulationDistributor(manager, ACCESOS)
    print("\nCapacidad de celdas interiores conectadas a accesos:")
    for building, count in DISTRIBUCION_500.items():
        capacity = distributor.capacity(building)
        assert count <= capacity, (
            f"{building}: {count} personas exceden las {capacity} celdas disponibles"
        )
        print(f"  {building:<5} personas={count:>3} | celdas={capacity:>3} [OK]")
    print(f"[OK] {PERSONAS} personas en {len(DISTRIBUCION_500)} edificios. "
          "Ocupacion ficticia, NO aforo real.")


def prueba_normal(ocupacion_temporal: Path) -> Muestra:
    t0 = time.perf_counter_ns()
    scenario = EvacuationControlCenter(CAMPUS, ACCESOS, ocupacion_temporal)
    assert len(scenario.people) == PERSONAS
    scenario.start_alarm()
    preparacion = (time.perf_counter_ns() - t0) / NS_MS

    turnos_ms: list[float] = []
    t0 = time.perf_counter_ns()
    for _ in range(TOPE_EVACUACION):
        if scenario.phase == "completado":
            break
        start_turn = time.perf_counter_ns()
        scenario.step()
        turnos_ms.append((time.perf_counter_ns() - start_turn) / NS_MS)
    duracion = (time.perf_counter_ns() - t0) / NS_MS

    confirmar_poblacion(scenario)
    summary = scenario.summary()
    assert scenario.phase == "completado", (
        f"No salieron todas las personas en {TOPE_EVACUACION} turnos. "
        f"Permanecen dentro: {summary['dentro']}. Revisar congestiones."
    )
    assert summary["salieron"] == PERSONAS and summary["dentro"] == 0
    assert summary["turnos"] == len(turnos_ms)
    assert len(scenario.log) == len(turnos_ms) + 1
    return Muestra(
        "Evacuacion normal", preparacion, duracion, turnos_ms, 0.0,
        len(turnos_ms), 0, summary["salieron"], summary["dentro"], 0,
        (summary["turnos"], summary["salieron"], summary["dentro"],
         summary["movimientos"]),
    )


def prueba_emergencia(ocupacion_temporal: Path) -> Muestra:
    t0 = time.perf_counter_ns()
    scenario = FireEvacuationControlCenter(
        CAMPUS, ACCESOS, ocupacion_temporal,
        ignition=(78, 55), direction="E", intensity=0.75, seed=2026,
    )
    network = VirtualSensorNetwork(
        scenario.environment, CAMPUS, SENSORES, run_id="rendimiento_14_3_3",
        seed=2026, temperature_noise=0.0, smoke_noise=0.0,
    )
    assert len(scenario.people) == PERSONAS
    assert len(network.sensors) == SENSORES_N
    scenario.start_alarm()
    preparacion = (time.perf_counter_ns() - t0) / NS_MS

    turnos_ms: list[float] = []
    n_readings = 0
    alarms = 0
    sensors_ns = 0
    t0 = time.perf_counter_ns()

    start_sensor = time.perf_counter_ns()
    initial = network.sample()  # Turno cero
    sensors_ns += time.perf_counter_ns() - start_sensor
    assert len(initial) == SENSORES_N
    n_readings += len(initial)
    alarms += sum(row["alarm"] for row in initial)

    for _ in range(TURNOS_FUEGO):
        if scenario.phase == "completado":
            break
        start_turn = time.perf_counter_ns()
        scenario.step()
        turnos_ms.append((time.perf_counter_ns() - start_turn) / NS_MS)
        start_sensor = time.perf_counter_ns()
        readings = network.sample()
        sensors_ns += time.perf_counter_ns() - start_sensor
        assert len(readings) == SENSORES_N
        n_readings += len(readings)
        alarms += sum(row["alarm"] for row in readings)

    duracion = (time.perf_counter_ns() - t0) / NS_MS
    confirmar_poblacion(scenario)
    summary = scenario.summary()
    assert scenario.environment.fire.turn == scenario.environment.smoke.turn
    assert summary["turnos"] == TURNOS_FUEGO == len(turnos_ms)
    assert n_readings == SENSORES_N * (TURNOS_FUEGO + 1)
    assert sum(summary["riesgo"].values()) == PERSONAS
    incapacitated = summary["riesgo"]["incapacitada"]
    return Muestra(
        "Emergencia E30 + 12 sensores", preparacion, duracion,
        turnos_ms, sensors_ns / NS_MS, len(turnos_ms), n_readings,
        summary["salieron"], summary["dentro"], incapacitated,
        (summary["turnos"], summary["salieron"], summary["dentro"],
         incapacitated, summary["movimientos"], n_readings, alarms,
         summary["fuego"]["burning"], summary["humo"]["smoky_cells"]),
    )


def mostrar_resumen(name: str, results: list[Muestra]) -> None:
    times = [r.ejecucion_ms for r in results]
    preparations = [r.preparacion_ms for r in results]
    turn_times = [ms for r in results for ms in r.duraciones_turno_ms]
    avg_per_run = [statistics.mean(r.duraciones_turno_ms) for r in results]
    speeds = [r.tps for r in results]
    r = results[0]
    print(f"\n--- {name} ---")
    print(f"Personas: {PERSONAS} | Turnos: {r.turnos} | Lecturas: {r.lecturas}")
    print(f"Preparacion, mediana:        {statistics.median(preparations):10.3f} ms")
    print(f"Ejecucion total, mediana:    {statistics.median(times):10.3f} ms")
    print(f"Tiempo medio por turno:     {statistics.mean(avg_per_run):10.3f} ms")
    print(f"Turno mas lento (p95):      {p95(turn_times):10.3f} ms")
    print(f"Rendimiento, mediana:       {statistics.median(speeds):10.2f} turnos/s")
    if r.lecturas:
        print(f"Lectura sensores, mediana:  "
              f"{statistics.median([m.sensores_ms for m in results]):10.3f} ms "
              "(total incluido en ejecucion)")
    print(f"Salieron: {r.salieron} | Dentro: {r.dentro} | "
          f"Incapacitadas (modelo): {r.incapacitadas}")
    print(f"Resultados identicos:      [OK] {len(results)}/{len(results)} repeticiones")


def medir(name: str, function, path: Path, warmups: int, repeats: int) -> list[Muestra]:
    print(f"\nMidiendo: {name} ...", flush=True)
    for _ in range(warmups):
        function(path)
    results: list[Muestra] = []
    for n in range(repeats):
        result = function(path)
        results.append(result)
        assert result.firma == results[0].firma, (
            f"{name}: los resultados de la simulacion cambiaron entre ejecuciones"
        )
        print(f"  Repeticion {n+1}/{repeats}: "
              f"{result.ejecucion_ms:.3f} ms, {result.tps:.1f} turnos/s", flush=True)
    mostrar_resumen(name, results)
    return results


def main():
    parser = argparse.ArgumentParser(description="Paso 14.3.3: rendimiento con 500 personas")
    parser.add_argument("--repeticiones", type=int, default=5)
    parser.add_argument("--calentamientos", type=int, default=1)
    args = parser.parse_args()
    if not (1 <= args.repeticiones <= 30):
        parser.error("--repeticiones debe estar entre 1 y 30")
    if not (0 <= args.calentamientos <= 5):
        parser.error("--calentamientos debe estar entre 0 y 5")

    for path in (CAMPUS, ACCESOS, SENSORES, OCUPACION_ORIGINAL):
        if not path.is_file():
            raise FileNotFoundError(f"Falta un archivo requerido: {path}")
    before = huellas(archivos_originales())
    print("=== PASO 14.3.3: RENDIMIENTO (500 PERSONAS) ===")
    print("Solo lectura sobre el proyecto; ocupacion creada en archivo temporal.")
    print(f"Python: {platform.python_version()} | Plataforma: {platform.system()}")
    print(f"Calentamientos: {args.calentamientos}; repeticiones: {args.repeticiones}")

    comprobar_capacidad()
    with tempfile.TemporaryDirectory(prefix="dcc_500_") as temp:
        config = Path(temp) / "ocupacion_500_temporal.json"
        config.write_text(json.dumps({
            "description": "Prueba ficticia de rendimiento, no aforos reales",
            "seed": 2026, "id_prefix": "P", "building_counts": DISTRIBUCION_500,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        normal = medir("Evacuacion normal", prueba_normal,
                       config, args.calentamientos, args.repeticiones)
        emergency = medir("Emergencia E30 + 12 sensores", prueba_emergencia,
                          config, args.calentamientos, args.repeticiones)

    after = huellas(archivos_originales())
    assert before == after, "Se detectaron cambios en archivos Python o JSON originales"
    print("\n=== RESUMEN 14.3.3 ===")
    print(f"[OK] Capacidad de {PERSONAS} personas validada en "
          f"{len(DISTRIBUCION_500)} edificios.")
    print(f"[OK] Sin incendio: {normal[0].salieron}/{PERSONAS} salieron en "
          f"{normal[0].turnos} turnos.")
    print(f"[OK] Emergencia E30: {emergency[0].salieron} salieron, "
          f"{emergency[0].dentro} dentro; "
          f"{emergency[0].incapacitadas} incapacitadas; "
          f"{emergency[0].lecturas} lecturas.")
    print(f"[OK] Resultados deterministas: {args.repeticiones} repeticiones por caso.")
    print(f"[OK] Archivos Python/JSON originales sin cambios: {len(after)}.")
    print("Paso 14.3.3 COMPLETADO: rendimiento medido en este equipo.")
    print("NOTA: al cambiar los edificios ocupados, la comparacion con 100 y 250 personas "
          "no aisla solo el efecto del tamano de poblacion.")
    print("NOTA: no se midio Pygame ni memoria; los turnos NO son segundos reales.")


if __name__ == "__main__":
    main()
