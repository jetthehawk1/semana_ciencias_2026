from pathlib import Path
import sys, json, cProfile, pstats, io
from time import perf_counter
ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'reports/sexta_fase/before'
sys.path[:0]=[str(BASE/'src'),str(BASE)]
from simulation.functional_scenario import FunctionalSimulation
from tools.compare_evacuation_modes import physical_digest

def run(name, turns, *, seed=2026, origin=None, winds=None, profile=False):
    t=perf_counter(); s=FunctionalSimulation(BASE,mode='optimizado',seed=seed)
    if origin: s.select_ignition(*origin)
    if winds: s.set_wind(*winds[0])
    s.start_alarm(); init=perf_counter()-t; contacts=[]; oldfire=set(); prof=cProfile.Profile()
    for turn in range(1,turns+1):
        if winds: s.set_wind(*winds[turn-1])
        before={p.person_id:dict(position=p.position,building=p.building_id,
                route=s.router.assignments.get(p.person_id),diagnostic=s.decision_policy.diagnostics.get(p.person_id),
                fire_eta=s.hazard_arrival.time_to_hazard(*p.position)) for p in s.people}
        fire_before=set(s.environment.fire.burning)
        known={pid for pid,r in s.tracker.records.items() if r.fire_contact}
        if profile and 60<=turn<=64: prof.enable()
        s.step()
        if profile and 60<=turn<=64: prof.disable()
        for p in s.people:
            if s.tracker.records[p.person_id].fire_contact and p.person_id not in known:
                data=before[p.person_id]
                contacts.append(dict(turn=turn,person_id=p.person_id,**data,
                    category='already_burning_before_turn' if data['position'] in fire_before else 'fire_reached_occupied_cell_before_movement',
                    final_position=p.position,exposure=vars(s.tracker.records[p.person_id])))
        if turn%40==0: print(name,turn,'contacts',len(contacts),flush=True)
    elapsed=perf_counter()-t
    result=dict(turns=turns,initialization_seconds=init,elapsed_seconds=elapsed,
                seconds_per_turn=(elapsed-init)/turns,metrics=s.metrics.result(s),summary=s.summary(),
                physics_digest=physical_digest(s),fire_contact_traces=contacts)
    (ROOT/f'reports/sexta_fase/{name}.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if profile:
        out=io.StringIO(); pstats.Stats(prof,stream=out).sort_stats('cumulative').print_stats(55)
        (ROOT/'reports/sexta_fase/profile_before.txt').write_text(out.getvalue(),encoding='utf-8')
        prof.dump_stats(str(ROOT/'reports/sexta_fase/profile_before.pstats'))
    print(name,'done',elapsed,flush=True)

if __name__=='__main__':
    run('baseline_profile',80,profile=True)
    run('baseline_240',240)
    previous=json.loads((ROOT/'reports/evacuation_comparison/summary.json').read_text())
    case=next(c for c in previous['scenarios'] if c['scenario_id']=='S10')
    run('fire_trace_S10',case['turns'],seed=case['seed'],origin=case['ignition'],winds=case['wind_inputs'])
