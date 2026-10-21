from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from tools.compare_evacuation_modes import scenarios,run_case,compare

def execute(task):
 scenario,mode=task
 return scenario,mode,run_case(scenario,mode)

if __name__=='__main__':
 output=ROOT/'reports/evacuation_comparison'
 paths=sorted((ROOT/'src').rglob('*.py'))+[ROOT/'data/functional_scenario.json',ROOT/'tools/compare_evacuation_modes.py']
 source_hash=hashlib.sha256(b''.join(p.read_bytes() for p in paths)).hexdigest()
 pending=[]
 for scenario in scenarios(10,160,2026):
  for mode in ('traditional','intelligent'):
   p=output/(scenario['scenario_id']+'_'+mode+'.json')
   existing=json.loads(p.read_text()) if p.exists() else None
   if existing and existing.get('source_hash')==source_hash and existing.get('scenario')==scenario:
    print('Preserved',scenario['scenario_id'],mode,flush=True)
   else:pending.append((scenario,mode))
 print('Independent remaining runs:',len(pending),'workers=3 on 12 logical CPUs',flush=True)
 with ProcessPoolExecutor(max_workers=3) as pool:
  futures=[pool.submit(execute,task) for task in pending]
  for f in as_completed(futures):
   scenario,mode,result=f.result()
   p=output/(scenario['scenario_id']+'_'+mode+'.json')
   p.write_text(json.dumps(dict(source_hash=source_hash,scenario=scenario,result=result),indent=2)+'\n',encoding='utf-8')
   print('Saved',scenario['scenario_id'],mode,flush=True)
 compare(10,160,2026,output,resume=True)
