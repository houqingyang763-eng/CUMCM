"""官方反馈驱动的本地算法重放＋独立计费；不是隐藏环境复刻。"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from two_stage import CONFIGS, TwoStagePolicy, ROOT
from state import InformationState


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    p=argparse.ArgumentParser();p.add_argument('--official',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=False)
    rows=[json.loads(s) for s in (args.official/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    manifest=read(args.official/'manifest.json')
    for rel,h in manifest['source_sha256'].items():
        assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==h
    policy=TwoStagePolicy(CONFIGS['scan7_r60']);state=InformationState()
    previous=(0.,0.);channel=1;total=0.;previous_official=0.;comparison=[];mismatch=[]
    for row in rows:
        old=row['action'];response=row['response'];new=policy.choose(state)
        diff=math.dist(old['position'],new['position'])
        equal=old['kind']==new['kind'] and old['channel']==new['channel'] and diff<=1e-8
        if not equal:mismatch.append(row['step'])
        # 计费仅由动作长度、频道状态、官方成功/失败回执推导；不读取官方cost字段。
        move=math.dist(previous,old['position'])/5
        switch=int(old['kind']=='measure' and channel!=old['channel'])
        operation=5 if old['kind']=='measure' or response.get('clear_result')=='success' else 3
        total+=move+switch+operation
        actual=response['virtual_time_s']
        comparison.append(dict(step=row['step'],kind=old['kind'],channel=old['channel'],
            x=old['position'][0],y=old['position'][1],phase=old['phase'],reason=old['reason'],
            response=response.get('measure_result',response.get('clear_result')),
            bearing_deg=response.get('svd_deg'),official_time_s=actual,local_ledger_s=total,
            cumulative_difference_s=actual-total,step_difference_s=actual-previous_official-move-switch-operation,
            replay_action_equal=equal,position_difference_m=diff))
        previous=tuple(old['position']);previous_official=actual
        if old['kind']=='measure':channel=old['channel']
        if not equal:break
        state.update(new,response)
    result=dict(comparison_type='official_feedback_replay_and_independent_cost',actions=len(rows),
        replayed_actions=len(comparison),action_mismatch_steps=mismatch,
        max_position_difference_m=max(r['position_difference_m'] for r in comparison),
        max_step_cost_difference_s=max(abs(r['step_difference_s']) for r in comparison),
        max_cumulative_cost_difference_s=max(abs(r['cumulative_difference_s']) for r in comparison),
        official_total_s=rows[-1]['response']['virtual_time_s'],local_ledger_total_s=total,
        replay_complete=state.complete,replay_cleared=sum(c.status=='cleared' for c in state.channels.values()),
        same_hidden_environment_test_performed=False,
        unavailable=['各源真实坐标','各源接收半径','官方固定空间误差场/种子'],
        limits='本地重放使用官方测向和清除反馈，不能独立验证Python环境是否产生相同反馈；源真值未公开，不能完整重建同一官方场景。')
    (out/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    with (out/'actions_comparison.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=list(comparison[0]));writer.writeheader();writer.writerows(comparison)
    (out/'local_plans.json').write_text(json.dumps(policy.metadata(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    if mismatch or not state.complete or result['max_cumulative_cost_difference_s']>1e-3:raise SystemExit(1)


if __name__=='__main__':main()
