"""本地配对执行，原F3不改，失败保留。"""
import argparse
import concurrent.futures
import hashlib
import json
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from policy import UtilityPolicy,a
from refined import RefinedPolicy
from diagnose import replay

HERE=Path(__file__).resolve().parent


def task(case_data,out,modes):
    case=a.Scenario.from_dict(case_data);directory=Path(out)/case.name;directory.mkdir(parents=True,exist_ok=True)
    path=directory/'selection.json'
    if path.exists():selection=json.loads(path.read_text(encoding='utf-8'))
    else:
        start=time.perf_counter();selection=a.select(a.first_state(case),16)
        selection['selected']=next(c for c in selection['candidates'] if c['id']==selection['position'])
        selection['wall_s']=time.perf_counter()-start;a.base.dump(path,selection)
    original=a.base.create_policy
    for mode in modes:
        target=directory/mode
        if (target/'result.json').exists():continue
        try:
            if mode=='f3':a.base.create_policy=lambda name,config:(RefinedPolicy(selection['selected'],3,4),a.CoverageInformationState())
            else:a.base.create_policy=lambda name,config:(UtilityPolicy(selection['selected'],int(mode[-1])),a.CoverageInformationState())
            a.base.execute_case(case_data,'patrol',a.CONFIG,target,{'action_limit':3000,'wall_limit_s':1200,'virtual_limit_s':10800})
        finally:a.base.create_policy=original
        result=json.loads((target/'result.json').read_text(encoding='utf-8'))
        if result['success']:a.base.dump(target/'audit.json',{'replayed_actions':replay(target,case)})
        print(json.dumps({'case':case.name,'mode':mode,'success':result['success'],'minutes':result['total_s']/60,'cpu_s':result['wall_s'],'error':result['failreason']},ensure_ascii=False),flush=True)
    return case.name


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--cases',type=Path,required=True)
    p.add_argument('--modes',nargs='+',default=['f3','s1','s2','s3']);p.add_argument('--workers',type=int,default=1)
    args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    cases=json.loads(args.cases.read_text(encoding='utf-8'));a.base.dump(args.out/'cases.json',cases)
    paths=list(HERE.glob('*.py'));manifest={'started':time.time(),'modes':args.modes,'hashes':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}
    if (args.out/'manifest.json').exists():
        old=json.loads((args.out/'manifest.json').read_text(encoding='utf-8'))
        assert old['hashes']==manifest['hashes'],'changed code: use new output root'
    else:a.base.dump(args.out/'manifest.json',manifest)
    if args.workers==1:
        for case in cases:task(case,str(args.out),args.modes)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
            for f in concurrent.futures.as_completed([pool.submit(task,c,str(args.out),args.modes) for c in cases]):print(f.result(),flush=True)


if __name__=='__main__':main()
