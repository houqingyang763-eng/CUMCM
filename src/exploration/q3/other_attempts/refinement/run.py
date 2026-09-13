"""保留全部胜负与失败的配对批次；冻结第二站，单独比较后续增量。"""
import argparse
import concurrent.futures
import hashlib
import json
import statistics
import time
from pathlib import Path

from refined import RefinedPolicy
from posterior import a

HERE=Path(__file__).resolve().parent


def selection_for(case, directory):
    path=directory/'selection.json'
    state=a.first_state(case)
    if path.exists():
        record=json.loads(path.read_text())
        if record['history_seed']!=a.history_seed(state):
            raise AssertionError('cached selection history mismatch')
        return record['selected']
    start=time.perf_counter()
    cache=a.HERE/'runs/confirm'/case.name/'selection.json'
    if cache.exists():
        selection=json.loads(cache.read_text())
        selected=next(c for c in selection['candidates'] if c['id']==selection['position'])
        origin='existing_public_first_station_selection'
    elif case.seed==269525288:
        raw=json.loads((a.HERE/'demonstration/replay.json').read_text())
        selection=raw['selection']
        selected=next(c for c in selection['candidates'] if c['id']==selection['position'])
        origin='demonstration_public_first_station_selection'
    else:
        selection=a.select(state,16)
        selected=next(c for c in selection['candidates'] if c['id']==selection['position'])
        origin='computed_from_public_first_station_state'
    a.base.dump(path,{'selected':selected,'history_seed':a.history_seed(state),'origin':origin,'wall_s':time.perf_counter()-start})
    return selected


def task(data):
    case_data,out,modes,samples=data
    case=a.Scenario.from_dict(case_data)
    directory=Path(out)/case.name
    directory.mkdir(parents=True,exist_ok=True)
    selected=selection_for(case,directory)
    old=a.base.create_policy
    summary={}
    for mode in modes:
        path=directory/mode/'result.json'
        if path.exists():
            summary[mode]=json.loads(path.read_text())
            continue
        try:
            if mode=='baseline':
                a.base.create_policy=old
                name='baseline'
            elif mode=='current':
                a.base.create_policy=lambda name,config:(a.AdaptivePolicy(selected),a.CoverageInformationState())
                name='patrol'
            else:
                level=int(mode[-1])
                a.base.create_policy=lambda name,config:(RefinedPolicy(selected,level,samples),a.CoverageInformationState())
                name='patrol'
            a.base.execute_case(case_data,name,a.CONFIG,directory/mode,
                                {'action_limit':3000,'wall_limit_s':1200,'virtual_limit_s':10800})
        finally:
            a.base.create_policy=old
        summary[mode]=json.loads(path.read_text())
        print(json.dumps({'case':case.name,'mode':mode,'success':summary[mode]['success'],
                          'min':round(summary[mode]['total_s']/60,3),'wall_s':round(summary[mode]['wall_s'],1),
                          'error':summary[mode]['failreason']},ensure_ascii=False),flush=True)
    return case.name


def summarize(out,modes):
    cases=json.loads((out/'cases.json').read_text())
    rows=[]
    for c in cases:
        row={'case':c['name'],'layout':c['layout'],'noise':c['noise']}
        for mode in modes:
            path=out/c['name']/mode/'result.json'
            if path.exists():row[mode]=json.loads(path.read_text())
        rows.append(row)
    stats={'cases':len(cases),'modes':modes,'rows':rows,'summary':{}}
    for mode in modes:
        data=[r[mode] for r in rows if mode in r]
        all_clear=len(data)==len(cases) and all(r['success'] for r in data)
        s={'finished':len(data),'all_clear':all_clear,'failures':[r['case'] for r in data if not r['success']]}
        if all_clear:
            s.update(mean_min=statistics.mean(r['total_s']/60 for r in data),
                     per_source_min=statistics.mean(r['per_source_s']/60 for r in data),
                     worst_min=max(r['total_s']/60 for r in data),
                     mean_wall_s=statistics.mean(r['wall_s'] for r in data))
            if mode!='current' and all('current' in r and r['current']['success'] for r in rows):
                delta=[(r['current']['total_s']-r[mode]['total_s'])/60 for r in rows]
                s.update(saving_min=statistics.mean(delta),wins=sum(d>1e-6 for d in delta),losses=sum(d<-1e-6 for d in delta),
                         worst_loss_min=max(0,-min(delta)))
        stats['summary'][mode]=s
    a.base.dump(out/'summary.json',stats)
    print(json.dumps(stats['summary'],ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--stage',choices=['development','confirm','stress'],required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--modes',nargs='+',default=['current','f1','f2','f3'])
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--samples',type=int,default=4)
    args=p.parse_args()
    out=args.out
    out.mkdir(parents=True,exist_ok=True)
    if args.stage=='development':
        cases=[a.Scenario.from_dict(json.loads((a.HERE/'demonstration/case.json').read_text()))]
        cases += [a.base.generate(seed,layout,noise) for seed,layout,noise in
                  [(280100,'uniform','smooth'),(280106,'edge','smooth'),(280113,'cluster','smooth'),(280119,'line','smooth')]]
    elif args.stage=='stress':
        cases=a.base.make_cases('stress')
    else:
        cases=[a.base.generate(310100+i,layout,noise) for i,(layout,noise) in enumerate(
               ( (l,n) for l in ('uniform','edge','cluster','line') for n in ('smooth','biased','hashed') for _ in range(2)))]
    paths=list(HERE.glob('*.py'))+list(a.HERE.glob('*.py'))+list((HERE.parent/'probability_patrol').glob('*.py'))+list((a.HERE.parents[1]/'b_adaptive_q3').glob('*.py'))+[a.HERE.parents[1]/'b_overnight/coverage.py']
    hashes={str(path.relative_to(a.base.ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    manifest={'stage':args.stage,'modes':args.modes,'samples':args.samples,'hashes':hashes,'time':time.time()}
    if (out/'manifest.json').exists():
        old=json.loads((out/'manifest.json').read_text())
        if old['hashes']!=hashes:
            raise ValueError('source changed; use new output directory')
    else:
        a.base.dump(out/'manifest.json',manifest)
        a.base.dump(out/'cases.json',[c.to_dict() for c in cases])
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs=[pool.submit(task,(c.to_dict(),str(out),args.modes,args.samples)) for c in cases]
        for f in concurrent.futures.as_completed(jobs):
            try:print('completed '+f.result(),flush=True)
            except Exception as exc:print('CASE WORKER FAILED: '+repr(exc),flush=True)
            summarize(out,args.modes)
    summarize(out,args.modes)


if __name__=='__main__':main()
