"""抽取一个新案例，实际在线选点运行，保存逐动作讲解数据。仅本地仿真。"""
import hashlib
import json
import math
import secrets
import time
from pathlib import Path
import adaptive as a
from online import OnlineAdaptivePolicy

HERE=Path(__file__).resolve().parent
OUT=HERE/'demonstration'


def snapshot(state):
    channels=[]
    for j,c in state.channels.items():
        item={'j':j,'status':c.status}
        if c.status=='found':
            center,radius=c.circle()
            item.update(center=center,radius=radius,polygon=c.support())
        channels.append(item)
    return {'q':state.position,'time':state.virtual_time_s,'channels':channels,
            'seen':sorted(state.ever_seen),'complete':state.complete,
            'absence_reasons':dict(state.absence_reasons)}


def main():
    OUT.mkdir(exist_ok=False)
    seed=secrets.randbelow(2**30)
    case=a.base.generate(seed,'uniform','hashed')
    a.base.dump(OUT/'case.json',case.to_dict())
    a.base.dump(OUT/'receipt.json',{'seed':seed,'sampling':'one unfiltered draw; uniform area, U[1000,1500] radii, hashed fixed noise',
                                 'mode':'position','samples':16,'started_unix':time.time()})
    state=a.CoverageInformationState()
    policy=OnlineAdaptivePolicy(mode='position',samples=16)
    env=a.LocalEnvironment(case)
    frames=[snapshot(state)]
    actions=[]
    previous=(0.,0.)
    channel=1
    ledger={'move_s':0.,'measure_s':0.,'switch_s':0.,'success_clear_s':0.,'fail_clear_s':0.}
    began=time.perf_counter()
    with (OUT/'actions.jsonl').open('w',encoding='utf-8',buffering=1) as stream:
        for step in range(3000):
            if state.complete:
                break
            start=time.perf_counter()
            action=policy.choose(state)
            decision_wall=time.perf_counter()-start
            before=a.base.visible_snapshot(state,action['channel'])
            target=policy.target
            before_radius=state.channels[action['channel']].circle()[1] if state.channels[action['channel']].status=='found' else None
            response=env.act(action)
            costs,channel=a.base.independent_cost(previous,channel,action,response)
            previous=tuple(action['position'])
            for k,v in costs.items():
                ledger[k]+=v
            state.update(action,response)
            a.audit_state(state,env)
            assert abs(sum(ledger.values())-env.virtual_time_s)<1e-6
            row=dict(action,step=step+1,response=response,independent_costs=costs,
                     before=before,after=a.base.visible_snapshot(state,action['channel']),
                     decision_wall_s=decision_wall,target=target,before_radius=before_radius,
                     plan=policy.decision_data)
            stream.write(json.dumps(row,ensure_ascii=False)+'\n')
            actions.append(row)
            frames.append(snapshot(state))
            if policy.selection is not None and not (OUT/'selection.json').exists():
                a.base.dump(OUT/'selection.json',policy.selection)
                print('second point selected',policy.selection['position'],flush=True)
            if step%20==0:
                print('action',step+1,'cleared',len(env.cleared),flush=True)
        else:
            raise RuntimeError('action limit')
    assert state.complete and len(env.cleared)==len(case.sources)
    result={'case':case.to_dict(),'actions':actions,'frames':frames,'ledger':ledger,
            'total_s':env.virtual_time_s,'all_clear':True,'wall_s':time.perf_counter()-began,
            'selection':policy.selection}
    a.base.dump(OUT/'replay.json',result)
    a.base.dump(OUT/'result.json',{'success':True,'total_s':env.virtual_time_s,'sources':len(case.sources),
                                'actions':len(actions),'ledger':ledger,'wall_s':result['wall_s']})
    print(json.dumps({'seed':seed,'sources':len(case.sources),'actions':len(actions),'total_min':env.virtual_time_s/60},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
