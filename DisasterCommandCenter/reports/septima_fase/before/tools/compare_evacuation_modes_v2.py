"""Reproducible phase-six paired benchmark; synthetic conditions only."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import csv
import hashlib
import json
import inspect
import math
from pathlib import Path
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from simulation.functional_scenario import FunctionalSimulation
from tools.compare_evacuation_modes import scenarios, physical_digest, aggregate


def report_json(payload):
    """Strict JSON: diagnostic out-of-horizon ETA is a string, never NaN/Inf."""
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
        if isinstance(value,(tuple,list)):return [clean(v) for v in value]
        if isinstance(value,float) and not math.isfinite(value):
            return 'Infinity' if value>0 else '-Infinity' if value<0 else 'NaN'
        return value
    return json.dumps(clean(payload),ensure_ascii=False,indent=2,allow_nan=False)+'\n'


def input_fingerprint():
    paths=sorted((ROOT/'src').rglob('*.py'))+sorted((ROOT/'data').rglob('*.json'))
    # Actor code and all data determine decisions. Scenario inputs are checked
    # verbatim per checkpoint. Pure CSV/statistics fixes must not require
    # rerunning unchanged actors; their tool hash is reported separately.
    payload=b''.join(str(p.relative_to(ROOT)).encode()+b'\0'+p.read_bytes() for p in paths)
    payload+=inspect.getsource(run_case).encode()+inspect.getsource(physical_digest).encode()
    return hashlib.sha256(payload).hexdigest()


def benchmark_scenarios(turns=160,seed=2026):
    cases=scenarios(10,turns,seed)
    for case in cases:
        case['category']='laboratory' if case['building'] in ('E16','E7','E15') else 'normal_building'
    ref=FunctionalSimulation(ROOT,mode='optimizado')
    terrain=ref.environment.fire.terrain
    grass=[(x,y) for y,row in enumerate(terrain) for x,value in enumerate(row) if value=='grass']
    def nearest_grass(area):
        x,y,w,h=ref.router.areas[area].bounds
        center=(x+w//2,y+h//2)
        return min(grass,key=lambda p:(abs(p[0]-center[0])+abs(p[1]-center[1]),p))
    extras=[('vegetation','R2','E',.75),('meeting_downwind','R3','E',.8),
            ('abrupt_wind','R1','W',.75),('two_meetings','R7','SW',.8),
            ('blocked_primary_exit',None,'E',.65),('persistent_smoke',None,'E',.1)]
    accesses=json.loads((ROOT/'data/functional/building_entrances.json').read_text())['accesses']
    for i,(category,area,direction,speed) in enumerate(extras,11):
        building='exterior'
        origin=nearest_grass(area) if area else None
        if category=='blocked_primary_exit':
            primary_groups={name:{a['id'].rsplit('-sub',1)[0] for a in accesses
                if a['building']==name and a.get('role','primary')=='primary'} for name in ref.original_counts}
            eligible=[name for name in ref.original_counts if len(primary_groups[name])==1 and
                any(a['building']==name and a.get('role')=='secondary' for a in accesses)]
            building=min(eligible,key=lambda name:(-ref.original_counts[name],name))
            a=next(a for a in accesses if a['building']==building and a.get('role','primary')=='primary')
            origin=(a['interior_cell']['x'],a['interior_cell']['y'])
            group=a['id'].rsplit('-sub',1)[0]
            secondary_foci=[[other['interior_cell']['x'],other['interior_cell']['y']]
                for other in accesses if other['id'].rsplit('-sub',1)[0]==group and other['id']!=a['id']]
        if category=='persistent_smoke':
            origin=tuple(cases[1]['ignition']);building=cases[1]['building']
        winds=[[direction,speed] for _ in range(turns)]
        if category=='abrupt_wind':
            winds=[['W' if t<turns//2 else 'E',speed] for t in range(turns)]
        case=dict(scenario_id=f'S{i:02}',category=category,building=building,seed=seed+17*(i-1),
                  ignition=list(origin),wind_inputs=winds,turns=turns)
        if category=='two_meetings':case['extra_ignitions']=[list(nearest_grass('R1'))]
        if category=='blocked_primary_exit':case['extra_ignitions']=secondary_foci
        cases.append(case)
    return cases


def run_case(scenario,mode):
    started=perf_counter(); first=scenario['wind_inputs'][0]
    s=FunctionalSimulation(ROOT,mode='optimizado',evacuation_mode=mode,seed=scenario['seed'],
        direction=first[0],intensity=first[1])
    s.select_ignition(*scenario['ignition']);s.start_alarm()
    for point in scenario.get('extra_ignitions',[]):s.ignite(*point)
    initialization=perf_counter()-started
    trajectory=[physical_digest(s)];samples=[]
    for turn,(direction,speed) in enumerate(scenario['wind_inputs'],1):
        s.set_wind(direction,speed)
        positions={p.person_id:p.position for p in s.people};s.step()
        assert len({p.position for p in s.people})==1879
        assert all(abs(p.x-positions[p.person_id][0])+abs(p.y-positions[p.person_id][1])<=1 for p in s.people)
        s.manager.assert_index_consistent()
        assert s.router.last_searches<=s.router.last_budget
        trajectory.append(physical_digest(s))
        if turn%40==0 or turn==scenario['turns']:
            samples.append(dict(turn=turn,**s.metrics.result(s)))
            print(scenario['scenario_id'],mode,turn,'incap',s.tracker.counts()['incapacitada'],flush=True)
    elapsed=perf_counter()-started
    metrics=s.metrics.result(s);metrics['runtime_seconds']=elapsed
    return dict(metrics=metrics,elapsed_seconds=elapsed,initialization_seconds=initialization,
        seconds_per_turn=(elapsed-initialization)/scenario['turns'],physical_trajectory=trajectory,samples=samples,
        total_astar_searches=s.router.total_astar_searches,cache_hits=s.router.flow.hits if s.router.flow else 0,
        cache_misses=s.router.flow.misses if s.router.flow else 0,flow_field_usage=s.router.flow.usage if s.router.flow else 0,
        fire_contact_traces=s.fire_contact_traces,unassigned_reasons=dict(s.router.unassigned_reasons),
        per_person_route_reasons=s.router.person_reasons,hard_invalidations=dict(s.router.hard_invalidations),
        watchdog_events=s.router.watchdog_events,soft_replans=s.router.soft_replans,
        route_comparisons=s.router.replan_diagnostics,escape_progress=s.decision_policy.escape_progress if s.decision_policy else [],
        meeting_load=s.router.meeting_load,meeting_states=dict(s.router.area_policy.states),
        destination_changes=s.router.destination_changes)


def publish(cases,output,fingerprint,total):
    paired=[c for c in cases if 'traditional' in c and 'intelligent' in c]
    if not paired:return None
    for c in paired:
        if c['traditional']['physical_trajectory']!=c['intelligent']['physical_trajectory']:
            raise AssertionError('Paired physical trajectory mismatch')
        c['identical_physical_trajectory']=True
    stats=aggregate(paired)
    for mode in ('traditional','intelligent'):
        stats[mode]['SafetyScore']['worst']=min(c[mode]['metrics']['SafetyScore'] for c in paired)
    t,i=stats['traditional'],stats['intelligent']
    gate=dict(fire_contacts=i['fire_contacts']['mean']<=t['fire_contacts']['mean'],
        incapacitated=i['incapacitated']['mean']<t['incapacitated']['mean'],
        smoke_exposure=i['people_exposed_smoke']['mean']<t['people_exposed_smoke']['mean'],
        smoke_dose=i['accumulated_smoke_dose']['mean']<t['accumulated_smoke_dose']['mean'],
        unsafe_wait=i['unsafe_waiting_person_turns']['mean']<t['unsafe_waiting_person_turns']['mean'],
        unassigned=i['unassigned']['mean']<=t['unassigned']['mean']*1.05)
    performance_path=ROOT/'reports/sexta_fase/performance_after.json'
    performance=json.loads(performance_path.read_text()) if performance_path.exists() else None
    config=json.loads((ROOT/'data/functional_scenario.json').read_text())
    valid_performance=performance and performance.get('source_hash')==fingerprint and performance['turns']==240
    gate['isolated_runtime_target']=(performance['seconds_per_turn']<=config['performance_validation']['target_seconds_per_turn']
                                     if valid_performance else None)
    report=dict(data_source='synthetic_simulation',source_hash=fingerprint,complete=len(paired)==total,
        evaluation_tool_hash=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        scenarios=paired,aggregate=stats,readiness_checks=gate,
        safety_score_config=json.loads((ROOT/'data/functional_scenario.json').read_text())['safety_score'],
        isolated_performance=performance if valid_performance else None,
        timing_note='Worker timings include assertions/hashes and concurrent CPU contention; isolated 240-turn performance is reported separately.')
    (output/'summary.json').write_text(report_json(report),encoding='utf-8')
    rows=[dict(scenario_id=c['scenario_id'],category=c['category'],seed=c['seed'],mode=m,
        **{k:v for k,v in c[m]['metrics'].items() if k!='state_counts'}) for c in paired for m in ('traditional','intelligent')]
    with (output/'per_scenario.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    with (output/'summary.csv').open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=['mode','metric','mean','median','worst']);writer.writeheader()
        for mode in ('traditional','intelligent'):
            for metric,values in stats[mode].items():
                if values:writer.writerow(dict(mode=mode,metric=metric,**{k:values[k] for k in ('mean','median','worst')}))
    return report


def compare(turns=160,seed=2026,workers=3,output=None,resume=False):
    output=Path(output or ROOT/'reports/evacuation_comparison_v2');output.mkdir(parents=True,exist_ok=True)
    cases=benchmark_scenarios(turns,seed);fingerprint=input_fingerprint()
    tasks=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for case in cases:
            for mode in ('traditional','intelligent'):
                path=output/f"{case['scenario_id']}_{mode}.json"
                old=json.loads(path.read_text()) if resume and path.exists() else None
                metadata={k:v for k,v in case.items() if k not in ('traditional','intelligent','identical_physical_trajectory')}
                if old and old.get('source_hash')==fingerprint and old['scenario']==metadata:
                    case[mode]=old['result']
                else: tasks.append((pool.submit(run_case,dict(case),mode),case,mode,path))
        mapping={f:(c,m,p) for f,c,m,p in tasks}
        for future in as_completed(mapping):
            case,mode,path=mapping[future];result=future.result();case[mode]=result
            # Scenario metadata only, excluding completed actor results.
            metadata={k:v for k,v in case.items() if k not in ('traditional','intelligent','identical_physical_trajectory')}
            path.write_text(report_json(dict(source_hash=fingerprint,scenario=metadata,result=result)),encoding='utf-8')
            publish(cases,output,fingerprint,len(cases))
    return publish(cases,output,fingerprint,len(cases))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--turns',type=int,default=160);parser.add_argument('--seed',type=int,default=2026)
    parser.add_argument('--workers',type=int,default=3);parser.add_argument('--output-dir',type=Path)
    parser.add_argument('--resume',action='store_true');args=parser.parse_args()
    if args.turns<1 or not 1<=args.workers<=4:parser.error('Positive turns and 1..4 workers required')
    compare(args.turns,args.seed,args.workers,args.output_dir,args.resume)
