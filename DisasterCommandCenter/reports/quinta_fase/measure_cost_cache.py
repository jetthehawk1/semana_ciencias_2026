from pathlib import Path
from copy import deepcopy
import ast,json,subprocess,sys,shutil,os
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'reports/quinta_fase/performance.json';old=json.loads(p.read_text())
shutil.copy2(p,ROOT/'reports/quinta_fase/performance_uncached_final.json')
tree=ast.parse((ROOT/'reports/quinta_fase/measure_before_after.py').read_text())
code=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CODE' for t in n.targets))
print('Measuring final per-search cost cache, 240 turns',flush=True)
r=subprocess.run([sys.executable,'-B','-',str(ROOT)],input=code,text=True,capture_output=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'},check=True)
new=json.loads(r.stdout)
a=deepcopy(old['after']['summary']);b=deepcopy(new['summary'])
a.pop('confirmed_forecast_departures',None);b.pop('confirmed_forecast_departures',None)
result={**old,'after':new,'uncached_final':old['after'],
 'identical_decision_summary_after_cost_cache':a==b,
 'identical_fire':old['before']['fire_hash']==new['fire_hash'],
 'identical_smoke':old['before']['smoke_hash']==new['smoke_hash'],
 'description':'Final cached implementation measured for 240 turns, no other simulations running. Only diagnostic confirmed-departure counter may differ; all decision summary fields must match uncached final.'}
p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:result[k]['seconds_per_turn'] for k in ['before','uncached_final','after']}),flush=True)
print('Same decision outcome:',result['identical_decision_summary_after_cost_cache'],flush=True)
assert result['identical_decision_summary_after_cost_cache']
assert result['identical_fire'] and result['identical_smoke']
