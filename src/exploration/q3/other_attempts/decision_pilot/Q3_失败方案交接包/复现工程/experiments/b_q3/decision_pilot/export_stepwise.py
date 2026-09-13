"""在本地仿真器重放原始动作，逐步核验并导出可读记录。可从交付工程独立运行。"""
import argparse
import csv
import json
import math
from pathlib import Path
import time

from model import (LocalEnvironment, InformationState, audit_state, worlds_from_history,
                   candidates, evaluate, continue_to_end)
from simulation import Scenario
from run import scan_snapshot

HERE = Path(__file__).resolve().parent
NAMES = {'scan7_r60':'原两阶段基线','sweep':'已有Sweep',
         'center_default':'新续行默认行动','rollout_selected':'新续行加预演选择'}
REASONS = {
    'fixed_scan':'按固定扫描任务检测；清除/排除频道及已足够小的区域会在任务生成时跳过',
    'guaranteed_here':'当前位置20米范围包含该源整个支持集，在原地保证清除',
    'guaranteed_center':'该源包围圆小于20米，去圆心保证清除',
    'one_small_center_try':'续行中该源区域不超过30米且中心相容，执行一次中心试清',
    'approach_center_and_measure':'区域仍大，去当前估计中心补测；中心已测时才横向偏移',
    'small_region_center_try':'原基线在20—30米区域对相容中心试清',
    'completion_shared_probe':'旧局部评价选择原地补测；仍使用旧W/G规则',
    'completion_localize':'旧局部评价选择移动补测',
    'completion_clear':'旧局部规则选择清除',
    'completion_cell_clear':'旧局部规则选择清除格试清',
}


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def dump(p, x):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def explain(a, phase):
    code=a.get('reason','')
    if code.endswith('_shared'):
        return '执行已选公共位置的多频道测量块；此步测一个频道，不重新进行全局预演'
    if code.endswith('_single'):
        return '执行阶段交界选择的单频道候选动作'
    return REASONS.get(code, '按冻结策略理由代码执行；未从日志补造未记录的评分：'+code)


def replay(case, raw, scan_count, name):
    state, env = InformationState(), LocalEnvironment(case)
    result=[]
    for i,item in enumerate(raw,1):
        a, stored=item['action'],item['response']
        c=state.channels[a['channel']]
        before_status=c.status
        before_radius=c.circle()[1] if c.status=='found' else None
        before_center=c.circle()[0] if c.status=='found' else None
        distance=math.dist(state.position,a['position'])
        switch=int(a['kind']=='measure' and state.measuring_channel!=a['channel'])
        response=env.act(a)
        assert response==stored, (case.name,name,i,'反馈/计时未复现')
        cost=distance/5 + (5+switch if a['kind']=='measure' else 5 if response['clear_result']=='success' else 3)
        assert abs(cost-(env.virtual_time_s-state.virtual_time_s))<1e-6
        state.update(a,response)
        audit_state(state,env)
        c=state.channels[a['channel']]
        phase=('发现未完' if any(x.status=='unknown' for x in state.channels.values()) else '处理已发现目标') if name=='sweep' else '扫描' if i<=scan_count else '服务'
        counts={s:sum(x.status==s for x in state.channels.values()) for s in ('unknown','found','absent','cleared')}
        result.append(dict(step=i, service_step=None if name=='sweep' or i<=scan_count else i-scan_count,
            phase=phase,kind=a['kind'],channel=a['channel'],x_m=a['position'][0],y_m=a['position'][1],
            before_status=before_status,after_status=c.status,
            before_center=before_center,before_radius_m=before_radius,
            after_center=c.circle()[0] if c.status=='found' else None,
            after_radius_m=c.circle()[1] if c.status=='found' else None,
            movement_m=distance,move_s=distance/5,switch_s=switch,
            operation_s=cost-distance/5-switch,step_s=cost,total_s=state.virtual_time_s,
            result=response.get('measure_result',response.get('clear_result')),bearing_deg=response.get('svd_deg'),
            reason=a.get('reason',''),reason_explanation=explain(a,phase),
            **counts, action=a,response=response))
    assert state.complete and len(env.cleared)==len(case.sources)
    return result


def fmt(x):
    return '—' if x is None else f'{x:.2f}'


def export(batch, output):
    output.mkdir(parents=True,exist_ok=False)
    cases=[Scenario.from_dict(x) for x in read(batch/'cases.json')]
    index=[]
    total_actions=0
    for case in cases:
        folder=batch/case.name
        selected=read(folder/'selection_before_counterfactual.json')
        scan=read(folder/'scan.json')
        dest=output/case.name
        dest.mkdir()
        for name in NAMES:
            if name in ('scan7_r60','sweep'):
                raw=read(folder/(name+'_actual.json'))['actions']
            else:
                key='default' if name=='center_default' else selected['selected_name']
                raw=scan+read(folder/(key+'_actual.json'))['actions']
            rows=replay(case,raw,len(scan),name)
            total_actions+=len(rows)
            (dest/(name+'.jsonl')).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows),encoding='utf-8')
            flat=[{k:v for k,v in r.items() if k not in ('action','response','before_center','after_center')} for r in rows]
            with (dest/(name+'.csv')).open('w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(flat[0]))
                writer.writeheader();writer.writerows(flat)
            lines=[f'# {case.name}：{NAMES[name]}完整逐步记录','',
                f'自建仿真动作回放，共{len(rows)}步，{len(case.sources)}源全清，虚拟耗时{rows[-1]["total_s"]:.6f}秒。',
                '','每行一个已执行动作，不合并连续检测。半径为被操作频道的保守包围圆，清除成功后用“—”表示终止状态，不表示半径为0。理由是原始reason代码及其规则解释；没有伪造逐步评分。CSV/JSONL提供完整精度、费用分项和全部状态计数。',
                '','| 总步/服务步 | 阶段 | 动作/频道 | 位置x,y/米 | 反馈/角度 | 半径前→后/米 | 移动/米 | 本步/秒 | 累计/秒 | 已清数 | 理由代码 |',
                '|---|---|---|---|---|---|---:|---:|---:|---:|---|']
            for r in rows:
                lines.append(f'| {r["step"]}/{r["service_step"] or "—"} | {r["phase"]} | {r["kind"]}/{r["channel"]} | {r["x_m"]:.2f},{r["y_m"]:.2f} | {r["result"]}/{fmt(r["bearing_deg"])} | {fmt(r["before_radius_m"])}→{fmt(r["after_radius_m"])} | {r["movement_m"]:.2f} | {r["step_s"]:.2f} | {r["total_s"]:.2f} | {r["cleared"]} | {r["reason"]} |')
            (dest/(name+'.md')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
            index.append(dict(case=case.name,policy=name,steps=len(rows),sources=len(case.sources),total_s=rows[-1]['total_s']))
        predictions=['# 阶段交界：候选比较及最终选择','',
            f'选中：`{selected["selected_name"]}`。只有此次比较调用新预演器，后续不是逐步滚动预演。',
            '','| 候选 | 5场景剩余耗时/秒 | 平均/秒 | 选中 |','|---|---|---:|---|']
        for p in selected['prediction']:
            predictions.append(f'| {p["name"]} | '+', '.join(fmt(x) for x in p['scenario_s'])+f' | {fmt(p["mean_s"])} | {"是" if p["name"]==selected["selected_name"] else ""} |')
        predictions+=['','实际候选块（一个位置逐频道执行）：','', '```json',json.dumps(selected['candidates'][selected['selected_index']],ensure_ascii=False,indent=2),'```','']
        (dest/'候选比较.md').write_text('\n'.join(predictions),encoding='utf-8')
    lines=['# 仿真逐步记录','',
        '本目录由export_stepwise.py在本次交付时重新逐动作调用自建LocalEnvironment生成；全部反馈与原实验日志逐项一致，并重新检查计费、位置保留和全清。属于原案例的确定性回放，不是新增独立案例，也不是官方模拟器记录。',
        '',f'共{len(cases)}案例×4种运行方式＝{len(index)}条完整记录，{total_actions}个动作。默认与预演恰好选择同一动作时仍分别提供记录，不能按文件数算不同案例。',
        '','建议先读edge_biased_161104的center_default.md与scan7_r60.md：前者服务步6—9的近共线补测，可与后者总步139的原地交会测量比较。再看rollout_selected.md，这是最终选中原型的完整轨迹，不能只用default说明其整局表现。',
        '','每个案例附四份MD（逐步阅读）、四份CSV（筛选费用和状态）、四份JSONL（原精度与原始动作反馈），另有候选比较.md。Sweep的阶段标签由每步后是否还有未知频道标注，仅为阅读辅助，不代表新增了该策略的显式阶段控制。',
        '','| 案例 | 方法 | 步数 | 整局/分 | 记录 |','|---|---|---:|---:|---|']
    for r in index:
        link=f'{r["case"]}/{r["policy"]}.md'
        lines.append(f'| {r["case"]} | {NAMES[r["policy"]]} | {r["steps"]} | {r["total_s"]/60:.2f} | [逐步记录]({link}) |')
    lines+=['','## 理由代码','']+[f'- `{k}`：{v}。' for k,v in REASONS.items()]
    lines+=['','后缀_shared代表执行选中的共享检测块；_single代表选中的单频道动作。其余冻结基线理由代码在CSV中保留原值，未记录的评分不补造。','']
    (output/'README.md').write_text('\n'.join(lines),encoding='utf-8')
    dump(output/'回放核验.json',dict(cases=len(cases),complete_traces=len(index),actions=total_actions,
        feedback_match=True,cost_and_truth_retention_passed=True,source='deterministic_local_replay',rows=index))
    return dict(traces=len(index),actions=total_actions)


def fresh_check(batch, output):
    """额外独立重跑一个选中策略，包含重新生成场景和重新评分。"""
    case=next(Scenario.from_dict(c) for c in read(batch/'cases.json') if c['name']=='edge_biased_161104')
    start=time.perf_counter()
    state,env,scan=scan_snapshot(case)
    options=candidates(state)
    worlds=worlds_from_history(state)
    ix,prediction=evaluate(state,options,worlds)
    archived=read(batch/case.name/'selection_before_counterfactual.json')
    assert options==archived['candidates'] or json.loads(json.dumps(options))==archived['candidates']
    assert ix==archived['selected_index'] and prediction==archived['prediction']
    result=continue_to_end(state,env,options[ix]['actions'])
    old=read(batch/case.name/(archived['selected_name']+'_actual.json'))
    assert json.loads(json.dumps(result['actions']))==old['actions']
    assert result['total_s']==old['total_s']
    dump(output/'独立重跑核验.json',dict(case=case.name,selected=options[ix]['name'],
        rerun_includes='重新扫描、生成场景、逐候选评分、执行选中块与后续全清',
        selection_and_all_actions_identical=True,total_s=result['total_s'],wall_s=time.perf_counter()-start,
        independent_new_case=False,created=time.strftime('%Y-%m-%d %H:%M:%S %z')))
    print('独立重跑核验通过：'+case.name,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--batch',type=Path,default=HERE/'runs/confirm_161100')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--fresh-check',action='store_true')
    args=p.parse_args()
    print(json.dumps(export(args.batch,args.output),ensure_ascii=False),flush=True)
    if args.fresh_check: fresh_check(args.batch,args.output)
