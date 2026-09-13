"""在用户指出的原F3公开状态上核对可清除效用、候选和过滤。"""
import json
import math
from pathlib import Path
from policy import UtilityPolicy,utility,a
from revision import BreakthroughPolicy
from refined import clearing_plans

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'refinement/runs/demo_f3_20260912'
case=json.loads((SOURCE/'cases.json').read_text(encoding='utf-8'))[0]
folder=SOURCE/case['name']/'f3'
actions=[json.loads(x) for x in (folder/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
decisions=json.loads((folder/'metadata.json').read_text(encoding='utf-8'))['refinement_decisions']
state=a.CoverageInformationState();out=[]
for action in actions:
    if action['step'] in (50,73,78,83,85,99,101,135):
        c=state.channels[action['channel']]
        policy=BreakthroughPolicy(None)
        record={'original_step':action['step'],'channel':c.channel,'q':action['position'],
                'original_reason':action['reason'],'before_radius':c.circle()[1],
                'before_utility':utility(c.circle()[1]),'distance_from_origin':math.hypot(*action['position'])}
        if action['kind']=='measure':
            keep,why,pred=policy.worthwhile(state,c,action['position'])
            best,records=policy.best_view(state,c)
            record.update(keep_as_optional=keep,filter_reason=why,prediction=pred,best_new_view=best,
                          candidate_count=len(records))
        else:record['certified_plans']=clearing_plans(state,c)
        d=next((d for d in decisions if d['at_action']==state.actions),None)
        if d:record['old_decision']={k:d.get(k) for k in ('chosen','predicted_saving_s','options')}
        out.append(record)
    state.update(action,action['response'])
a.base.dump(HERE/'requested_steps.json',out)
print(json.dumps([{k:v for k,v in r.items() if k in ('original_step','channel','keep_as_optional','filter_reason','before_radius','candidate_count')} for r in out],ensure_ascii=False))
