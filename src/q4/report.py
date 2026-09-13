"""从冻结正式批次生成中文结果报告、关键指标与逐局表，不手填实验数字。"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics

PROJECT=Path(__file__).resolve().parents[2]
LABELS={'baseline':'简单基线 B0','joint25':'已有 joint25','selected':'第四问新模型'}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def stats(rows):
    good=[r for r in rows if r['success']]
    return dict(cases=len(rows),all_clear=len(good),cleared=sum(r['cleared'] for r in rows),
        sources=sum(r['source_count'] for r in rows),
        mean_per_source_s=statistics.mean(r['average_localization_clear_s'] for r in good) if good else None,
        mean_total_s=statistics.mean(r['virtual_time_s'] for r in good) if good else None,
        max_total_s=max(r['virtual_time_s'] for r in rows),
        max_per_source_s=max((r['average_localization_clear_s'] for r in good),default=None),
        failed_clears=sum(r['failed_clears'] for r in rows),
        max_wall_s=max(r['wall_time_s'] for r in rows),
        mean_wall_s=statistics.mean(r['wall_time_s'] for r in rows))


def comparison(rows, reference):
    a={r['case']:r for r in rows if r['policy']==reference}
    b={r['case']:r for r in rows if r['policy']=='selected'}
    if set(a)!=set(b): raise ValueError('比较策略案例不完全相同')
    pairs=[]
    for case in sorted(a):
        if a[case]['source_count']!=b[case]['source_count']: raise ValueError('配对源数不一致')
        if a[case]['success'] and b[case]['success']:
            pairs.append(dict(case=case,saved_s=a[case]['virtual_time_s']-b[case]['virtual_time_s'],
                saved_per_source_s=a[case]['average_localization_clear_s']-b[case]['average_localization_clear_s']))
    return dict(reference=reference,matched=len(a),both_all_clear=len(pairs),
        wins=sum(p['saved_s']>1e-6 for p in pairs),ties=sum(abs(p['saved_s'])<=1e-6 for p in pairs),
        mean_saved_s=statistics.mean(p['saved_s'] for p in pairs) if pairs else None,
        regressions=sorted((p for p in pairs if p['saved_s']<-1e-6),key=lambda p:p['saved_s']),pairs=pairs)


def build(holdout, pressure, practice, output):
    if output.exists(): raise ValueError('保留已有报告；选择新输出目录')
    output.mkdir(parents=True)
    groups=[]
    for label,path in [('独立确认集',holdout),('压力集',pressure)]:
        rows=read(path/'results.json')
        if set(r['policy'] for r in rows)!={'baseline','joint25','selected'}:
            raise ValueError('正式报告必须含baseline、joint25、selected三种同案例策略')
        summaries={p:stats([r for r in rows if r['policy']==p]) for p in LABELS}
        groups.append(dict(label=label,path=path,rows=rows,stats=summaries,
            comparisons=[comparison(rows,p) for p in ('baseline','joint25')]))
    overall=[r for group in groups for r in group['rows']]
    counts=stats([r for r in overall if r['policy']=='selected'])
    fully_clear=all(r['success'] for r in overall)
    practice_result=read(practice) if practice else None
    digest={str(p.relative_to(PROJECT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for group in groups for p in (group['path']/'manifest.json',group['path']/'results.json')}
    digest[str(Path(__file__).resolve().relative_to(PROJECT))] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    payload=dict(generated_at_utc=datetime.now(timezone.utc).isoformat(),fully_clear=fully_clear,
        selected_total=counts,groups=[{k:v for k,v in g.items() if k not in ('rows','path')}|{'path':str(g['path'].relative_to(PROJECT))} for g in groups],
        source_sha256=digest,official_practice=practice_result,
        scope='预先固定的自建案例与独立审计；不代表官方隐藏分布或正式测试成绩')
    (output/'summary.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    columns=['group','case','policy','success','source_count','cleared','virtual_time_s','average_localization_clear_s','move_s','measure_s','switch_s','failed_clears','wall_time_s']
    with (output/'cases.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader()
        for g in groups:
            for r in g['rows']: writer.writerow({'group':g['label'],**{k:r[k] for k in columns if k!='group'}})
    def link(label,path): return f"[{label}]({os.path.relpath(path,output).replace(chr(92),'/')})"
    lines=['# 第四问：结果与交付说明','',
        '本报告由 `src/q4/report.py` 从原始批次生成。先要求整局全清，再比较每局虚拟总秒数除以源数；跨局均值没有改成总时间除以总源数。','',
        f"新模型在下列 {counts['cases']} 局中有 {counts['all_clear']} 局全清，共清除 {counts['cleared']}/{counts['sources']} 个源。"]
    if not fully_clear: lines += ['', '**存在失败，不能给出整体速度更优或可交付的结论。**']
    lines += ['', '## 1. 独立确认与压力结果','',
        '| 批次 | 策略 | 全清局 | 清除/源数 | 平均秒/源 | 平均整局分钟 | 最慢整局分钟 | 最长现实秒 |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for g in groups:
        for p,s in g['stats'].items():
            lines.append(f"| {g['label']} | {LABELS[p]} | {s['all_clear']}/{s['cases']} | {s['cleared']}/{s['sources']} | {s['mean_per_source_s']:.2f} | {s['mean_total_s']/60:.2f} | {s['max_total_s']/60:.2f} | {s['max_wall_s']:.2f} |")
    lines += ['', '本地确认集与压力集使用不同种子。压力集覆盖边界向外、切向、最小接收半径、近共线及源数两端；均包含全向与定向源。具体布局与误差场是团队自建假设，不能外推为官方隐藏测试保证。','',
              '| 批次 | 比较参照 | 新模型更快/配对全清局 | 平均节省分钟/局 | 每源均值降低比例 |',
              '|---|---|---:|---:|---:|']
    for g in groups:
        for pair in g['comparisons']:
            p=pair['reference']; reduction=1-g['stats']['selected']['mean_per_source_s']/g['stats'][p]['mean_per_source_s']
            lines.append(f"| {g['label']} | {LABELS[p]} | {pair['wins']}/{pair['both_all_clear']} | {pair['mean_saved_s']/60:.2f} | {100*reduction:.2f}% |")
    lines += ['', '上述“每源均值降低比例”是两个每局 T/N 均值之比，和逐局百分比再取均值不是同一统计量。原始逐局结果全部保留。','',
              '## 2. 新模型真正增加了什么','',
              '继承 F3 的任务级滚动决策与连续区域覆盖清除思想。第四问的固定半圆发射使阴性反馈同时具有“距离太远”和“背向”两种解释，因此重新建立位置—半径—类型—朝向条件模型，不能复用第三问的阴性圆盘删除规则。','',
              '给定候选位置后，接收半径仅在阴性测点距离处改变约束，发射方向用角弧交集与差集表示。程序对这些区间和角弧解析积分，只抽样位置。这借鉴了条件边际化/Rao–Blackwell化思想；本题公式是独立适配，不是原论文直接给出的算法，也不构成每局提速保证。[Doucet等，2000](https://arxiv.org/pdf/1301.3853)','',
              '共享路线把查漏、补测与清除一起安排。服务点上的未知频道扫描只有能替代后续查漏任务时才承诺执行；删除计划测点须保留完整连续覆盖证书。计划中的未来阴性始终不能提前写入真实状态。多圆清除对每个凸片的全部顶点核验20米覆盖，成功后立即取消后续清除尝试。','',
              '概率模型负责比较动作，保守几何负责保证不误删目标和判断任务是否结束。二者承担不同职责。当前完整rollout作为已试验、未默认采用的能力保留；不可把未启用的模块写成性能来源。','',
              link('完整中文模型与理论推导',PROJECT/'experiments/q4/MODEL.md')+'；'+link('一手来源与适用边界',PROJECT/'experiments/q4/THEORY_RESEARCH.md')+'。','',
              '## 3. baseline与探索选择','',
              'B0 在试验前冻结：固定25点发现扫描、估计中心开放路线、逐源局部补测与清除，保留有限覆盖后备。另以已有 joint25 作较强参照，避免仅胜过简单基线就宣称优秀。','',
              '保留了首版慢例和未采纳方向。无贡献的沿途扫描会吞掉路程节省；22点虽获连续覆盖证明，整局收益并不稳定；4样本完整rollout首批四局两快两慢、计算开销增大；按已见源数直接触发额外扫描也未优于主线。所有选择以完整同案例费用为依据，未删除失败或退步案例。','',
              '源数上界的概率价值试探也另行保留：在已发现15源时估计额外扫描发现第16源的机会。它使用的剩余扫描路线只是价值代理，不能当作真实边际收益；是否采用仍以完整开发案例为据。当前选定配置没有启用该模块。','',
              link('研究入口与全部批次',PROJECT/'experiments/q4/README.md')+'。','',
              '## 4. 必须保留的退步案例','']
    for g in groups:
        for pair in g['comparisons']:
            regressions=pair['regressions']
            lines.append(f"- {g['label']}相对{LABELS[pair['reference']]}：{len(regressions)} 局退步。" +
                (f" 最大退步为 `{regressions[0]['case']}`，多用 {-regressions[0]['saved_s']/60:.2f} 分钟。" if regressions else ''))
    lines += ['', '因此结论是这些已核验批次上的平均改善，并非逐局支配、全局最优或严格最短时间。均匀位置/半径/朝向先验、有限位置池、局部后续工作量近似和启发式路线都可能造成个别退步。', '',
              link('完整动作与成本退步诊断',PROJECT/'outputs/q4/diagnostics01/REPORT.md')+'。该诊断是已发生轨迹的费用解释，不是把某个模块单独关闭后的因果试验。','',
              '## 5. 官方演练核验','']
    if practice_result:
        p=practice_result
        if not p.get('official_all_cleared'): raise ValueError('官方演练尚未与实际UI终局交叉核验')
        lines += [f"shared25版本单局官方演练实际清除 {p['cleared_count']}/{p['official_true_count']} 个源（全向{p['omni_count']}、定向{p['directional_count']}），总虚拟时间 {p['virtual_time_s']:.6f} 秒，平均 {p['average_localization_clear_s']:.2f} 秒/源，现实运行 {p['wall_time_s']:.2f} 秒。",'',
            f"成功频道去重、官方终局源数和独立计费交叉核验通过；累计计费差 {p['accounting_difference_s']:.8f} 秒，日志已保存。"+link('演练核验证据',practice)+
            '。这是单局接线与结果核验，不是正式成绩，不用于与另一个官方案例比较模型速度。']
    else: lines += ['本报告没有接入经过实际UI核验的官方演练记录。']
    lines += ['', '任何问题4正式测试仍须用户针对该次明确授权；交付代码不自行启动正式测试。','',
        '## 6. 复现与文件','',
        '- '+link('正式代码与运行说明',PROJECT/'src/q4/README.md'),
        '- '+link('唯一正式参数',PROJECT/'src/q4/selected_config.json'),
        '- '+link('迁移及动作等价性核验',PROJECT/'outputs/q4/migration_smoke/REPORT.md'),
        '- '+link('逐局明细 CSV',output/'cases.csv'),
        '- '+link('论文图表及对应数据',PROJECT/'outputs/q4/figures01/figure_data.json'),
        '- '+link('机器可读指标与源文件散列',output/'summary.json'),'']
    for g in groups: lines.append('- '+link(g['label']+'原始结果',g['path']/'RESULTS.md'))
    lines += ['', '求解器使用Python标准库；制图另用固定版本matplotlib。结果附带种子、完整场景、参数、源码指纹、逐动作反馈及独立账本。原始题目、第三问程序和正式测试机会均保留。','',
              '模型、代码与文稿由AI辅助生成并执行核验；这不能替代参赛团队对推导、引用与提交内容的人工审阅。']
    (output/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return payload


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--holdout',type=Path,required=True)
    parser.add_argument('--pressure',type=Path,required=True)
    parser.add_argument('--practice',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=build(args.holdout.resolve(),args.pressure.resolve(),args.practice.resolve() if args.practice else None,args.output.resolve())
    print(json.dumps(dict(fully_clear=result['fully_clear'],selected_total=result['selected_total']),ensure_ascii=False))
