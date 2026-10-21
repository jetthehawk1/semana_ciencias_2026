from pathlib import Path
import json,sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from simulation.functional_scenario import FunctionalSimulation

def trace(mode):
 case=json.loads((ROOT/'reports/evacuation_comparison/S07_traditional.json').read_text())['scenario']
 d,v=case['wind_inputs'][0]
 s=FunctionalSimulation(ROOT,mode='optimizado',evacuation_mode=mode,seed=case['seed'],direction=d,intensity=v)
 s.select_ignition(*case['ignition']);s.start_alarm()
 events=[];samples=[]
 for turn,(d,v) in enumerate(case['wind_inputs'],1):
  previous={p.person_id:dict(position=p.position,level=s.tracker.records[p.person_id].level,assignment=s.router.assignments.get(p.person_id),
    state=s.metrics.states.get(p.person_id),hazard_eta=s.hazard_arrival.time_to_hazard(*p.position),
    margin=s.decision_policy.diagnostics.get(p.person_id,{}).get('safety_margin') if s.decision_policy else None,
    route_status=s.router.follower.route_snapshot(p.person_id)) for p in s.people}
  s.set_wind(d,v);s.step()
  for p in s.people:
   e=s.tracker.records[p.person_id]
   if e.level=='incapacitada' and previous[p.person_id]['level']!='incapacitada':
    events.append(dict(turn=turn,person_id=p.person_id,origin=s.origin[p.person_id],position=p.position,building=p.building_id,
      fire_contact=e.fire_contact,dose=e.dose,smoke=s.environment.smoke.concentrations[p.y][p.x],
      previous=previous[p.person_id],current_assignment=s.router.assignments.get(p.person_id),
      current_eta=s.hazard_arrival.time_to_hazard(*p.position)))
  if turn%20==0:
   samples.append(dict(turn=turn,incap=s.tracker.counts()['incapacitada'],unassigned=s.router.waiting,
    states=s.summary()['evacuation_states'],gathered=s.router.gathered_count(),
    wind=[d,v],areas=dict(s.router.area_policy.states)))
 result=dict(mode=mode,events=events,samples=samples,metrics=s.metrics.result(s),
  incapacitated_by_origin=dict(Counter(e['origin'] for e in events)),
  incapacitated_inside=sum(e['building'] is not None for e in events),
  incap_after_120=sum(e['turn']>120 for e in events))
 (ROOT/f'reports/quinta_fase/regression_{mode}.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 print('Regression trace saved',mode,len(events),flush=True)
 return mode
if __name__=='__main__':
 with ProcessPoolExecutor(max_workers=2) as pool:list(pool.map(trace,['traditional','intelligent']))
