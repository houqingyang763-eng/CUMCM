"""从冻结日志独立复算费用与全清；生成公平比较、机会与后悔统计。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def audit_trace(rows, case):
    previous, channel, elapsed = (0., 0.), 1, 0.
    cleared = set()
    sources = {s['channel']:s for s in case['sources']}
    costs = dict(move_s=0., measure_s=0., switch_s=0., success_clear_s=0., fail_clear_s=0.)
    for row in rows:
        a, r = row['action'], row['response']
        q, j = a['position'], a['channel']
        assert math.hypot(*q) <= 5000+1e-6
        move = math.dist(previous,q)/5
        costs['move_s'] += move
        s = sources.get(j) if j not in cleared else None
        distance = math.dist(q,s['position']) if s else math.inf
        if a['kind']=='measure':
            switch = int(j!=channel)
            costs['switch_s'] += switch
            costs['measure_s'] += 5
            elapsed += move+switch+5
            channel=j
            result=r['measure_result']
            if s is None or distance > s['radius']:
                assert result=='no_signal'
            elif distance <= 5:
                assert result=='near'
            else:
                assert result=='direction'
                bearing=math.degrees(math.atan2(s['position'][1]-q[1],s['position'][0]-q[0]))
                assert abs((r['svd_deg']-bearing+180)%360-180) <= 1.0050001
        else:
            success=distance<=20
            assert (r['clear_result']=='success')==success
            operation=5 if success else 3
            costs['success_clear_s' if success else 'fail_clear_s'] += operation
            elapsed += move+operation
            if success:
                cleared.add(j)
        assert abs(elapsed-r['virtual_time_s']) < 1e-5
        previous=q
    assert cleared == set(sources)
    assert abs(elapsed-sum(costs.values())) < 1e-5
    return costs


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('batch')
    args=parser.parse_args()
    out=HERE/'runs'/args.batch
    manifest, cases=read(out/'manifest.json'),read(out/'cases.json')
    assert not read(out/'failures.json')
    assert sha(out/'cases.json') == manifest['cases_sha256']
    for p,digest in manifest['sources_sha256'].items():
        assert sha(out/'source'/p)==digest
        assert sha(ROOT/p)==digest
    result_rows=read(out/'results.json')
    assert len(result_rows)==4*len(cases)
    summaries=read(out/'summary.json')
    diagnostics=read(out/'diagnostics.json')
    costs_by_policy={name:[] for name in ('scan7_r60','sweep','center_default','rollout_selected')}
    trace_count=action_count=imagined_count=0
    for case,d in zip(cases,diagnostics):
        folder=out/case['name']
        frozen=read(folder/'selection_before_counterfactual.json')
        assert sha(folder/'selection_before_counterfactual.json')==d['selection_sha256']
        index=min((p['mean_s'],i) for i,p in enumerate(frozen['prediction']) if p['mean_s'] is not None)[1]
        assert index==frozen['selected_index']==d['selected_index']
        scan=read(folder/'scan.json')
        actual={}
        for item,pred in zip(frozen['candidates'],frozen['prediction']):
            r=read(folder/(item['name']+'_actual.json'))
            costs=audit_trace(scan+r['actions'],case)
            trace_count+=1
            action_count+=len(scan)+len(r['actions'])
            actual[item['name']]=r['total_s']
            imagined_count+=len(pred['scenario_s'])
            if item['name']=='default': costs_by_policy['center_default'].append(costs)
            if item['name']==frozen['selected_name']: costs_by_policy['rollout_selected'].append(costs)
        for name in ('scan7_r60','sweep'):
            r=read(folder/(name+'_actual.json'))
            costs=audit_trace(r['actions'],case)
            trace_count+=1
            action_count+=len(r['actions'])
            costs_by_policy[name].append(costs)
            actual[name]=r['total_s']
        for name,key in [('center_default','default'),('rollout_selected',frozen['selected_name']),
                         ('scan7_r60','scan7_r60'),('sweep','sweep')]:
            r=next(r for r in result_rows if r['case']==case['name'] and r['policy']==name)
            assert abs(actual[key]-r['total_s'])<1e-7
            assert abs(actual[key]/len(case['sources'])-r['per_source_s'])<1e-7
    labels=dict(scan7_r60='原两阶段基线',sweep='已有Sweep',center_default='新续行：默认行动',rollout_selected='新续行：预演选择')
    lines=['# 一次阶段交界决策验证结果','',
        f'批次：{args.batch}。{len(cases)}个新自建Q3案例；四种完整运行方式均全清。不是官方成绩。', '',
        '## 同案例整局结果','',
        '| 方法 | 整局均值/分钟 | 每局T/N再平均/秒 | 最慢四分之一每源/秒 |',
        '|---|---:|---:|---:|']
    for key,label in labels.items():
        s=summaries[key]
        rs=[r for r in result_rows if r['policy']==key]
        assert abs(s['mean_per_source_s']-statistics.mean(r['total_s']/r['sources'] for r in rs))<1e-7
        lines.append(f'| {label} | {s["mean_total_min"]:.2f} | {s["mean_per_source_s"]:.2f} | {s["worst_quarter_per_source_s"]:.2f} |')
    lines+=['','## 完整轨迹的费用分解','','下表全部包含第一阶段，共用前缀没有漏算。', '',
        '| 方法 | 移动/秒 | 检测/秒 | 切换/秒 | 成功清除/秒 | 失败清除/秒 |',
        '|---|---:|---:|---:|---:|---:|']
    for key,label in labels.items():
        cs=costs_by_policy[key]
        lines.append('| '+label+' | '+' | '.join(f'{statistics.mean(c[k] for c in cs):.2f}' for k in cs[0])+' |')
    d=summaries['diagnosis']
    lines+=['','## 单独判断评价器','','比较的是相同新续行方法的默认行动与预演所选行动，初始信息完全一致。', '',
        f'- 胜/平/负：{d["wins"]}/{d["ties"]}/{d["losses"]}；平均每局节省{d["mean_gain_s"]:.2f}秒。',
        f'- 候选内事后最好相比默认的平均可改善空间：{d["mean_opportunity_s"]:.2f}秒。',
        f'- 所选行动距候选内事后最好的平均差距：{d["mean_regret_s"]:.2f}秒。',
        f'- 平均一次场景生成与预演评分现实耗时：{d["mean_planning_wall_s"]:.2f}秒，另于虚拟耗时报告。',
        '- 全部候选均在选中结果落盘后才进行真实反事实执行；这些反事实真值未送回选点策略。', '',
        '| 案例 | 选中块 | 实际节省/秒 | 候选最大可省/秒 | 距候选最好/秒 |',
        '|---|---|---:|---:|---:|']
    for d in diagnostics:
        lines.append(f'| {d["case"]} | {d["selected"]} | {d["actual_gain_s"]:.2f} | {d["opportunity_s"]:.2f} | {d["regret_s"]:.2f} |')
    lines+=['','## 验证及边界','',
        f'- 独立重算{trace_count}条完整实际轨迹、{action_count}个动作（包含各反事实分支重复的共享扫描前缀），费用、信号可接收性、方向误差界、20米清除规则与全清均通过。',
        f'- 候选评分共执行{imagined_count}条假想续行；运行器逐步检查位置保留和费用。本报告独立重算的是实际反事实轨迹。',
        '- 输入、实验源码快照及当前源码SHA一致；各例选中行动等于冻结评分最小者；选择记录SHA未变。',
        '- 原始results.json的measures/failed_clears/wall_s列有阶段范围区别：前两种为整局，后两种为阶段二；rollout的wall_s另含评分时间。因此不能直接横比这些原始列。本报告费用表已统一到整局，现实时间只比较单列评分耗时。',
        '- 只验证阶段交界一次选择，不代表已经实现全程滚动控制。续行策略有意保持明确简单，其强弱需与评价器分开判断。',
        '- 5个场景等权平均是团队假设，不是官方分布或已识别后验；12例不能证明总体低失败概率、尾部稳健或统计显著性。',
        '- 全清只代表所运行案例成功；动作上限或相容采样耗尽会明确失败，尚无新的全局有限步保证。',
        '- 候选中的试清与续行中的每源一次中心试清是两个操作入口，不能据此宣称整个策略每源最多一次失败清除。',
        '- 尚待团队人工审阅；候选未晋升src，也未替换任何原算法。','']
    (out/'RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
    validation=dict(actual_trajectories=trace_count,actual_actions_including_shared_prefix=action_count,
                    imagined_rollouts=imagined_count,cases=len(cases),all_checks_passed=True)
    (out/'VALIDATION.json').write_text(json.dumps(validation,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(validation))


if __name__=='__main__': main()
