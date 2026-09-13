"""本地配对实验；先选动作，落盘冻结，再在真实自建案例执行。"""
import argparse
import concurrent.futures
import hashlib
import json
import statistics
import time
from pathlib import Path
import adaptive as a

HERE=Path(__file__).resolve().parent


def task(data):
    case_data,out,samples,salt,prior=data
    case=a.Scenario.from_dict(case_data)
    directory=Path(out)/case.name
    directory.mkdir(parents=True,exist_ok=True)
    start=time.perf_counter()
    state=a.first_state(case)
    selection=a.select(state,samples,salt,prior)
    selection['wall_s']=time.perf_counter()-start
    a.base.dump(directory/'selection.json',selection)
    old=a.base.create_policy
    try:
        for mode in ('fixed','position','joint','baseline'):
            if mode=='baseline':
                a.base.create_policy=old
                name,config='baseline',{}
            else:
                chosen=next(r for r in selection['candidates'] if r['id']==selection[mode])
                a.base.create_policy=lambda name,config, chosen=chosen: (a.AdaptivePolicy(chosen),a.CoverageInformationState())
                name,config='patrol',a.CONFIG
            a.base.execute_case(case_data,name,config,directory/mode,
                                {'action_limit':3000,'wall_limit_s':180,'virtual_limit_s':10800})
    finally:
        a.base.create_policy=old
    return case.name,selection['wall_s']


def summarize(out):
    rows=[]
    for path in sorted(Path(out).glob('*/selection.json')):
        sel=json.loads(path.read_text())
        row={'case':path.parent.name,'selection_wall_s':sel['wall_s']}
        for mode in ('fixed','position','joint','baseline'):
            r=json.loads((path.parent/mode/'result.json').read_text())
            row[mode]=r
            if mode!='baseline':
                chosen=next(c for c in sel['candidates'] if c['id']==sel[mode])
                row[mode+'_choice']=chosen['id']
                row[mode+'_predicted_s']=chosen['mean_s']
        rows.append(row)
    result={'cases':len(rows),'all_clear':all(r[m]['success'] for r in rows for m in ('fixed','position','joint','baseline')),'rows':rows}
    if result['all_clear'] and rows:
        result['means_min']={m:statistics.mean(r[m]['total_s']/60 for r in rows) for m in ('fixed','position','joint','baseline')}
        result['saving_vs_fixed_min']={m:result['means_min']['fixed']-result['means_min'][m] for m in ('position','joint')}
    a.base.dump(Path(out)/'summary.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',choices=['pilot','confirm','sensitivity'],default='pilot')
    p.add_argument('--samples',type=int,default=16)
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--out',required=True)
    p.add_argument('--salt',type=int,default=0)
    p.add_argument('--prior',choices=['uniform','minimum'],default='uniform')
    args=p.parse_args()
    out=Path(args.out)
    if out.exists():
        raise ValueError('output exists; preserve previous batch')
    out.mkdir(parents=True)
    if args.stage=='pilot':
        cases=[a.base.generate(270100+i,layout,'hashed') for i,layout in enumerate(('uniform','edge','cluster','line'))]
    else:
        cases=[a.base.generate(280100+i,layout,noise) for i,(layout,noise) in enumerate(
            ( (l,n) for l in ('uniform','edge','cluster','line') for n in ('smooth','biased','hashed') for _ in range(2)))]
        if args.stage=='sensitivity':
            cases=cases[::3]
    a.base.dump(out/'cases.json',[c.to_dict() for c in cases])
    dependencies=list(HERE.glob('*.py'))+list((HERE.parent/'probability_patrol').glob('*.py'))+list((HERE.parents[1]/'b_adaptive_q3').glob('*.py'))+[HERE.parents[1]/'b_overnight/coverage.py']
    hashes={str(f.relative_to(HERE.parents[2])):hashlib.sha256(f.read_bytes()).hexdigest() for f in dependencies}
    a.base.dump(out/'manifest.json',{'args':vars(args),'hashes':hashes,'created_unix':time.time()})
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs=[pool.submit(task,(c.to_dict(),str(out),args.samples,args.salt,args.prior)) for c in cases]
        for future in concurrent.futures.as_completed(jobs):
            print(future.result(),flush=True)
    summarize(out)


if __name__=='__main__':
    main()
