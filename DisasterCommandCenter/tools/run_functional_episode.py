"""Episodio reproducible sin ventana; mide el modelo activo sin forzar evacuacion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from simulation.functional_scenario import FunctionalSimulation
from simulation.scenario_fire import ScenarioFireSimulation
from simulation.wind_simulation import Wind, WindFireSimulation, WindSmokeSimulation


def compare_behavior(config):
    totals = {"normal": [], "laboratory": [], "legacy": []}
    behavior = {**config["fire_behavior"], "spotting_enabled": False}
    terrain = [["building"]*41 for _ in range(41)]
    owners = [["E"]*41 for _ in range(41)]
    for seed in range(30):
        for name in totals:
            properties = {"E": {"laboratory": name == "laboratory", "flammable_materials": name == "laboratory"}}
            fire = (WindFireSimulation(terrain, seed=seed) if name == "legacy" else
                    ScenarioFireSimulation(terrain, None, behavior=behavior, owners=owners,
                                           properties=properties, seed=seed))
            fire.set_wind(Wind("E", .75))
            fire.ignite(20, 20)
            for _ in range(30):
                fire.step()
            totals[name].append(fire.total_ignitions)
    smoke_totals = {}
    for name, options in (("legacy", {}), ("functional", config["smoke_behavior"])):
        smoke = WindSmokeSimulation(1, 1, **options)
        smoke.concentrations[0][0] = 1
        for _ in range(40):
            smoke.step()
        smoke_totals[name] = smoke.concentrations[0][0]
    return {"description": "41x41 edificio homogeneo, viento E .75, 30 turnos, seeds 0..29; sin brasas",
            "total_ignitions_by_seed": totals,
            "mean_ignitions": {key: sum(values)/len(values) for key, values in totals.items()},
            "smoke_after_40_turns_without_source_in_closed_1_cell": smoke_totals}


def run(turns=240, sample_every=20, ignition=None, mode="optimizado", controlled_wind=False,
        evacuation_mode=None, seed=None):
    started = perf_counter()
    simulation = FunctionalSimulation(ROOT, mode=mode, evacuation_mode=evacuation_mode, seed=seed)
    if ignition is not None:
        simulation.select_ignition(*ignition)
    simulation.start_alarm()
    initialization = perf_counter()-started
    reached = set()
    peak_blocked = 0
    samples = []
    for turn in range(turns+1):
        if turn:
            if controlled_wind:
                # Entradas reproducibles equivalentes a controles, nunca al predictor.
                directions = ("E", "SE", "S", "SW", "W", "NW", "N", "NE")
                import math
                direction = directions[((turn-1)//20) % len(directions)]
                speed = .65+.15*math.sin(turn/12)
                simulation.set_wind(direction, speed)
            previous = {p.person_id: p.position for p in simulation.people}
            simulation.step()
            assert len({p.position for p in simulation.people}) == 1879
            assert all(abs(p.x-previous[p.person_id][0])+abs(p.y-previous[p.person_id][1]) <= 1
                       for p in simulation.people)
            if hasattr(simulation.manager, "assert_index_consistent"):
                simulation.manager.assert_index_consistent()
        fire = simulation.environment.fire
        reached.update(name for x, y in fire.burning if (name := simulation.manager.building_at(x, y)))
        peak_blocked = max(peak_blocked, len(simulation.controller.blocked_exit_groups))
        if turn % sample_every == 0 or turn == turns:
            info = simulation.summary()
            sample = {"turn": turn, "fire_cells": len(fire.burning),
                      "smoke_cells_ge_005": info["humo"]["smoky_cells"],
                      "outside_students": info["salieron"], "gathered_students": info["meeting"]["gathered"],
                      "routes_calculated": simulation.router.routes_calculated,
                      "routes_recalculated": simulation.router.replanned_routes,
                      "secondary_foci": len(fire.spotting_events), "buildings_reached": sorted(reached),
                      "blocked_exits": len(simulation.controller.blocked_exit_groups),
                      "alternative_exits_used": simulation.controller.alternative_exits_used,
                      "alternative_exits_under_blockage": simulation.controller.alternative_exits_under_blockage,
                      "incapacitated_students": info["riesgo"]["incapacitada"],
                      "available_meeting_areas": sum(simulation.router.safe.values())}
            sample.update(unsafe_waiting=sum(v == 'WAITING_UNSAFE' for v in simulation.metrics.states.values()),
                          temporary_goals=len(simulation.router.temporary),
                          confirmed_forecast_departures=len(simulation.metrics.confirmed_departures),
                          route_budget=simulation.router.last_budget)
            if simulation.predicted_wind is not None:
                sample.update(wind_direction=simulation.environment.wind.direction,
                              wind_speed=simulation.environment.wind.intensity,
                              predicted_wind=vars(simulation.predicted_wind),
                              meeting_states={key: simulation.router.area_policy.states[key] for key in simulation.router.areas},
                              preventive_reassignments=simulation.router.preventive_reassignments,
                              predictive_route_invalidations=simulation.router.predictive_route_invalidations,
                              destination_changes=len(simulation.router.destination_changes))
            samples.append(sample)
            print(json.dumps(sample, ensure_ascii=False), flush=True)
    elapsed = perf_counter()-started
    report = {"seed": simulation.hazard_seed, "mode": mode, "ignition": simulation.ignition_cell,
            "wind": simulation.config["wind"], "turns": turns, "samples": samples,
            "spotting_events": fire.spotting_events, "final_summary": simulation.summary(),
            "peak_blocked_exits": peak_blocked, "initialization_seconds": initialization,
            "elapsed_seconds": elapsed, "seconds_per_turn": (elapsed-initialization)/max(turns, 1)}
    report.update(controlled_wind=controlled_wind,
                  evacuation_mode=simulation.evacuation_mode, hazard_seed=simulation.hazard_seed,
                  evacuation_metrics=simulation.metrics.result(simulation),
                  wind_prediction_calls=dict(simulation.wind_predictor.calls),
                  wind_observations=simulation.wind_telemetry.observations,
                  meeting_transitions=simulation.router.area_policy.transitions,
                  destination_changes=simulation.router.destination_changes,
                  risk_array_bytes=sum(value.nbytes for value in vars(simulation.risk_field).values() if hasattr(value, 'nbytes')),
                  static_topology_cached=simulation.router.graph._static_neighbors is not None)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=240)
    parser.add_argument("--sample-every", type=int, default=20)
    parser.add_argument("--ignition", type=int, nargs=2, metavar=("X", "Y"))
    parser.add_argument("--mode", choices=("original", "optimizado"), default="optimizado")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--controlled-wind", action="store_true")
    parser.add_argument('--evacuation-mode', choices=('intelligent', 'traditional'), default=None)
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/tercera_fase/episode.json")
    args = parser.parse_args()
    if args.turns < 1 or args.sample_every < 1:
        parser.error("turns y sample-every deben ser positivos")
    result = run(args.turns, args.sample_every, args.ignition, args.mode, args.controlled_wind,
                 args.evacuation_mode, args.seed)
    if args.compare:
        result["controlled_comparison"] = compare_behavior(json.loads((ROOT / "data/functional_scenario.json").read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Informe: {args.output}; {result['elapsed_seconds']:.3f}s", flush=True)
