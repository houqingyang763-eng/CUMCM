"""独立重放反馈与计费，汇总行动、尾部查漏及搜索失败。"""
import argparse
import json
import math
import statistics
from pathlib import Path
from planner import a
from state import audit_state


def inspect(case,directory):
    result = json.loads((directory/'result.json').read_text(encoding='utf-8'))
    actions = [json.loads(x) for x in (directory/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    state = a.CoverageInformationState()
    env = a.LocalEnvironment(case)
    total = 0.
    before = (0.,0.)
    channel = 1
    distances = []
    repeats = []
    last_clear_s = 0.
    first_clear_s = None
    for action in actions:
        q,j = tuple(action['position']),action['channel']
        if action['kind']=='measure' and q in state.channels[j].measured:
            repeats.append(action['step'])
        reply = env.act(action)
        for key in ('measure_result','clear_result','svd_deg'):
            if reply.get(key) != action['response'].get(key):
                raise AssertionError((action['step'],key,'feedback mismatch'))
        d = math.hypot(q[0]-before[0],q[1]-before[1])
        if d>1e-6:
            distances.append(d)
        if action['kind']=='measure':
            cost = d/5 + 5 + int(channel!=j)
            channel = j
        else:
            cost = d/5 + (5 if reply['clear_result']=='success' else 3)
        total += cost
        if abs(total-action['response']['virtual_time_s'])>1e-5:
            raise AssertionError('independent ledger mismatch')
        state.update(action,reply)
        audit_state(state,env)
        before = q
        if action['kind']=='clear' and reply['clear_result']=='success':
            last_clear_s = total
            first_clear_s = total if first_clear_s is None else first_clear_s
    if abs(total-result['total_s'])>1e-5:
        raise AssertionError('result total mismatch')
    if result['success'] != (state.complete and len(env.cleared)==len(case.sources)):
        raise AssertionError('completion mismatch')
    metadata = json.loads((directory/'metadata.json').read_text(encoding='utf-8'))
    decisions = metadata.get('decisions',[])
    errors = [x for x in decisions if 'error' in x]
    output = dict(case=case.name,success=result['success'],actions=len(actions),verified_s=total,
                  first_clear_min=first_clear_s/60 if first_clear_s else None,
                  final_post_clear_check_min=(total-last_clear_s)/60,
                  moves=len(distances),mean_move_s=statistics.mean(distances)/5 if distances else 0.,
                  repeated_measure_steps=repeats,search_decisions=len(decisions),search_errors=len(errors),
                  search_calls=sum('estimates' in x or 'error' in x for x in decisions),
                  selected_station_plans=sum('chosen_plan' in x for x in decisions),
                  queued_station_actions=sum(x.get('proof')=='continue_selected_station' for x in decisions),
                  error_types=sorted({x['error'] for x in errors}),
                  changed_from_incumbent=sum(x.get('chosen',{}).get('position')!=x.get('original',{}).get('position') or
                                            x.get('chosen',{}).get('channel')!=x.get('original',{}).get('channel') or
                                            x.get('chosen',{}).get('kind')!=x.get('original',{}).get('kind') for x in decisions if 'original' in x),
                  min_particle_ess=min((x['min_ess'] for x in decisions if 'min_ess' in x),default=None),
                  max_search_depth=max((x.get('max_depth',0) for x in decisions),default=0))
    a.base.dump(directory/'audit.json',output)
    return output


def main():
    p=argparse.ArgumentParser()
    p.add_argument('out',type=Path)
    args=p.parse_args()
    cases=[a.Scenario.from_dict(x) for x in json.loads((args.out/'cases.json').read_text(encoding='utf-8'))]
    rows=[]
    for case in cases:
        if not (args.out/case.name).exists():
            continue
        for directory in (args.out/case.name).iterdir():
            if directory.is_dir() and (directory/'result.json').exists():
                row=inspect(case,directory)
                row['mode']=directory.name
                rows.append(row)
    a.base.dump(args.out/'audit.json',dict(episodes=len(rows),actions=sum(x['actions'] for x in rows),rows=rows))
    print(json.dumps(rows,ensure_ascii=False))


if __name__=='__main__':main()
