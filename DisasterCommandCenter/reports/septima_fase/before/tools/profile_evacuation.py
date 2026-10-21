"""Isolated timing and a separately timed profiler window; no physics shortcuts."""
from __future__ import annotations

import argparse
import cProfile
import io
import json
from pathlib import Path
import pstats
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from simulation.functional_scenario import FunctionalSimulation
from tools.compare_evacuation_modes import physical_digest
from tools.compare_evacuation_modes_v2 import input_fingerprint, report_json


def run(turns=240,output=None,profile_window=False,mode='intelligent'):
    output=Path(output or ROOT/'reports/sexta_fase');output.mkdir(parents=True,exist_ok=True)
    started=perf_counter();s=FunctionalSimulation(ROOT,mode='optimizado',evacuation_mode=mode);s.start_alarm()
    init=perf_counter()-started
    for turn in range(1,turns+1):
        s.step()
        if turn%40==0:print('timing',turn,flush=True)
    elapsed=perf_counter()-started
    flow=s.router.flow
    flow_bytes=(sum(a.nbytes for a in (flow.ids,flow.xs,flow.ys,flow.origins,flow.targets))+
        sum(a.nbytes for triple in flow.fields.values() for a in triple)+
        sum(a.nbytes for a in (flow.matrix.data,flow.matrix.indices,flow.matrix.indptr))) if flow else 0
    result=dict(turns=turns,initialization_seconds=init,elapsed_seconds=elapsed,seconds_per_turn=(elapsed-init)/turns,
        evacuation_mode=mode,
        source_hash=input_fingerprint(),
        physics_digest=physical_digest(s),metrics=s.metrics.result(s),summary=s.summary(),fire_contact_traces=s.fire_contact_traces,
        total_astar_searches=s.router.total_astar_searches,cache_hits=s.router.flow.hits if s.router.flow else 0,
        cache_misses=s.router.flow.misses if s.router.flow else 0,flow_field_usage=s.router.flow.usage if s.router.flow else 0,
        flow_rebuilds=s.router.flow.rebuilds if s.router.flow else 0)
    result['flow_array_bytes']=flow_bytes
    filename='performance_after.json' if mode=='intelligent' else 'performance_traditional.json'
    (output/filename).write_text(report_json(result),encoding='utf-8')
    if profile_window:
        sample=FunctionalSimulation(ROOT,mode='optimizado',evacuation_mode=mode);sample.start_alarm()
        for _ in range(59):sample.step()
        profiler=cProfile.Profile();profiler.enable()
        for _ in range(5):sample.step()
        profiler.disable();stream=io.StringIO()
        stats=pstats.Stats(profiler,stream=stream).sort_stats('cumulative');stats.print_stats(70)
        (output/'profile_after.txt').write_text(stream.getvalue(),encoding='utf-8')
        profiler.dump_stats(str(output/'profile_after.pstats'))
    print(json.dumps({k:result[k] for k in ('elapsed_seconds','seconds_per_turn','total_astar_searches','cache_hits','cache_misses','flow_field_usage')}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--turns',type=int,default=240)
    parser.add_argument('--output-dir',type=Path);parser.add_argument('--profile',action='store_true')
    parser.add_argument('--evacuation-mode',choices=('traditional','intelligent'),default='intelligent');args=parser.parse_args()
    if args.turns<1:parser.error('Positive turns required')
    run(args.turns,args.output_dir,args.profile,args.evacuation_mode)
