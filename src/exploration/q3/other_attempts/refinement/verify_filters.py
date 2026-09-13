"""独立核对F1过滤记录的逻辑条件及是否保留了原移动轨迹。"""
import argparse
import json
import math
from pathlib import Path
from posterior import a


def main(out):
    out=Path(out);results=[]
    for meta_path in sorted(out.glob('*/f1/metadata.json')):
        directory=meta_path.parent
        if not (directory/'result.json').exists() or not (directory.parent/'current/result.json').exists():continue
        actions=[json.loads(s) for s in (directory/'actions.jsonl').read_text().splitlines()]
        original=[json.loads(s) for s in (directory.parent/'current/actions.jsonl').read_text().splitlines()]
        records=json.loads(meta_path.read_text())['skipped']
        by_prefix={}
        for r in records:by_prefix.setdefault(r['at_action'],[]).append(r)
        state=a.CoverageInformationState();checked=0
        for action in actions:
            for record in by_prefix.get(state.actions,[]):
                c=state.channels[record['channel']];p=tuple(record['prior_position']);q=tuple(record['position'])
                assert any(tuple(old)==p and result=='no_signal' for old,result,_ in c.observations)
                # 不调用策略过滤函数；用展开后的仿射表达式核对全部顶点。
                for x in c.support():
                    affine=sum(q[k]*q[k]-p[k]*p[k]-2*x[k]*(q[k]-p[k]) for k in (0,1))
                    assert affine>=1e-4-1e-7
                checked+=1
            state.update(action,action['response'])
        assert checked==len(records)
        def moves(trace):
            points=[(0.,0.)]
            for r in trace:
                q=tuple(r['position'])
                if math.dist(points[-1],q)>1e-8:points.append(q)
            return points
        x,y=moves(original),moves(actions)
        same=len(x)==len(y) and all(math.dist(p,q)<1e-5 for p,q in zip(x,y))
        results.append({'case':directory.parent.name,'proofs_checked':checked,'same_movement_route':same})
    result={'cases':len(results),'proofs_checked':sum(r['proofs_checked'] for r in results),
            'same_route_cases':sum(r['same_movement_route'] for r in results),'rows':results}
    a.base.dump(out/'filter_verification.json',result);print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');args=p.parse_args();main(args.out)
