"""决策冻结后的离线诊断，真值只用于评估，绝不反馈到已执行策略。"""
import argparse
import concurrent.futures
import json
import math
import statistics
from pathlib import Path
import numpy as np
import adaptive as a


def oracle_task(data):
    case_data,selection_path=data
    case=a.Scenario.from_dict(case_data)
    state=a.first_state(case)
    selection=json.loads(Path(selection_path).read_text())
    costs={c['id']:a.rollout(state,case,c,True) for c in selection['candidates']}
    result={'case':case.name,'costs_s':costs,'best_position':min((c['id'] for c in selection['candidates'] if c['set']=='all'),key=costs.get),
            'best_joint':min(costs,key=costs.get)}
    a.base.dump(Path(selection_path).parent/'oracle_diagnostic.json',result)
    return result


def replay(directory,case):
    sources={s.channel:s for s in case.sources}
    cleared=set()
    q=(0.,0.)
    channel=1
    seconds=0.
    count=0
    for line in (directory/'actions.jsonl').read_text().splitlines():
        row=json.loads(line)
        response=row['response']
        p=tuple(row['position'])
        j=row['channel']
        source=sources.get(j) if j not in cleared else None
        distance=math.dist(p,source.position) if source else math.inf
        move=math.dist(q,p)/5
        switch=0
        if row['kind']=='measure':
            switch=int(channel!=j)
            operation=5
            expected='no_signal' if source is None or distance>source.radius else ('near' if distance<=5 else 'direction')
            assert response['measure_result']==expected
            if expected=='direction':
                bearing=math.degrees(math.atan2(source.position[1]-p[1],source.position[0]-p[0]))%360
                diff=abs((response['svd_deg']-bearing+180)%360-180)
                assert diff<=1.00500001
            channel=j
        else:
            ok=distance<=20
            assert (response['clear_result']=='success')==ok
            operation=5 if ok else 3
            if ok:
                cleared.add(j)
        seconds+=move+switch+operation
        assert abs(seconds-response['virtual_time_s'])<1e-6
        q=p
        count+=1
    assert len(cleared)==len(sources)
    result=json.loads((directory/'result.json').read_text())
    assert result['success'] and abs(seconds-result['total_s'])<1e-6
    return count


def analyze(out):
    out=Path(out)
    cases=[a.Scenario.from_dict(x) for x in json.loads((out/'cases.json').read_text())]
    rng=np.random.default_rng(290912)
    rows=[]
    action_count=0
    for case in cases:
        directory=out/case.name
        sel=json.loads((directory/'selection.json').read_text())
        oracle=json.loads((directory/'oracle_diagnostic.json').read_text())
        row={'case':case.name,'layout':case.layout}
        for mode in ('fixed','position','joint','baseline'):
            action_count+=replay(directory/mode,case)
            r=json.loads((directory/mode/'result.json').read_text())
            row[mode]=r['total_s']/60
            row[mode+'_move_min']=r['move_s']/60
            row[mode+'_scan_min']=(r['measure_s']+r['switch_s'])/60
            if mode!='baseline':
                chosen=next(c for c in sel['candidates'] if c['id']==sel[mode])
                row[mode+'_choice']=chosen['id']
                row[mode+'_channels']=len(chosen['channels'])
                row[mode+'_predicted']=chosen['mean_s']/60
                assert abs(oracle['costs_s'][chosen['id']]+a.first_state(case).virtual_time_s-r['total_s'])<1e-6
        for mode in ('position','joint'):
            row[mode+'_oracle_saving']=(oracle['costs_s'][sel['fixed']]-oracle['costs_s'][oracle['best_'+mode]])/60
        rows.append(row)
    report={'cases':len(rows),'independently_replayed_actions':action_count,'comparisons':{},'by_layout':{},'rows':rows}
    for mode in ('position','joint'):
        delta=np.array([r['fixed']-r[mode] for r in rows])
        predicted=np.array([r['fixed_predicted']-r[mode+'_predicted'] for r in rows])
        means=[]
        enough=all(sum(r['layout']==l for r in rows)>=2 for l in set(r['layout'] for r in rows))
        for _ in range(10000 if enough else 0):
            vals=[]
            for layout in sorted(set(r['layout'] for r in rows)):
                d=delta[[i for i,r in enumerate(rows) if r['layout']==layout]]
                vals.extend(rng.choice(d,len(d),replace=True))
            means.append(np.mean(vals))
        report['comparisons'][mode]={'saving_min':float(delta.mean()),'ci95_min':np.quantile(means,[.025,.975]).tolist() if enough else None,
              'wins':int((delta>1e-6).sum()),'losses':int((delta < -1e-6).sum()),'ties':int((abs(delta)<=1e-6).sum()),
              'worst_loss_min':float(-delta.min()),'predicted_saving_min':float(predicted.mean()),
              'prediction_correlation':float(np.corrcoef(delta,predicted)[0,1]),
              'local_oracle_saving_min':statistics.mean(r[mode+'_oracle_saving'] for r in rows),
              'mean_second_channels':statistics.mean(r[mode+'_channels'] for r in rows)}
    for layout in sorted(set(r['layout'] for r in rows)):
        subset=[r for r in rows if r['layout']==layout]
        report['by_layout'][layout]={m:statistics.mean(r[m] for r in subset) for m in ('fixed','position','joint','baseline')}
    report['means_min']={m:statistics.mean(r[m] for r in rows) for m in ('fixed','position','joint','baseline')}
    a.base.dump(out/'analysis.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='rows'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('out')
    p.add_argument('--workers',type=int,default=6)
    p.add_argument('--available',action='store_true')
    args=p.parse_args()
    out=Path(args.out)
    cases=json.loads((out/'cases.json').read_text())
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
        ready=[c for c in cases if (out/c['name']/'baseline/result.json').exists()]
        selected=ready if args.available else cases
        jobs=[pool.submit(oracle_task,(c,str(out/c['name']/'selection.json'))) for c in selected
              if not (out/c['name']/'oracle_diagnostic.json').exists()]
        for job in concurrent.futures.as_completed(jobs):
            print(job.result()['case'],flush=True)
    if len(ready)==len(cases):
        analyze(out)
    else:
        print(f'partial diagnostics only: {len(ready)}/{len(cases)}',flush=True)
