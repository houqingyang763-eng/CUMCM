"""独立实验入口；实际真值仅用于环境和验证。"""
import argparse
import concurrent.futures
import hashlib
import json
import statistics
import time
from pathlib import Path

from planner import BeliefTreePolicy, RefinedPolicy, a

HERE = Path(__file__).resolve().parent


def task(data):
    raw,out,modes,iterations,particles,wall = data
    directory = Path(out)/raw['name']
    old = a.base.create_policy
    for mode in modes:
        result = directory/mode/'result.json'
        if result.exists():
            continue
        try:
            if mode == 'baseline':
                a.base.create_policy = old
                name = 'baseline'
            elif mode == 'f3':
                a.base.create_policy = lambda name,config:(RefinedPolicy(level=3),a.CoverageInformationState())
                name = 'patrol'
            else:
                depth = int(mode[-1])
                def create(name,config):
                    policy = BeliefTreePolicy(depth,iterations,particles)
                    policy.log_path = directory/mode/'decisions.jsonl'
                    return policy,a.CoverageInformationState()
                a.base.create_policy = create
                name = 'patrol'
            a.base.execute_case(raw,name,a.CONFIG,directory/mode,
                                dict(action_limit=1000,wall_limit_s=wall,virtual_limit_s=10800))
        finally:
            a.base.create_policy = old
        row = json.loads(result.read_text(encoding='utf-8'))
        print(json.dumps(dict(case=raw['name'],mode=mode,success=row['success'],
                              min=row['total_s']/60,wall_s=row['wall_s'],error=row['failreason']),ensure_ascii=False),flush=True)
    return raw['name']


def summarize(out,modes):
    cases = json.loads((out/'cases.json').read_text(encoding='utf-8'))
    rows = []
    for raw in cases:
        row = dict(case=raw['name'],layout=raw['layout'],noise=raw['noise'])
        for mode in modes:
            path = out/raw['name']/mode/'result.json'
            if path.exists():
                row[mode] = json.loads(path.read_text(encoding='utf-8'))
        rows.append(row)
    summary = {}
    for mode in modes:
        values = [r[mode] for r in rows if mode in r]
        item = dict(finished=len(values),all_clear=len(values)==len(cases) and all(v['success'] for v in values),
                    failures=[v['case'] for v in values if not v['success']])
        if item['all_clear']:
            item.update(mean_min=statistics.mean(v['total_s']/60 for v in values),
                        per_source_min=statistics.mean(v['per_source_s']/60 for v in values),
                        worst_min=max(v['total_s']/60 for v in values),
                        mean_wall_s=statistics.mean(v['wall_s'] for v in values))
            for ref in ('f3','baseline','u1'):
                if ref != mode and all(ref in r and r[ref]['success'] for r in rows):
                    ds = [(r[ref]['total_s']-r[mode]['total_s'])/60 for r in rows]
                    item['vs_'+ref] = dict(saving_min=statistics.mean(ds),wins=sum(d>1e-6 for d in ds),
                                            losses=sum(d<-1e-6 for d in ds),worst_loss_min=max(0.,-min(ds)))
        summary[mode] = item
    a.base.dump(out/'summary.json',dict(summary=summary,rows=rows))
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--stage',choices=['smoke','development','confirm','stress'],default='smoke')
    p.add_argument('--modes',nargs='+',default=['f3','u1','t3','baseline'])
    p.add_argument('--iterations',type=int,default=96)
    p.add_argument('--particles',type=int,default=16)
    p.add_argument('--workers',type=int,default=3)
    p.add_argument('--wall',type=float,default=7200)
    p.add_argument('--count',type=int)
    p.add_argument('--indices',type=int,nargs='+')
    args = p.parse_args()
    if args.stage == 'stress':
        cases = a.base.make_cases('stress')
    elif args.stage == 'smoke':
        cases = [a.base.generate(330000,'uniform','hashed')]
    else:
        base = 330010 if args.stage == 'development' else 330100
        repeats = 1 if args.stage == 'development' else 2
        pairs = [(l,n) for l in ('uniform','edge','cluster','line') for n in ('smooth','biased','hashed') for _ in range(repeats)]
        cases = [a.base.generate(base+i,l,n) for i,(l,n) in enumerate(pairs)]
    if args.count:
        cases = cases[:args.count]
    if args.indices:
        cases = [cases[i] for i in args.indices]
    args.out.mkdir(parents=True,exist_ok=True)
    paths = list(HERE.glob('*.py')) + list((HERE.parent/'refinement').glob('*.py')) + list(a.HERE.glob('*.py'))
    paths += list((HERE.parent/'probability_patrol').glob('*.py')) + list((a.base.ROOT/'experiments/b_adaptive_q3').glob('*.py'))
    paths += [a.base.ROOT/'experiments/b_overnight/coverage.py']
    manifest = dict(stage=args.stage,modes=args.modes,iterations=args.iterations,particles=args.particles,
                    cases=[c.name for c in cases],
                    hashes={str(p.relative_to(a.base.ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    file = args.out/'manifest.json'
    if file.exists() and json.loads(file.read_text(encoding='utf-8')) != manifest:
        raise ValueError('configuration/source changed: use a new run directory')
    a.base.dump(file,manifest)
    a.base.dump(args.out/'cases.json',[c.to_dict() for c in cases])
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(task,(c.to_dict(),str(args.out),args.modes,args.iterations,args.particles,args.wall)) for c in cases]
        for job in concurrent.futures.as_completed(jobs):
            print('completed '+job.result(),flush=True)
            print(json.dumps(summarize(args.out,args.modes),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
