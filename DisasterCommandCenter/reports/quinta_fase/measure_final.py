from pathlib import Path
import ast,json,subprocess,sys,shutil,os
ROOT=Path(__file__).resolve().parents[2]
p=ROOT/'reports/quinta_fase/performance.json';old=json.loads(p.read_text())
shutil.copy2(p,ROOT/'reports/quinta_fase/performance_proactive.json')
tree=ast.parse((ROOT/'reports/quinta_fase/measure_before_after.py').read_text())
code=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CODE' for t in n.targets))
print('Measuring final stationary-obstacle policy, 240 turns',flush=True)
r=subprocess.run([sys.executable,'-B','-',str(ROOT)],input=code,text=True,capture_output=True,encoding='utf-8',env={**os.environ,'PYTHONUTF8':'1'},check=True)
new=json.loads(r.stdout)
result=dict(before=old['before'],after=new,unoptimized=old['unoptimized'],connectivity_only=old['connectivity_only'],budget_cap_only=old['budget_cap_only'],proactive_only=old['after'],
 connectivity_preserved_outcome=old['connectivity_preserved_outcome'],
 identical_fire=old['before']['fire_hash']==new['fire_hash'],identical_smoke=old['before']['smoke_hash']==new['smoke_hash'],
 description='Sequential, isolated 240-turn measurements with same physical inputs. Final includes stationary obstacles, calm fix and common component cache.')
p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:result[k]['seconds_per_turn'] for k in ['before','unoptimized','budget_cap_only','proactive_only','after']}),flush=True)
print('Same physics:',result['identical_fire'],result['identical_smoke'],flush=True)
