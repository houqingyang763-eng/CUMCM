"""补充新确认集中的增量对照，完整保留差值和最坏案例。"""
import argparse
import json
from pathlib import Path
import numpy as np


def compare(rows,reference,candidate,ci=True):
    delta=np.array([(r[reference]['total_s']-r[candidate]['total_s'])/60 for r in rows])
    rng=np.random.default_rng(320912)
    means=[]
    if ci and len(rows)>1:
        groups=[delta[[i for i,r in enumerate(rows) if r['layout']==layout]] for layout in sorted({r['layout'] for r in rows})]
        for _ in range(5000):
            means.append(np.mean(np.concatenate([rng.choice(g,len(g),replace=True) for g in groups])))
    return {'reference':reference,'candidate':candidate,'cases':len(rows),'saving_min':float(delta.mean()),
            'ci95_min':np.quantile(means,[.025,.975]).tolist() if means else None,
            'wins':int((delta>1e-6).sum()),'losses':int((delta<-1e-6).sum()),'ties':int((abs(delta)<=1e-6).sum()),
            'worst_loss_min':max(0.,-float(delta.min())),
            'cost_savings_min':{k:float(np.mean([(r[reference][k]-r[candidate][k])/60 for r in rows]))
                                for k in ('move_s','measure_s','switch_s','fail_clear_s')},
            'worse_cases':sorted([{'case':r['case'],'extra_min':-float(d)} for r,d in zip(rows,delta) if d < -1e-6],key=lambda x:-x['extra_min'])}


def main(folder):
    folder=Path(folder)
    a=json.loads((folder/'analysis.json').read_text());rows=a['rows']
    assert not a['failures']
    comparisons=[]
    for reference,candidate in [('f1','f2'),('f2','f3'),('f3','f4'),('f1','f4'),('baseline','f1'),('baseline','f2'),('baseline','f3'),('baseline','f4')]:
        if all(reference in r and candidate in r for r in rows):
            comparisons.append(compare(rows,reference,candidate,folder.name not in ('stress','random_audit')))
    checks=[]
    for path in folder.glob('*/f4/metadata.json'):
        meta=json.loads(path.read_text())
        for d in meta['refinement_decisions']:
            c=d.get('recheck',{})
            if c.get('performed'):
                checks.append({'case':path.parent.parent.name,'step':d['at_action']+1,
                               'proposed':c['proposed'],'accepted':c['accepted'],'mean_saving_s':c['mean_saving_s']})
    result={'comparisons':comparisons,'rechecks':checks,'accepted':sum(c['accepted'] for c in checks),'rejected':sum(not c['accepted'] for c in checks)}
    (folder/'incremental.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rechecks'},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder');args=p.parse_args();main(args.folder)
