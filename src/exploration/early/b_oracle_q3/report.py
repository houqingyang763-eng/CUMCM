"""从已完成真值参照生成中文报告和逐例CSV，不重跑路线求解。"""
import csv
import hashlib
import json
from pathlib import Path
import statistics

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'runs/sweep_validation_48100'
oracle_path=OUT/'results.json'
policy_path=ROOT.parent/'b_overnight/runs/q3_sweep_validation/results.json'
summary_path=OUT/'summary.json'
oracle=json.loads(oracle_path.read_text(encoding='utf-8'))
policies=json.loads(policy_path.read_text(encoding='utf-8'))
summary=json.loads(summary_path.read_text(encoding='utf-8'))
lookup={r['case']:r for r in oracle}
joined=[]
for row in policies:
    o=lookup[row['case']]
    residual_clear=row['clear_s']-5*row['source_count']
    difference=row['virtual_time_s']-o['oracle_feasible_s']
    move=row['move_s']-o['oracle_move_s']
    sense=row['measure_s']+row['switch_s']
    assert abs(difference-move-sense-residual_clear)<1e-7
    joined.append(dict(case=row['case'],layout=row['layout'],policy=row['policy'],source_count=row['source_count'],
                       policy_total_s=row['virtual_time_s'],oracle_total_s=o['oracle_feasible_s'],lower_bound_s=o['lower_bound_s'],
                       policy_per_source_s=row['virtual_time_s']/row['source_count'],
                       oracle_per_source_s=o['oracle_per_source_s'],excess_move_s=move,
                       sensing_switch_s=sense,failed_clear_s=residual_clear,excess_total_s=difference))
with (OUT/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(joined[0])); w.writeheader(); w.writerows(joined)
lines=['# 第三问：知道所有位置后，还需要多久？','',
       '**同一批12个案例，当前巡查策略每局平均63.69分钟；已知所有源的个数、频道和位置后，可执行清除路线平均26.19分钟，最优清除时间的数学下界平均24.54分钟。** 当前离理想效率仍有明显差距。',
       '', '这不是新的搜索策略，也不是官方成绩。参照拥有搜索算法没有的真值，免去了发现和排除未知频道；差距包含必要的信息获取成本，不能全部当作可消除的浪费。',
       '', '## 同案例成绩', '',
       '| 方法 | 每源平均秒（主指标） | 整局平均分钟 | 每源最慢四分之一均值/秒 |',
       '|---|---:|---:|---:|']
for key,label in [('lower_bound','数学下界'),('oracle_centers','已知真值的可执行路线'),('committed_baseline','修正后的基础方法'),('completion','默认自适应方法'),('sweep','集中巡查方法')]:
    r=summary[key]
    lines.append(f"| {label} | {r['per_source']['mean']:.2f} | {r['total']['mean']/60:.2f} | {r['per_source']['tail_quarter_mean']:.2f} |")
lines += ['', '每源指标是每局T/N后等权平均；整局平均分钟是辅助读数。下界不是一条可执行路线。理想最优均值被夹在24.54—26.19分钟内，区间宽约1.65分钟，因此这里的理想参照已相当接近已知信息条件下的最优时间。',
          '', '## 目前多出的时间在哪里', '', '| 方法 | 比理想路线多出的分钟 | 其中移动 | 其中检测及切频 | 其中失败清除 |', '|---|---:|---:|---:|---:|']
for name,label in [('committed_baseline','基础方法'),('completion','默认方法'),('sweep','巡查方法')]:
    rows=[r for r in joined if r['policy']==name]
    vals=[statistics.mean(r[k] for r in rows)/60 for k in ('excess_total_s','excess_move_s','sensing_switch_s','failed_clear_s')]
    lines.append('| '+label+' | '+' | '.join(f'{v:.2f}' for v in vals)+' |')
lines += ['', '巡查方法平均多出的37.50分钟中，约25.83分钟来自更长移动，11.63分钟来自检测及切频，失败清除约0.05分钟。移动中的一部分也是为了寻找和交会定位，不能把全部25.83分钟标成不必要绕路。',
          '', '## 不同布局的差距', '', '| 布局（每组3例） | 理想路线分钟 | 数学下界分钟 | 巡查策略分钟 |', '|---|---:|---:|---:|']
for layout,label in [('uniform','分散'),('edge','圆域边缘'),('cluster','三团聚集'),('line','近共线')]:
    rows=[r for r in joined if r['policy']=='sweep' and r['layout']==layout]
    values=[statistics.mean(r[k] for r in rows)/60 for k in ('oracle_total_s','lower_bound_s','policy_total_s')]
    lines.append('| '+label+' | '+' | '.join(f'{v:.2f}' for v in values)+' |')
lines += ['', '布局分组只作这12个已看过案例的诊断，不能据此推断总体胜率。完整逐例表在 [comparison.csv](runs/sweep_validation_48100/comparison.csv)。',
          '', '## 如何解释这个baseline', '',
          '- 基础方法是可部署参照，用来确认改进有没有实际收益。',
          '- 真值路线是效率参照，用来测量已知信息条件与未知信息条件之间的代价；不参与搜索策略选点。',
          '- 数学下界确保没有因理想路线规划得太差而误判空间。真实位置仅来自已有自建案例，未读取官方隐藏数据。',
          '- 当前可说“比基础方法快，但远没有接近真值效率”；还不能说“差距全部可消除”或“在未知信息条件下已经接近最优”。',
          '', '## 证据', '',
          '5项必要检查通过：动态规划与6节点全排列一致、整数距离上下取整关系、单源解析清除距离、重叠圆盘、下界与独立构造可行路线对照。12个真值路线共159个源全清，原自建环境逐动作执行并核对累计计费；36条策略—案例费用分解恒等式核对通过。',
          '', '详见 [构造与证明](README.md)、[路线及清除动作](runs/sweep_validation_48100/results.json)、[汇总](runs/sweep_validation_48100/summary.json)、[输入源码散列](runs/sweep_validation_48100/manifest.json)。这些是AI实现与核验，仍待团队人工审阅。']
(ROOT/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
manifest={'decomposition_rows':len(joined),'source_count':sum(r['source_count'] for r in oracle),
          'max_ideal_interval_width_s':max(r['ideal_interval_width_s'] for r in oracle),
          'solve_wall_s':sum(r['wall_s'] for r in oracle),
          'sha256':{str(p.relative_to(ROOT.parent.parent)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (Path(__file__),ROOT/'test_oracle.py',oracle_path,policy_path,summary_path)}}
(OUT/'report_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=False))
