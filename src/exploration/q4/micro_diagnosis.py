"""只读诊断两局既有轨迹；不调用策略或官方环境。"""
import json
import math
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/q4'))
import common
from selected import SelectedPolicy
from belief import reception_mass

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))

def main():
    for tag, channels in [('2995', [2, 8, 10]), ('2141', [12, 9])]:
        d = load(ROOT / f'outputs/q4/replays02/q4-regression-{tag}/selected.json')
        print('\nCASE', tag)
        for j in channels:
            print('CHANNEL', j)
            for i, a in enumerate(d['actions']):
                if a['channel'] != j:
                    continue
                before, after = d['frames'][i], d['frames'][i+1]
                c, cnew = before['channels'][j-1], after['channels'][j-1]
                print(i+1, round(after['time']/60, 2), a['kind'], a['result'],
                      'radius', round(c.get('radius', -1), 2), '->', round(cnew.get('radius', -1), 2),
                      'q', tuple(round(v) for v in a['position']))

def audit():
    """公开前缀估价和固定其余动作的单次清除前移，仅作诊断。"""
    out = ROOT / (sys.argv[sys.argv.index('--output')+1] if '--output' in sys.argv else 'outputs/experiments/q4/micro_diagnosis01')
    out.mkdir(parents=True, exist_ok=False)
    records = []
    for tag, batch, name in [
        ('2995', 'holdout01', 'holdout_943004_uniform_outward_hashed'),
        ('2141', 'pressure01', 'pressure_944001_edge_tangent_hashed')]:
        folder = ROOT / 'outputs/q4' / batch / 'cases' / name / 'selected'
        manifest = load(ROOT / 'outputs/q4' / batch / 'manifest.json')
        for path, digest in manifest['code_sha256'].items():
            assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == digest, path
        rows = [json.loads(line) for line in (folder/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
        plans = load(folder/'result.json')['policy_metadata']['plans']
        priority_by_start = {p['at_action']+1:p['jobs'][0].get('channel') for p in plans}
        state, policy, estimates = common.Q4State(), SelectedPolicy(), []
        priority = None
        for row in rows:
            j, q = row['channel'], tuple(row['position'])
            if row['step'] in priority_by_start:
                priority = priority_by_start[row['step']]
            c = state.channels[j]
            if row['kind'] == 'measure' and c.status == 'found':
                radius = c.circle()[1]
                info = dict(step=row['step'], channel=j, reason=row['reason'], priority=priority,
                            before_radius=radius, measure_result=row['response']['measure_result'])
                # 只估计该前缀下实际测点的接收概率；不参与重放和动作选择。
                try:
                    pool = policy._pool(state,c)
                    info['reception_probability'] = sum(w*reception_mass(x,s,q) for x,s,w in zip(pool['points'],pool['slices'],pool['weights']))/sum(pool['weights'])
                    info['ess'] = pool['ess']
                except ValueError:
                    info['reception_probability'] = None
                estimates.append(info)
            state.update(row, row['response'])
            if estimates and estimates[-1]['step'] == row['step']:
                estimates[-1]['after_radius'] = c.circle()[1] if c.status == 'found' else 0
        assert state.complete
        d = load(ROOT / f'outputs/q4/replays02/q4-regression-{tag}/selected.json')
        record = dict(case=name, input_sha256={f:hashlib.sha256((folder/f).read_bytes()).hexdigest() for f in ['actions.jsonl','result.json']}, estimates=estimates)
        low = [e for e in estimates if e['reception_probability'] is not None and e['reception_probability']<.05]
        ledger = load(folder/'ledger.json')
        record['low_probability_diagnostic'] = dict(threshold=.05, count=len(low),
            all_auxiliary=all(e['channel']!=e['priority'] for e in low),
            no_signal=sum(e['measure_result']=='no_signal' for e in low),
            fees_s=sum(ledger[e['step']-1]['charges']['measure_s']+ledger[e['step']-1]['charges']['switch_s'] for e in low),
            no_outer_radius_change=sum(abs(e['before_radius']-e['after_radius'])<1e-6 for e in low),
            limitation='5%仅为诊断分组，不是建议冻结阈值；概率由当前公开前缀重新计算，32点有限池的0不等于物理不可能。未减小外包半径不等于未更新朝向信息。')
        if tag == '2141':
            prefix, final = 266, 345
            c = d['frames'][prefix]['channels'][11]
            target = rows[final-1]['position']
            assert c['radius'] < 20 and max(math.dist(v,target) for v in c['polygon']) < 20
            assert not any(a['channel']==12 for a in rows[prefix:final-1])
            order = rows[:prefix]+[rows[final-1]]+rows[prefix:final-1]
            cf = common.Q4State()
            for original in order:
                move = math.dist(cf.position,original['position'])/5
                operation = 5 if original['kind']=='measure' or original['response'].get('clear_result')=='success' else 3
                switch = int(original['kind']=='measure' and original['channel']!=cf.measuring_channel)
                reply = dict(original['response'],virtual_time_s=cf.virtual_time_s+move+operation+switch)
                cf.update(original,reply)
            assert cf.complete and sum(c.status=='cleared' for c in cf.channels.values())==16
            first = next(i for i,f in enumerate(d['frames']) if f['channels'][11].get('radius',999)>0 and f['channels'][11].get('radius',999)<20)
            full_plan = next(p['jobs'] for p in plans if p['at_action']==prefix)
            old_index = next(i for i,j in enumerate(full_plan) if j.get('channel')==12)
            p = d['frames'][prefix]['q']
            length = lambda jobs: sum(math.dist(a,b) for a,b in zip([p]+[j['position'] for j in jobs],[j['position'] for j in jobs]))
            remaining = full_plan[:old_index]+full_plan[old_index+1:]
            relocated = [full_plan[old_index]]+remaining
            record['single_clear_relocation'] = dict(first_certified_action=first, first_certified_min=d['frames'][first]['time']/60,
                radius_m=c['radius'], execute_after=prefix, moved_original_action=final,
                old_s=state.virtual_time_s, counterfactual_s=cf.virtual_time_s,saving_s=state.virtual_time_s-cf.virtual_time_s,
                old_final_leg_move_s=math.dist(rows[-2]['position'],target)/5,
                frozen_plan_added_s=(length(relocated)-length(full_plan))/5,
                limitation='清除前移之外保留原动作和同地点反馈；不是修改策略的闭环性能。')
            scan_positions = [j['position'] for j in full_plan if j['kind']=='scan']
            scenarios = []
            for k in range(len(scan_positions)+1):
                keep = lambda jobs: [j for j in jobs if j['kind']!='scan' or j['position'] in scan_positions[:k]]
                oldcost,newcost = length(keep(full_plan))/5,length(keep(relocated))/5
                best = min(oldcost,newcost)
                scenarios.append(dict(retained_scan_prefix=k,original_move_s=oldcost,
                    early_clear_move_s=newcost,original_regret_s=oldcost-best,early_clear_regret_s=newcost-best))
            record['prefix_sensitivity'] = dict(scenarios=scenarios,
                original_worst_regret_s=max(s['original_regret_s'] for s in scenarios),
                early_clear_worst_regret_s=max(s['early_clear_regret_s'] for s in scenarios),
                scope='固定服务点与扫描顺序的敏感性场景，不是新源反馈仿真，也不赋予各前缀发生概率；0前缀是压力假设，未宣称当前立即取消在物理上可达。')
        records.append(record)
    result = dict(records=records, script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (out/'diagnosis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    a,b = records
    relocation=b['single_clear_relocation']; sensitivity=b['prefix_sensitivity']
    report = f'''# 第四问两局退步：动作诊断与小改法

本轮只诊断原有记录、比较固定计划和一次清除前移；没有改动selected或运行新闭环策略。以下全为AI/程序核验。

## 最值得处理的决策

### 1. 已经能保证清除，却依赖将来可能取消的扫描回程

压力局C12在动作266、{relocation['first_certified_min']:.2f}分钟时相容位置外包半径已是{relocation['radius_m']:.2f}米。旧方案同频道56.82分钟取得保证清除的定位范围，57.26分钟完成清除。新方案把C12放到计划末尾；该计划预期从西侧扫描完后经内部站返回东北。动作333发现满16源后，未发现频道被合法判空，回程扫描取消，C12依然欠着。动作345单次折返移动{relocation['old_final_leg_move_s']/60:.2f}分钟。

将这一个已认证的清除动作移到动作266之后，其余动作、地点、频道反馈固定不变，公开状态重放仍全清，总时间从{relocation['old_s']/60:.2f}变为{relocation['counterfactual_s']/60:.2f}分钟，减少{relocation['saving_s']/60:.2f}分钟。这是固定其余轨迹的可行反事实，不是部署改法后的实测收益。其他目标后续反馈沿用的依据是目标静止、频道独立及本地误差场只依赖位置/频道/种子，不依赖清除动作发生顺序；未知分布的新实测不能借此保证。

同一公开状态下，原完整计划中前移C12只增加{relocation['frozen_plan_added_s']:.2f}秒路费。这解释了为什么值得容忍少量计划路程，保护取消后的折返风险。检查全部扫描前缀的固定点敏感性后，两条候选路线的最坏相对损失分别为{ sensitivity['original_worst_regret_s']:.2f}和{sensitivity['early_clear_worst_regret_s']:.2f}秒。各前缀不是已验证的真实场景分布。

**建议A：只给新获得保证清除证据的目标增加一个“立即处理”候选。**保留原完整路线，另将该目标前置；扫描顺序与覆盖站集合保持。对“扫描完整保留”和“后半段被取消”的各前缀，计算两路线的移动费用。用有限候选最小最大后悔值择优：R(a)=max_k[C(a,k)-min_b C(b,k)]。仅在排序时做这层比较，不实际提前取消任何扫描任务；多圆试清和未定位目标不强制前置。它没有全局最优保证，有限计划只近似后续新增目标，但能明确处理原评分遗漏的风险。

### 2. 条件概率只参与主测点选择，没有约束顺带补测

candidate.py的_measure_options使用接收概率；_station及_station_action主要按状态、是否测过和1500米粗距离排队。辅助频道即使在工作模型中几乎收不到信号，仍可能被塞入队列。

| 案例 | 低于5%补测 | 实际阴性 | 检测加切频费用 | 外包半径不变 |
|---|---:|---:|---:|---:|
| 29.95分钟退步局 | {a['low_probability_diagnostic']['count']} | {a['low_probability_diagnostic']['no_signal']} | {a['low_probability_diagnostic']['fees_s']:.0f}秒 | {a['low_probability_diagnostic']['no_outer_radius_change']} |
| 21.41分钟退步局 | {b['low_probability_diagnostic']['count']} | {b['low_probability_diagnostic']['no_signal']} | {b['low_probability_diagnostic']['fees_s']:.0f}秒 | {b['low_probability_diagnostic']['no_outer_radius_change']} |

以上全部是非当前主目标的补测。5%仅用于诊断分组，不是看过结果后选定的新策略阈值；有限样本0概率不等于不可能收到。半径不变也不能证明阴性完全无信息。

第一局C2的外包半径约750米，动作23、42、46、64、70、87、91、92等阴性后仍维持该尺度；旧方案在动作26已将C2定位到保证清除范围，动作27清除，新方案到动作309才清除。完整流程不同，不能将这整段延迟都归因于顺带补测。

**建议B：给非主目标的已知频道补测加入净价值门槛。**用现有条件池和位置状态估计阳性、阴性两种结果后的剩余定位清除费用，预期节省必须超过本次检测5秒加切频0或1秒，才保留该辅助频道。主目标测量、未知频道覆盖承诺及保守全清证书保持。抽样耗尽时保留原行为，不以概率0判空。概率模型已存在，主要补齐估价与执行队列的接口。

不能用“连续几次没信号就放弃”替代：压力局C9在动作334、336、338、340的四次阴性将外包半径从389.34米依次减至134.28、104.28、59.31、44.33米，随后认证多圆成功，属于有效定位。建议B保留主目标并显式计阴性价值。

## 优先级与验证门槛

优先A，它对大额折返有直接依据；B规模更小、覆盖更广，但直接操作费只有约{a['low_probability_diagnostic']['fees_s']/60:.2f}/{b['low_probability_diagnostic']['fees_s']/60:.2f}分钟，不能宣称单靠删这些补测就解决29.95分钟退步。两者应各自作为独立候选，先在这两局和事先固定的原本胜出局对照，再做新种子检验；全清后比较完整T_virtual/N、最差退步和现实计算费，不将A、B效果直接相加。

没有证据把第一局早期选择绕行方向称为错误；当时不知道所有源的位置。C10最终成功接收的测点在动作156的计划中就存在，但被多次后排，不能归因于根本未提出该候选；这不表示当时已知这个点必然成功。扩大候选池或提高采样量不是本轮首选。

## 理论与来源范围

- A是本题的有限取消场景与最小最大后悔值设计；表中界限只对列出的固定任务/前缀/两路线成立，不是官方问题整体界限。
- B借鉴付费观测的价值与费用比较。Dance与Silander的[付费观测研究](https://jmlr.org/papers/v20/17-185.html)讨论观测成本和信息不足的权衡；它的高斯随机游走阈值最优结论不能直接套到本题。
- 复现：`py -3.13 -X utf8 experiments/q4/micro_diagnosis.py --audit --output outputs/experiments/q4/新的诊断批次`。原日志、前缀估价、费用及输入指纹见同目录diagnosis.json；原策略源码指纹逐项一致。
'''
    (out/'REPORT.md').write_text(report,encoding='utf-8')
    for r in records:
        low = [e for e in r['estimates'] if e['reception_probability'] is not None and e['reception_probability']<.05]
        print(r['case'], 'low_probability',len(low), 'negative',sum(e['measure_result']=='no_signal' for e in low))
        print('relocation',r.get('single_clear_relocation'))
        print('low_steps',[(e['step'],e['channel'],round(e['reception_probability'],4),round(e['before_radius']-e['after_radius'],4)) for e in low])

if __name__ == '__main__':
    audit() if '--audit' in sys.argv else main()
