"""冻结A加一个挪站因素，共8例。"""
import argparse
import concurrent.futures
import hashlib
import platform
import time
from pathlib import Path
from relocate import lr,relocation_context,RelocationPolicy
from relocation_probe import BASE,OUT,read,sha
from light_run import check,MANIFEST

HERE=Path(__file__).resolve().parent

def validate():
    manifest,cases,receipt=check();baseline=read(BASE/'manifest.json')
    assert manifest==baseline['baseline_manifest']
    for rel,h in baseline['code_hashes'].items():assert sha(lr.ROOT/rel)==h,rel
    analysis=read(BASE/'analysis.json')
    for rel,h in analysis['source_hashes'].items():
        if '/A/' in rel:assert sha(lr.ROOT/rel)==h,rel
    probe=read(OUT/'probe.json');assert probe['gate']
    for rel,h in probe['code_hashes'].items():assert sha(lr.ROOT/rel)==h,rel
    return manifest,cases,receipt,baseline


def execute(payload):
    case,item,out=payload;selection=read(lr.ROOT/item['baseline_selection']);selection_s=selection['wall_s']
    context=lr.RunContext('A',time.perf_counter()+1200-selection_s)
    path=Path(out)/case['name'];previous=lr.a.base.create_policy
    try:
        with relocation_context(context):
            lr.a.base.create_policy=lambda name,config:(RelocationPolicy(selection['selected']),lr.a.CoverageInformationState())
            lr.a.base.execute_case(case,'A_plus_relocation',lr.a.CONFIG,path,
                dict(action_limit=3000,virtual_limit_s=10800,wall_limit_s=1200-selection_s))
    finally:lr.a.base.create_policy=previous
    result=read(path/'result.json');result.update(cached_opening_selection_wall_s=selection_s,accounted_wall_s=result['wall_s']+selection_s)
    lr.a.base.dump(path/'result.json',result)
    print(case['name'],result['success'],round(result['total_s']/60,4),'min',round(result['accounted_wall_s'],1),'wall seconds',result['failreason'],flush=True)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,default=2);args=p.parse_args()
    manifest,cases,receipt,baseline=validate();out=args.out.resolve()
    assert out.is_relative_to(lr.ROOT/'outputs/experiments');out.mkdir(parents=True,exist_ok=False)
    files=[HERE/n for n in ('relocate.py','run_relocation.py','test_relocation.py','RELOCATION_DESIGN.md')]+[MANIFEST,OUT/'probe.json']
    lr.a.base.dump(out/'manifest.json',dict(started_unix=time.time(),python=platform.python_version(),workers=args.workers,
        code_hashes={f.relative_to(lr.ROOT).as_posix():sha(f) for f in files},baseline_manifest=manifest,
        prior_run=BASE.relative_to(lr.ROOT).as_posix(),prior_freeze=baseline,input_validation=receipt,
        main_comparison='A_plus_relocation versus frozen A',limits=dict(actions=3000,virtual_s=10800,accounted_wall_s=1200)))
    lr.a.base.dump(out/'cases.json',cases);items={v['name']:v for v in manifest['cases']};results=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(execute,(case,items[case['name']],str(out))) for case in cases]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result());lr.a.base.dump(out/'progress.json',dict(finished=len(results),planned=8,results=results))
    lr.a.base.dump(out/'completion.json',dict(finished=len(results),all_clear=all(r['success'] for r in results),finished_unix=time.time()))

if __name__=='__main__':main()
