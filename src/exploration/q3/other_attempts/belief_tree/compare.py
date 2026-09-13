"""按同一实际案例合并不同版本；缺失、失败与完整成绩分别呈现。"""
import argparse
import json
import random
import statistics
from pathlib import Path

from planner import a


def paired_ci(values):
    rng=random.Random(330927)
    means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(5000))
    return [means[125],means[4874]]


def main():
    p=argparse.ArgumentParser()
    p.add_argument('runs',type=Path,nargs='+')
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    rows={}
    for run in args.runs:
        for case in json.loads((run/'cases.json').read_text(encoding='utf-8')):
            name=case['name']
            if name not in rows:
                rows[name]=dict(case=case,versions={})
            if rows[name]['case']!=case:
                raise AssertionError('case content differs across versions')
            for path in (run/name).glob('*/result.json'):
                mode=path.parent.name
                result=json.loads(path.read_text(encoding='utf-8'))
                if mode in rows[name]['versions']:
                    prior=rows[name]['versions'][mode]
                    if prior['result']['success']!=result['success'] or abs(prior['result']['total_s']-result['total_s'])>1e-5:
                        raise AssertionError('conflicting duplicate results')
                rows[name]['versions'][mode]=dict(path=path.as_posix(),result=result)
    modes=sorted({m for r in rows.values() for m in r['versions']})
    comparisons=[]
    for mode in modes:
        for ref in ('f3','baseline','u1','t3'):
            if ref==mode:
                continue
            pairs=[(name,r['versions'][ref]['result'],r['versions'][mode]['result'])
                   for name,r in rows.items() if ref in r['versions'] and mode in r['versions']]
            if not pairs:
                continue
            item=dict(mode=mode,reference=ref,finished_pairs=len(pairs),
                      failures=[name for name,left,right in pairs if not left['success'] or not right['success']])
            if not item['failures']:
                ds=[(left['total_s']-right['total_s'])/60 for _,left,right in pairs]
                item.update(mean_min=statistics.mean(r['total_s']/60 for _,_,r in pairs),
                            reference_mean_min=statistics.mean(l['total_s']/60 for _,l,_ in pairs),
                            saving_min=statistics.mean(ds),wins=sum(x>1e-6 for x in ds),
                            losses=sum(x<-1e-6 for x in ds),worst_loss_min=max(0.,-min(ds)),
                            cases=[name for name,_,_ in pairs],
                            cost_savings_min={k:statistics.mean((l[k]-r[k])/60 for _,l,r in pairs)
                                              for k in ('move_s','measure_s','switch_s','success_clear_s','fail_clear_s')})
                if len(ds)>=4:
                    item['paired_bootstrap95_min']=paired_ci(ds)
            comparisons.append(item)
    a.base.dump(args.out,dict(rows=list(rows.values()),comparisons=comparisons,
                             note='只有完整配对计算均值；开发例区间只作描述，不是独立确认'))
    print(json.dumps(comparisons,ensure_ascii=False))


if __name__=='__main__':main()
