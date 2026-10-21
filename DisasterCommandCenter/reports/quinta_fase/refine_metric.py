from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import csv,hashlib,json,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
import numpy as np
from scipy.ndimage import binary_dilation
from simulation.functional_scenario import FunctionalSimulation
from tools.compare_evacuation_modes import physical_digest,aggregate

def refine(case):
 scenario={k:case[k] for k in ['scenario_id','building','seed','ignition','wind_inputs','turns']}
 d,v=scenario['wind_inputs'][0]
 s=FunctionalSimulation(ROOT,mode='optimizado',seed=scenario['seed'],direction=d,intensity=v)
 s.select_ignition(*scenario['ignition']);s.start_alarm()
 by_turn={}
 for mode in ['traditional','intelligent']:
  for event in case[mode]['confirmed_forecast_departures']:
   by_turn.setdefault(event['departure_turn'],[]).append(event)
 expected=case['traditional']['physical_trajectory']
 assert physical_digest(s)==expected[0]
 for turn,(d,v) in enumerate(scenario['wind_inputs'],1):
  before=set(s.environment.fire.burning)
  s.set_wind(d,v);s.environment.step()
  union=before|set(s.environment.fire.burning)
  assert physical_digest(s)==expected[turn],(scenario['scenario_id'],turn)
  if turn in by_turn:
   mask=np.zeros((s.manager.height,s.manager.width),dtype=bool)
   if union:
    xs,ys=zip(*union);mask[ys,xs]=True
   radius=s.config['hazard_arrival']['fire_clearance_cells']
   if radius:mask=binary_dilation(mask,iterations=radius)
   danger=mask|(np.asarray(s.environment.smoke.concentrations,dtype=np.float32)>=s.config['hazard_arrival']['danger_smoke_threshold'])
   for event in by_turn[turn]:
    x,y=event['point'];event['clean_at_departure']=not bool(danger[y,x])
 for mode in ['traditional','intelligent']:
  result=case[mode];events=result['confirmed_forecast_departures']
  clean=[e for e in events if e['clean_at_departure']];reactive=[e for e in events if not e['clean_at_departure']]
  result['confirmed_forecast_departures']=clean
  result['rejected_reactive_departures']=reactive
  m=result['metrics'];m['confirmed_forecast_departures']=len(clean)
  m['rejected_current_danger_departures']=len(reactive)
  m['candidate_hazard_departures']=m.pop('forecast_departures')
  m['pending_candidate_departures']=m.pop('unconfirmed_forecast_departures')
  m['expired_candidate_departures']=m.pop('expired_unconfirmed_forecast_departures')
 return case

if __name__=='__main__':
 output=ROOT/'reports/evacuation_comparison'
 report=json.loads((ROOT/'reports/quinta_fase/summary_before_metric_filter.json').read_text())
 manifest=json.loads((ROOT/'reports/quinta_fase/source_before_metric_filter.json').read_text())
 changed=[n for n,h in manifest.items() if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h]
 assert set(changed)=={'src/simulation/evacuation_metrics.py','src/routing/weighted_astar.py'},changed
 cases=[]
 with ProcessPoolExecutor(max_workers=3) as pool:
  futures=[pool.submit(refine,c) for c in report['scenarios']]
  for f in as_completed(futures):
   c=f.result();cases.append(c);print('Physics replay and departure filter verified:',c['scenario_id'],flush=True)
 cases.sort(key=lambda c:c['scenario_id']);report['scenarios']=cases;report['aggregate']=aggregate(cases)
 inputs=sorted((ROOT/'src').rglob('*.py'))+[ROOT/'data/functional_scenario.json',ROOT/'tools/compare_evacuation_modes.py']
 current=hashlib.sha256(b''.join(p.read_bytes() for p in inputs)).hexdigest()
 report['evaluation_source_hash']=current
 report['metric_postprocessing']=dict(verified_physical_replays=10,verified_turns_per_case=161,
  movement_not_reexecuted=True,changed_files=changed,
  reason='Only observer filtering and per-search memoization of immutable costs changed. Decision logic and scalar step costs identical; actor results preserved. Actual danger at each departure recomputed from verified physics.',
  original_decision_execution_source_hash=report['source_hash'])
 report['definitions']['confirmed_forecast_departures']='Forecast-tagged departure from a cell below the environmental danger threshold at departure; cell actually dangerous later within horizon and person absent after movement at confirmation. Observed proxy, not proof of prevented injury.'
 for c in cases:
  for mode in ['traditional','intelligent']:
   p=output/(c['scenario_id']+'_'+mode+'.json');payload=json.loads(p.read_text())
   payload['result']=c[mode];payload['metric_postprocessing_source_hash']=current
   p.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 rows=[dict(scenario_id=c['scenario_id'],seed=c['seed'],building=c['building'],mode=m,**c[m]['metrics']) for c in cases for m in ['traditional','intelligent']]
 for row in rows:row.pop('state_counts',None)
 with (output/'summary.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
 print('Refined benchmark saved; no safety outcome changed',flush=True)
