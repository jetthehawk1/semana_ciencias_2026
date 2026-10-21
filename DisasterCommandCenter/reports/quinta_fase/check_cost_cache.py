from pathlib import Path
import json,pickle,random,sys
from time import perf_counter
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from routing.weighted_astar import weighted_astar
from routing.graph import CampusGraph
from routing.congestion import CongestionManager
from simulation.campus_map import CampusMap
namespace={};exec((ROOT/'reports/quinta_fase/weighted_astar_before_cost_cache.py').read_text(),namespace)
original=namespace['weighted_astar'];rng=random.Random(2026)
checks=0
for sample in range(40):
 campus=CampusMap(17,13);campus.fill_terrain('floor');graph=CampusGraph(campus)
 blocked={(rng.randrange(17),rng.randrange(13)) for _ in range(35)}-{(1,1),(15,11)}
 values=[[rng.randrange(0,8)/3 for _ in range(17)] for _ in range(13)]
 field=SimpleNamespace(risk_cost=lambda x,y:values[y][x])
 congestion=CongestionManager();congestion.congestion_map={(rng.randrange(17),rng.randrange(13)):rng.randrange(5) for _ in range(20)}
 kwargs=dict(graph=graph,start=(1,1),goal=(15,11),blocked_cells=blocked,risk_field=field,congestion_manager=congestion)
 assert original(**kwargs)==weighted_astar(**kwargs)
 checks+=1
s=pickle.loads((ROOT/'reports/quinta_fase/turn240_state.pickle').read_bytes())
settled={p.position for p in s.people if s.router.at_meeting(p)}
blocked=s.last_blocked_cells|settled
selected=sorted(s.router.assignments,key=lambda pid:len(s.router.paths[pid]),reverse=True)[:25]
times={'original':0.,'cached':0.}
for pid in selected:
 p=s.manager.get_person(pid);goal=s.router.assignments[pid][1]
 kwargs=dict(graph=s.router.graph,start=p.position,goal=goal,blocked_cells=blocked-{p.position},
             congestion_manager=s.router.congestion,risk_field=s.decision_policy)
 t=perf_counter();before=original(**kwargs);times['original']+=perf_counter()-t
 t=perf_counter();after=weighted_astar(**kwargs);times['cached']+=perf_counter()-t
 assert before==after,pid
 checks+=1
report=dict(identical_paths=checks,random_graphs=40,real_turn240_requests=len(selected),query_seconds=times,
 note='Same graph, heuristic, heap ordering, weights and immutable cost inputs; only per-query cost memoization differs. Diagnostic ran alongside validation; use isolated episode for performance conclusions.')
(ROOT/'reports/quinta_fase/cost_cache_equivalence.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report),flush=True)
