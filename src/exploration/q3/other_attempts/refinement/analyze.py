"""实际轨迹独立复算、配对区间、负面案例及机制计数。"""
import argparse
import collections
import csv
import json
import math
import statistics
from pathlib import Path

import numpy as np
from posterior import a
from diagnose import replay


def analyze(out):
    out=Path(out)
    summary=json.loads((out/'summary.json').read_text())
    modes=summary['modes']
    cases=[a.Scenario.from_dict(c) for c in json.loads((out/'cases.json').read_text())]
    rows=[]
    failures=[]
    count=0
    for case in cases:
        row={'case':case.name,'layout':case.layout,'noise':case.noise}
        for mode in modes:
            directory=out/case.name/mode
            if not (directory/'result.json').exists():
                failures.append({'case':case.name,'mode':mode,'error':'missing_result'})
                continue
            r=json.loads((directory/'result.json').read_text())
            row[mode]=r
            if not r['success']:
                failures.append({'case':case.name,'mode':mode,'error':r['failreason']})
                continue
            count+=replay(directory,case)
        rows.append(row)
    result={'independently_replayed_actions':count,'failures':failures,'comparisons':{},'mechanisms':{},'by_layout':{},'rows':rows}
    rng=np.random.default_rng(319912)
    for mode in modes:
        if mode=='current':continue
        if any(mode not in r or not r[mode]['success'] or not r['current']['success'] for r in rows):
            result['comparisons'][mode]={'all_clear':False,'mean_not_reported':True}
            continue
        delta=np.array([(r['current']['total_s']-r[mode]['total_s'])/60 for r in rows])
        means=[]
        if len(rows)>1:
            groups=[delta[[i for i,r in enumerate(rows) if r['layout']==layout]] for layout in sorted({r['layout'] for r in rows})]
            for _ in range(5000):
                means.append(float(np.mean(np.concatenate([rng.choice(g,len(g),replace=True) for g in groups]))))
        costs={key:statistics.mean((r['current'][key]-r[mode][key])/60 for r in rows)
               for key in ('move_s','measure_s','switch_s','success_clear_s','fail_clear_s')}
        worse=sorted([{'case':r['case'],'extra_min':-float(d)} for r,d in zip(rows,delta) if d < -1e-6],key=lambda x:-x['extra_min'])
        result['comparisons'][mode]={'all_clear':True,'mean_min':statistics.mean(r[mode]['total_s']/60 for r in rows),
                'saving_min':float(delta.mean()),'ci95_min':np.quantile(means,[.025,.975]).tolist() if means else None,
                'wins':int((delta>1e-6).sum()),'losses':int((delta<-1e-6).sum()),'ties':int((abs(delta)<=1e-6).sum()),
                'cost_savings_min':costs,'worse_cases':worse,
                'mean_measure_count':statistics.mean(r[mode]['measure_count'] for r in rows),
                'mean_fail_clears':statistics.mean(r[mode]['fail_clears'] for r in rows),
                'worst_min':max(r[mode]['total_s']/60 for r in rows)}
        by_layout={}
        for layout in sorted({r['layout'] for r in rows}):
            values=[d for r,d in zip(rows,delta) if r['layout']==layout]
            by_layout[layout]=statistics.mean(values)
        result['by_layout'][mode]=by_layout
        chosen=collections.Counter();fallback=collections.Counter();skipped=0;kept=0;decisions=0
        for case in cases:
            path=out/case.name/mode/'metadata.json'
            if not path.exists():continue
            meta=json.loads(path.read_text())
            skipped+=len(meta.get('skipped',[]));kept+=len(meta.get('kept_to_progress',[]))
            for d in meta.get('refinement_decisions',[]):
                decisions+=1;chosen[d['chosen']]+=1
                if 'fallback' in d:fallback[d['fallback']]+=1
        result['mechanisms'][mode]={'decisions':decisions,'chosen':dict(chosen),'fallbacks':dict(fallback),'skipped':skipped,'kept_to_progress':kept}
    a.base.dump(out/'analysis.json',result)
    with (out/'paired.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f);writer.writerow(['case','layout','noise']+[m+'_min' for m in modes])
        for row in rows:
            writer.writerow([row[k] for k in ('case','layout','noise')]+[row[m]['total_s']/60 if m in row and row[m]['success'] else 'FAILED' for m in modes])
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');args=p.parse_args();analyze(args.out)
