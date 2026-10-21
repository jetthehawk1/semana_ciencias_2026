from pathlib import Path
import sys,inspect,textwrap,hashlib,argparse
from collections import defaultdict,deque
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
import simulation.hazard_impact as engine
from tools.compare_evacuation_modes_v2 import benchmark_scenarios,run_case,report_json,input_fingerprint


def resolve(ctrl,tracker,blocked,doors,distances,previous,eligible,priorities):
    policy=getattr(ctrl,'predictive',None)
    if policy is None:return 0
    occupied=ctrl._occupied()
    moved={pid for pid,point in previous.items() if ctrl.manager.people[pid].position!=point}
    pending=[pid for pid in ctrl.ids if pid not in moved and eligible(pid)
             and ctrl.manager.people[pid].building_id in policy.affected]
    pending.sort(key=lambda pid:(-(priorities or {}).get(pid,0),pid))
    watchers=defaultdict(set)
    for pid in pending:
        person=ctrl.manager.people[pid]
        for dx,dy in ((0,-1),(1,0),(0,1),(-1,0)):
            watchers[person.x+dx,person.y+dy].add(pid)
    queue=deque(pending);queued=set(pending);extra=0
    while queue:
        pid=queue.popleft();queued.discard(pid)
        if pid in moved:continue
        p=ctrl.manager.people[pid];name=p.building_id
        if name is None:continue
        old=p.position
        if old in doors[name]:
            target=doors[name][old]
            if target in occupied or target in blocked:continue
            p.building_id=None;ctrl.exited[pid]=name
        else:
            distance=distances[name];current=ctrl.current_indoor_distance(p,distance)
            if current is None:continue
            choices=ctrl.indoor_candidates(p,distance,current,occupied,blocked)
            if not choices:continue
            target=choices[0]
        occupied.remove(old);occupied.add(target);p.x,p.y=target
        moved.add(pid);extra+=1
        for other in sorted(watchers[old]):
            if other not in moved and other not in queued:
                queue.append(other);queued.add(other)
    return extra


def experiment(scenario):
    original=inspect.getsource(engine.HazardEvacuationController.step_with_hazards)
    source=textwrap.dedent(original)
    source=source.replace('    fire = set(burning)', '    fire = set(burning)\n    previous_for_retry = {pid:self.manager.people[pid].position for pid in self.ids}')
    source=source.replace('    self._priority = ', '    late = resolve(self,tracker,fire,doors,distances,previous_for_retry,eligible,priority_by_person)\n    moved += late\n    waiting -= late\n    self._priority = ')
    namespace={**vars(engine),'resolve':resolve};exec(compile(source,'<dependency_resolution_experiment>','exec'),namespace)
    engine.HazardEvacuationController.step_with_hazards=namespace['step_with_hazards']
    case=next(c for c in benchmark_scenarios() if c['scenario_id']==scenario)
    result=run_case(case,'intelligent')
    report=dict(experiment='bounded waiting dependencies, only previously unmoved eligible pupils',
        base_actor_hash=input_fingerprint(),patch_source=source,helper_source=inspect.getsource(resolve),
        scenario=case,result=result)
    (ROOT/f'reports/septima_fase/interior_dependencies_{scenario}.json').write_text(report_json(report),encoding='utf-8')
    print(result['metrics'],flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('scenario');a=parser.parse_args();experiment(a.scenario)
