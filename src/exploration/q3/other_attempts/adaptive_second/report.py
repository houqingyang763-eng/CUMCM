"""把固定实验日志整理成可追溯的中文报告。"""
import collections
import hashlib
import json
import statistics
from pathlib import Path
import adaptive as a

HERE=Path(__file__).resolve().parent


def main():
    out=HERE/'runs/confirm'
    analysis=json.loads((out/'analysis.json').read_text())
    rows=analysis['rows']
    halves={m:[] for m in ('position','joint')}
    same={m:0 for m in halves}
    histories=0
    seconds=[]
    for file in out.glob('*/selection.json'):
        selection=json.loads(file.read_text())
        seconds.append(selection['wall_s'])
        histories+=1
        for mode in halves:
            candidates=[c for c in selection['candidates'] if mode=='joint' or c['set']=='all']
            k=selection['samples']//2
            first=min(candidates,key=lambda c:statistics.mean(c['costs_s'][:k]))
            second=min(candidates,key=lambda c:statistics.mean(c['costs_s'][k:]))
            same[mode]+=first['id']==second['id']
            fixed=next(c for c in candidates if c['id']=='p0_all')
            halves[mode].append(statistics.mean((x-y)/60 for x,y in zip(fixed['costs_s'][k:],first['costs_s'][k:])))
    sampling={m:{'same_winner_between_halves':same[m], 'histories':histories,
                 'cross_half_expected_gain_min':statistics.mean(halves[m])} for m in halves}
    a.base.dump(out/'sampling_diagnostic.json',sampling)
    manifest=json.loads((out/'manifest.json').read_text())
    root=HERE.parents[2]
    changed=[name for name,h in manifest['hashes'].items() if hashlib.sha256((root/name).read_bytes()).hexdigest()!=h]
    assert not changed,changed
    sensitivity=[]
    for file in (HERE/'runs/pilot').glob('*/sensitivity_*.json'):
        s=json.loads(file.read_text())
        sensitivity.append({k:v for k,v in s.items() if k not in ('values','posterior')})
    a.base.dump(out/'validation_receipt.json',{'frozen_hashes_match':True,'replayed_actions':analysis['independently_replayed_actions'],
                  'sampling':sampling,'pilot_independent_sensitivity':sensitivity,
                  'selection_wall_mean_s':statistics.mean(seconds),'selection_wall_max_s':max(seconds)})
    means=analysis['means_min']
    lines=['# 自适应第二站实验报告','',
           '**结论：保留“仅自适应第二点”作为小幅改进的研究候选；不推荐增加当前这套频道集合选择，不晋升正式策略。** 24个新案例仅选点平均省1.65分钟，联合频道仅额外省2.31秒，尾部有9.22分钟退步。相比scan7_r60，选点版仍只省7.10分钟，尚未达到此前至少10分钟改善的目标。', '',
           '本轮已实现基于首轮反馈的场景抽样与完整全清rollout。不是手写反馈分支，也不是完整POMDP求解器。仅改变首轮之后的一次动作，其后仍使用原R3。', '',
           '## 独立24例结果','',
           '| 策略 | 平均整局/分钟 | 相对固定第二站节省/分钟 |','|---|---:|---:|']
    for mode,label in [('baseline','scan7_r60基线'),('fixed','固定第二站R3'),('position','自适应第二点'),('joint','自适应第二点与频道')]:
        lines.append(f'| {label} | {means[mode]:.2f} | {means["fixed"]-means[mode]:.2f} |')
    lines+=['','四种策略全部24/24实际全清，费用包含失败清除、补测和查漏。以下区间为固定四种布局权重下，逐布局配对bootstrap 10000次；不是官方分布保证。','',
            '| 策略 | 95%经验区间/分钟 | 改善/退步/相同 | 最坏退步/分钟 |', '|---|---:|---:|---:|']
    for mode in ('position','joint'):
        c=analysis['comparisons'][mode]
        lo,hi=c['ci95_min']
        lines.append(f'| {mode} | [{lo:.2f}, {hi:.2f}] | {c["wins"]}/{c["losses"]}/{c["ties"]} | {c["worst_loss_min"]:.2f} |')
    lines+=['','频道选择相对仅选点的增量为0.0385分钟（2.31秒），单独配对分层bootstrap 95%经验区间[-0.89,1.08]分钟。没有可靠证据表明频道集合选择增加收益。详见incremental.json。',
            '', '## 具体失败：省掉第二轮反而增加后续路程', '',
            '`edge_biased_280109`：第一轮20频道全部无信号。原第二轮会移动到(519.62,300)扫描；新算法选择不再扫描、直接进入后续覆盖策略。模型预计剩余时间省1.09分钟，实际整局却从76.39变成85.62分钟，多9.22分钟，其中移动多8.92分钟，检测切频多0.30分钟。', '',
            '这一例有14个真实边缘源，均匀位置先验在全阴性反馈下却把源数后验均值推到10.98。先验不匹配是明确存在的；究竟多少损失来自源数、空间分布、噪声与R3路线敏感性，当前实验没有分别隔离，不能武断归因于其中一项。', '',
            '因此本轮不继续增加决策功能。先验失配、有限抽样误选、后续R3敏感性都已暴露，但尚未得到经独立验证的可靠修正。仅增加样本不能自动解决先验失配和后续策略局限。']
    lines+=['','## 不同布局','', '| 布局 | 固定 | 选点 | 选点与频道 |', '|---|---:|---:|---:|']
    for layout,r in analysis['by_layout'].items():
        lines.append(f'| {layout} | {r["fixed"]:.2f} | {r["position"]:.2f} | {r["joint"]:.2f} |')
    lines+=['','## 决策是否选对','',
            '仅作诊断：冻结决策以后，评估者用实际自建场景逐一执行所有候选，计算这个有限集合中的事后最佳结果。该结果利用真值挑选，不是可执行策略、全局最优或可实现收益承诺。','',
            '| 策略 | 选择时预测节省 | 实际平均节省 | 候选内事后最佳节省 |','|---|---:|---:|---:|']
    for mode,c in analysis['comparisons'].items():
        lines.append(f'| {mode} | {c["predicted_saving_min"]:.2f} | {c["saving_min"]:.2f} | {c["local_oracle_saving_min"]:.2f} |')
    lines+=['','## 抽样稳定性与先验','',
            '将16个选择场景拆成前后各8个，比较两个子样本分别选择的动作；再用后8个评估前8个选出的动作。该分析只诊断小样本噪声，不修改策略。','']
    for mode,s in sampling.items():
        lines.append(f'- {mode}：两半选中相同动作 {s["same_winner_between_halves"]}/24；独立半样本评价的平均预测节省 {s["cross_half_expected_gain_min"]:.2f} 分钟。')
    lines+=['','另外，四个pilot案例的已冻结选择分别在64个新后验场景下复核，比较均匀半径与固定1000米半径。它们不是额外的真实案例，不增加24例样本量。详见各pilot目录sensitivity_*.json。','',
            '| pilot案例 | 半径假设 | 独立预测选点收益 | 独立预测联合收益 |','|---|---|---:|---:|']
    for s in sensitivity:
        d=s['independent_predicted_saving_min']
        lines.append(f'| {s["case"]} | {s["prior"]} | {d["position"]:.2f} | {d["joint"]:.2f} |')
    lines+=['','## 开销、验证与限制','',
            f'- 选择计算平均 {statistics.mean(seconds):.1f} 秒、最大 {max(seconds):.1f} 秒（6进程并行评估不同案例的机器负载条件）。单独列为计算墙钟，不计入题面虚拟时间；不代表已具备实时部署能力。',
            f'- 独立按坐标和题面规则复算 {analysis["independently_replayed_actions"]} 条真实执行动作，反馈类型、角误差界、清除结果、移动/检测/切频费用及最终全清一致。',
            '- 12项新增测试通过：后验相容性、源数后验独立组合推导、同点固定误差、状态不被模拟改变、固定版动作轨迹完全一致、真场景rollout与实际执行一致、随机性仅依赖公开观测、16源/near/空扫描边界、流式适配接口轨迹一致等。流式接口测试替换优化器为已保存的同一反馈决策，不重复计为新增性能案例。',
            '- 确认批次开始时列入manifest的全部文件散列保持一致；后加诊断脚本不参与选择。',
            '- 先验为独立均匀位置及均匀源数，无法表达真实聚集、边缘分布；连续角度似然近似了0.01度舍入；未来误差采用哈希场。候选最多六点、频道仅三类集合，未搜索任意频道子集。',
            '- 4个pilot用于跑通，随后固定算法；24个新种子用于确认，没有按确认结果修订控制器。每个候选使用16个共同场景，独立场景数偏少，不能以样本内最小值保证真实提速。',
            '- 未使用官方模拟器，未修改正式提交或原R3。', '',
            '## 复现与证据','',
            '模型、公式、理论依据见[MODEL.md](MODEL.md)。运行器[run.py](run.py)，策略[adaptive.py](adaptive.py)，独立诊断[diagnose.py](diagnose.py)。', '',
            '确认命令：`py -3.13 experiments/b_q3/adaptive_second/run.py --stage confirm --samples 16 --workers 6 --out <新的输出目录>`。',
            '诊断命令：`py -3.13 experiments/b_q3/adaptive_second/diagnose.py <上述输出目录>`。',
            '详细汇总在[runs/confirm/analysis.json](runs/confirm/analysis.json)，每局selection.json保存全部候选的逐场景成本，四个策略目录保存完整动作日志。', '']
    (HERE/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'means':means,'sampling':sampling,'wall_mean_s':statistics.mean(seconds)},ensure_ascii=False))


if __name__=='__main__':
    main()
