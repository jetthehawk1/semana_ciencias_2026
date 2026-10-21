from pathlib import Path
import sys,inspect,textwrap,hashlib,json,argparse,math
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
import simulation.interior_prediction as interior
from tools.compare_evacuation_modes_v2 import benchmark_scenarios,run_case,report_json,input_fingerprint

def experiment(scenario):
    original=inspect.getsource(interior.PredictiveInteriorPolicy._refuge_fields)
    source=textwrap.dedent(original)
    source=source.replace("        best = max(self.quality(p) for p in candidates)","""        occupied = self.controller._occupied()
        candidates = [p for p in candidates if p not in occupied]
        if not candidates:
            continue
        mobile = sum(p.building_id == name and self.tracker.records[p.person_id].level != 'incapacitada'
                     for p in self.controller.manager.people.values())
        wanted = max(math.ceil(len(candidates)*.25), mobile)
        scores = sorted((self.quality(p) for p in candidates), reverse=True)
        best = scores[min(len(scores), wanted)-1]""")
    source=source.replace("self.quality(p) >= best-self.config['refuge_minimum_gain']", "self.quality(p) >= best")
    assert source != textwrap.dedent(original)
    assert 'wanted = max' in source
    namespace={**vars(interior),'math':math}
    exec(compile(source,'<distributed_refuge_experiment>','exec'),namespace)
    interior.PredictiveInteriorPolicy._refuge_fields=namespace['_refuge_fields']
    case=next(c for c in benchmark_scenarios() if c['scenario_id']==scenario)
    result=run_case(case,'intelligent')
    report=dict(experiment='distributed free refuge tier; minimum one goal per mobile building occupant; top quarter',
                base_actor_hash=input_fingerprint(),patch_source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                patch_source=source,scenario=case,result=result)
    (ROOT/f'reports/septima_fase/distributed_refuges_{scenario}.json').write_text(report_json(report),encoding='utf-8')
    print(result['metrics'],flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('scenario');args=parser.parse_args();experiment(args.scenario)
