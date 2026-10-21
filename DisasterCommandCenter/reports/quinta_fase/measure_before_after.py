"""Local verification artifact: restores fourth-phase snapshot into an isolated temporary copy."""
from pathlib import Path
import json, os, shutil, subprocess, sys, tempfile
ROOT=Path(__file__).resolve().parents[2]
PYTHON=Path(sys.executable)
CODE=r"""
import sys,json,hashlib
from pathlib import Path
from time import perf_counter
import numpy as np
root=Path(sys.argv[1]);sys.path[:0]=[str(root/'src'),str(root)]
from simulation.functional_scenario import FunctionalSimulation
t=perf_counter();s=FunctionalSimulation(root,mode='optimizado');s.start_alarm();init=perf_counter()-t
for _ in range(240): s.step()
elapsed=perf_counter()-t
f=s.environment.fire
print(json.dumps(dict(initialization_seconds=init,elapsed_seconds=elapsed,seconds_per_turn=(elapsed-init)/240,turns=240,
fire_hash=hashlib.sha256(json.dumps([sorted(f.burning.items()),sorted(f.burned),f.spotting_events],sort_keys=True).encode()).hexdigest(),
smoke_hash=hashlib.sha256(np.asarray(s.environment.smoke.concentrations,dtype='<f8').tobytes()).hexdigest(),
summary=s.summary())))
"""
def measure(root):
 p=subprocess.run([str(PYTHON),'-B','-',str(root)],input=CODE,text=True,capture_output=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'},check=True)
 return json.loads(p.stdout)
with tempfile.TemporaryDirectory(prefix='dcc_phase5_before_') as tmp:
 copied=Path(tmp)/'DisasterCommandCenter'
 shutil.copytree(ROOT,copied,ignore=shutil.ignore_patterns('reports','exports','.venv','venv','__pycache__','.pytest_cache','*.pyc','.env'))
 before=ROOT/'reports/quinta_fase/before'
 for p in before.rglob('*'):
  if p.is_file() and p.name!='protected_hashes.json':
   target=copied/p.relative_to(before);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
 print('Measuring fourth-phase snapshot, 240 turns',flush=True)
 old=measure(copied)
 print('Measuring fifth-phase final, 240 turns',flush=True)
 new=measure(ROOT)
 result=dict(before=old,after=new,identical_fire=old['fire_hash']==new['fire_hash'],identical_smoke=old['smoke_hash']==new['smoke_hash'],description='Sequential isolated measurements, same seed 2026, E .75, origin 235,166, optimized manager, 240 steps; no assertions or rendering in timed loops.')
 (ROOT/'reports/quinta_fase/performance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:{m:v[m] for m in ['elapsed_seconds','seconds_per_turn']} for k,v in [('before',old),('after',new)]}),flush=True)
 print('Physics equal:',result['identical_fire'],result['identical_smoke'],flush=True)
