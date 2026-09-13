"""A/B/AB三个冻结候选，各八例；独立进程隔离路线函数与工厂。"""
import argparse
import concurrent.futures
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

from light_route import ROOT,a,LightPolicy,RunContext,route_context
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from prepare_team import check,read,digest,MANIFEST


def execute(payload):
    case,item,mode,out=payload
    selection=read(ROOT/item['baseline_selection']);selection_s=selection['wall_s']
    context=RunContext(mode,time.perf_counter()+1200-selection_s)
    path=Path(out)/mode/case['name']; previous=a.base.create_policy
    try:
        with route_context(context):
            a.base.create_policy=lambda name,config:(LightPolicy(selection['selected']),a.CoverageInformationState())
            a.base.execute_case(case,'light_'+mode,a.CONFIG,path,
                dict(action_limit=3000,virtual_limit_s=10800,wall_limit_s=1200-selection_s))
    finally:a.base.create_policy=previous
    result=read(path/'result.json')
    result.update(mode=mode,cached_opening_selection_wall_s=selection_s,
        accounted_wall_s=result['wall_s']+selection_s,
        opening_selection='identical public history cache; historical selection time charged separately')
    a.base.dump(path/'result.json',result)
    print(json.dumps(dict(mode=mode,case=case['name'],success=result['success'],minutes=result['total_s']/60,
        wall_s=result['accounted_wall_s'],failreason=result['failreason']),ensure_ascii=False),flush=True)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    manifest,cases,receipt=check()
    out=args.out.resolve()
    assert out.is_relative_to(ROOT/'outputs/experiments')
    out.mkdir(parents=True,exist_ok=False)
    files=[HERE/'light_route.py',HERE/'light_run.py',HERE/'test_light.py',HERE/'LIGHTWEIGHT_DESIGN.md',MANIFEST]
    hashes={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    a.base.dump(out/'manifest.json',dict(started_unix=time.time(),python=platform.python_version(),
        modes=['A','B','AB'],workers=args.workers,code_hashes=hashes,baseline_manifest=manifest,
        input_validation=receipt,limits=dict(actions=3000,virtual_s=10800,accounted_wall_s=1200)))
    a.base.dump(out/'cases.json',cases)
    items={c['name']:c for c in manifest['cases']}; results=[]
    payloads=[(case,items[case['name']],mode,str(out)) for case in cases for mode in ('A','B','AB')]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(execute,p) for p in payloads]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result());a.base.dump(out/'progress.json',dict(finished=len(results),planned=24,results=results))
    a.base.dump(out/'completion.json',dict(finished=len(results),all_clear=all(r['success'] for r in results),finished_unix=time.time()))


if __name__=='__main__':main()
