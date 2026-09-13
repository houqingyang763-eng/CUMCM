"""开发诊断：固定已执行前缀，比较此后完整F1续行；不供在线策略调用。"""
import argparse
import copy
import json
import statistics
from pathlib import Path

from planner import a, candidates, fallback_policy, policy_after, action_key
from particle_belief import draw


def replay(directory, count=None):
    state = a.CoverageInformationState()
    policy = fallback_policy(state)
    actions = [json.loads(x) for x in (directory/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    for action in actions[:count]:
        original_policy = copy.deepcopy(policy)
        original = original_policy.choose(state)
        policy = policy_after(state,policy,original_policy,action,original)
        state.update(action,action['response'])
    return state,policy,actions[:count]


def complete(state,policy,env):
    for _ in range(3000):
        if state.complete:
            return env.virtual_time_s
        action = policy.choose(state)
        state.update(action,env.act(action))
    raise RuntimeError('diagnostic tail failed')


def prefix(directory,raw):
    state,policy,actions = replay(directory)
    env = a.LocalEnvironment(a.Scenario.from_dict(raw))
    for action in actions:
        reply = env.act(action)
        assert reply == action['response']
    before = state.virtual_time_s
    total = complete(state,policy,env)
    return dict(case=raw['name'],mode=directory.name,prefix_actions=len(actions),
                prefix_min=before/60,if_F1_finishes_min=total/60,
                note='反事实诊断：前缀冻结后用公开状态F1完整续行；不是正在运行版本的最终成绩')


def rescore(directory,out,count,world_count):
    state,policy,actions = replay(directory,count)
    options,original_policy = candidates(state,policy)
    worlds = draw(state,world_count,salt=719237,pool_size=512)
    # 只诊断原树实际展开的候选，统一世界作配对，深度固定一层。
    decisions = [json.loads(x) for x in (directory/'decisions.jsonl').read_text(encoding='utf-8').splitlines()]
    decision = next(d for d in decisions if d['at_action']==len(actions))
    rows=[]
    for item in decision['estimates']:
        action=item['action']
        values=[]
        for world in worlds:
            s=copy.deepcopy(state)
            p=policy_after(s,policy,original_policy,action,options[0])
            env=a.ConditionalEnvironment(world,s)
            s.update(action,env.act(action))
            values.append(complete(s,p,env)-state.virtual_time_s)
        rows.append(dict(action=action,original_tree_s=item['mean_s'],visits=item['visits'],
                         common_world_mean_s=statistics.mean(values),
                         world_sd_s=statistics.stdev(values),values_s=values))
        a.base.dump(out,dict(at_action=len(actions),worlds=world_count,rows=rows,
                             note='新配对世界的一层F1尾部重估；不能冒充三层反馈价值真值'))
        print(json.dumps({k:v for k,v in rows[-1].items() if k!='values_s'},ensure_ascii=False),flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('directory',type=Path)
    p.add_argument('--rescore',type=Path)
    p.add_argument('--count',type=int,default=0)
    p.add_argument('--worlds',type=int,default=32)
    args=p.parse_args()
    if args.rescore:
        rescore(args.directory,args.rescore,args.count,args.worlds)
    else:
        cases=json.loads((args.directory/'cases.json').read_text(encoding='utf-8'))
        rows=[]
        for raw in cases:
            for mode in ('u1','t3'):
                directory=args.directory/raw['name']/mode
                if (directory/'actions.jsonl').exists() and not (directory/'result.json').exists():
                    rows.append(prefix(directory,raw))
        print(json.dumps(rows,ensure_ascii=False))
        a.base.dump(args.directory/'prefix_diagnosis.json',rows)


if __name__=='__main__':main()
