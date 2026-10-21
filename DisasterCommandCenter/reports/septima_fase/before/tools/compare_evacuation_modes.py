"""Paired synthetic evacuation benchmark, same physical inputs in both modes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import mean, median
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT)]
import numpy as np
from simulation.functional_scenario import FunctionalSimulation


def physical_digest(simulation):
    f = simulation.environment.fire
    payload = json.dumps([f.turn, sorted(f.burning.items()), sorted(f.burned), f.spotting_events], sort_keys=True).encode()
    return hashlib.sha256(payload+np.asarray(simulation.environment.smoke.concentrations, dtype='<f8').tobytes()).hexdigest()


def scenarios(count=10, turns=160, seed=2026):
    reference = FunctionalSimulation(ROOT, mode='optimizado')
    names = sorted(reference.manager.building_ids)
    selected = ['E30']+random.Random(seed).sample([n for n in names if n != 'E30'], count-1)
    directions = ('E', 'SE', 'S', 'SW', 'W', 'NW', 'N', 'NE')
    result = []
    for i, name in enumerate(selected):
        cells = [(x, y) for y, row in enumerate(reference.manager.building_owners) for x, n in enumerate(row) if n == name]
        cx, cy = mean(p[0] for p in cells), mean(p[1] for p in cells)
        origin = min(cells, key=lambda p: ((p[0]-cx)**2+(p[1]-cy)**2, p))
        if i == 0:
            origin = reference.ignition_cell
        inputs = []
        for turn in range(1, turns+1):
            index = i % 8 if i < count//2 else (i+(turn-1)//40) % 8
            speed = .5+(i % 3)*.15 if i < count//2 else .65+.12*math.sin(turn/18+i)
            inputs.append([directions[index], speed])
        result.append(dict(scenario_id=f'S{i+1:02}', building=name, seed=seed+17*i,
                           ignition=list(origin), wind_inputs=inputs, turns=turns))
    return result


def run_case(scenario, mode, *, progress=True):
    began = perf_counter()
    first = scenario['wind_inputs'][0]
    s = FunctionalSimulation(ROOT, mode='optimizado', evacuation_mode=mode, seed=scenario['seed'],
                             direction=first[0], intensity=first[1])
    s.select_ignition(*scenario['ignition']); s.start_alarm()
    initialized = perf_counter()-began
    trajectory = [physical_digest(s)]
    for i, (direction, speed) in enumerate(scenario['wind_inputs'], 1):
        s.set_wind(direction, speed)
        previous = {p.person_id: p.position for p in s.people}
        s.step()
        assert s.router.last_searches <= s.router.last_budget
        assert len({p.position for p in s.people}) == 1879
        assert all(abs(p.x-previous[p.person_id][0])+abs(p.y-previous[p.person_id][1]) <= 1 for p in s.people)
        s.manager.assert_index_consistent()
        trajectory.append(physical_digest(s))
        if progress and (i % 40 == 0 or i == scenario['turns']):
            print(f"{scenario['scenario_id']} {mode} t={i} gathered={s.router.gathered_count()} incap={s.tracker.counts()['incapacitada']}", flush=True)
    elapsed = perf_counter()-began
    return dict(metrics=s.metrics.result(s), elapsed_seconds=elapsed, initialization_seconds=initialized,
                seconds_per_turn=(elapsed-initialized)/scenario['turns'], physical_trajectory=trajectory,
                maximum_route_budget_used=s.router.maximum_budget_used,
                maximum_astar_searches=s.router.maximum_searches_used,
                final_fire=s.environment.fire.stats(), wind_predictor_calls=dict(s.wind_predictor.calls),
                confirmed_forecast_departures=s.metrics.confirmed_departures,
                destination_changes=s.router.destination_changes,
                unassigned_reasons=dict(s.router.unassigned_reasons),
                meeting_states=dict(s.router.area_policy.states))


LOWER_IS_BETTER = ('people_exposed_smoke', 'accumulated_smoke_dose', 'people_close_to_fire', 'fire_contacts',
                  'incapacitated', 'unsafe_waiting_person_turns', 'destination_became_unsafe_before_arrival',
                  'people_in_cells_that_later_became_hazardous')


def aggregate(cases):
    result = {}
    for mode in ('traditional', 'intelligent'):
        keys = [k for k, v in cases[0][mode]['metrics'].items() if isinstance(v, (int, float)) or v is None]
        result[mode] = {}
        for key in keys:
            values = [c[mode]['metrics'][key] for c in cases if c[mode]['metrics'][key] is not None]
            result[mode][key] = dict(mean=mean(values), median=median(values),
                worst=min(values) if key in ('safe_meeting_arrivals', 'people_ever_reached_meeting') else max(values),
                measured_scenarios=len(values)) if values else None
    wins = {}
    for key in LOWER_IS_BETTER:
        deltas = [c['intelligent']['metrics'][key]-c['traditional']['metrics'][key] for c in cases]
        wins[key] = dict(intelligent_wins=sum(d < -1e-9 for d in deltas), ties=sum(abs(d) <= 1e-9 for d in deltas),
                         traditional_wins=sum(d > 1e-9 for d in deltas), mean_delta=mean(deltas))
    result['paired_risk_comparison'] = wins
    # Explicit conservative readiness gate; metrics are never modified to satisfy it.
    primary = ('incapacitated', 'accumulated_smoke_dose', 'unsafe_waiting_person_turns')
    result['consistent_risk_improvement'] = all(wins[k]['mean_delta'] < 0 and
        wins[k]['intelligent_wins'] > wins[k]['traditional_wins'] for k in primary)
    return result


def compare(count=10, turns=160, seed=2026, output=None, *, resume=False):
    if not 1 <= count <= 20 or turns < 1:
        raise ValueError('Usa 1..20 escenarios y turnos positivos; entrega completa >=10 escenarios.')
    output = Path(output or ROOT/'reports/evacuation_comparison')
    output.mkdir(parents=True, exist_ok=True)
    # A checkpoint from any other source/config is never silently reused.
    inputs = sorted((ROOT/'src').rglob('*.py'))+[ROOT/'data/functional_scenario.json', Path(__file__)]
    source_hash = hashlib.sha256(b''.join(p.read_bytes() for p in inputs)).hexdigest()
    cases = []
    for scenario in scenarios(count, turns, seed):
        case = dict(scenario)
        for mode in ('traditional', 'intelligent'):
            path = output/f"{scenario['scenario_id']}_{mode}.json"
            existing = json.loads(path.read_text(encoding='utf-8')) if resume and path.exists() else None
            if existing and existing.get('source_hash') == source_hash and existing.get('scenario') == scenario:
                case[mode] = existing['result']
            else:
                case[mode] = run_case(scenario, mode)
                path.write_text(json.dumps(dict(source_hash=source_hash, scenario=scenario, result=case[mode]), indent=2)+'\n', encoding='utf-8')
        case['identical_physical_trajectory'] = case['traditional']['physical_trajectory'] == case['intelligent']['physical_trajectory']
        if not case['identical_physical_trajectory']:
            raise AssertionError('Los modos alteraron la fisica: comparacion invalida.')
        cases.append(case)
        report = dict(data_source='synthetic_simulation', source_hash=source_hash, scenarios=cases,
                      aggregate=aggregate(cases), complete=len(cases) == count,
                      definitions=dict(confirmed_forecast_departures='Departure explicitly triggered by forecast; abandoned cell actually dangerous later within horizon and person absent at confirmation. Observed proxy, not proven prevented injury.',
                        smoke_dose='Existing ExposureTracker cumulative dose; stops accumulating after incapacitation.',
                        arrival_times='First arrival among people who reached an available area. Unreached are censored, not assigned zero.',
                        later_hazard='Person occupied cell in previous horizon before observed smoke >=0.30 or fire clearance violation.',
                        unsafe_wait='No displacement, mobile, finite hazard ETA minus evacuation ETA <= unsafe-wait margin; same observer both modes.'))
        (output/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        rows = [dict(scenario_id=c['scenario_id'], seed=c['seed'], building=c['building'], mode=m, **c[m]['metrics'])
                for c in cases for m in ('traditional', 'intelligent')]
        for row in rows:
            row.pop('state_counts', None)
        with (output/'summary.csv').open('w', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        print(f"Paired {scenario['scenario_id']}: physical equality verified", flush=True)
    return report


if __name__ == '__main__':
    defaults = json.loads((ROOT/'data/functional_scenario.json').read_text(encoding='utf-8'))['comparison']
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenarios', type=int, default=defaults['scenario_count'])
    parser.add_argument('--turns', type=int, default=defaults['turns'])
    parser.add_argument('--seed', type=int, default=defaults['seed'])
    parser.add_argument('--output-dir', type=Path, default=ROOT/'reports/evacuation_comparison')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    compare(args.scenarios, args.turns, args.seed, args.output_dir, resume=args.resume)
