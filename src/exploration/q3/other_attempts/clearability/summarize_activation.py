"""严格区分新增筛选与函数形状的配对结果。"""
import json
import statistics
from pathlib import Path

HERE=Path(__file__).resolve().parent
OUT=HERE/'runs/activation_only'


def main():
    rows=[]
    cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'))
    for i,c in enumerate(cases):
        base=HERE.parent/'refinement/runs/demo_f3_20260912' if i==0 else HERE/'runs/fresh_loaded'
        row={'case':c['name'],'sources':len(c['sources'])}
        for mode in ('f3','linear','sigmoid'):
            path=(base if mode=='f3' else OUT)/c['name']/mode
            r=json.loads((path/'result.json').read_text(encoding='utf-8'))
            row[mode]={k:r[k] for k in ('success','total_s','move_s','measure_s','switch_s','fail_clear_s','measure_count','failreason')}
        rows.append(row)
    assert all(r[m]['success'] for r in rows for m in ('f3','linear','sigmoid')),'failure retained; do not average successful subset'
    summary={}
    for label,selected in [('all5',rows),('other4',rows[1:])]:
        summary[label]={m:statistics.mean(r[m]['total_s']/60 for r in selected) for m in ('f3','linear','sigmoid')}
        summary[label]['sigmoid_saving_vs_f3']=summary[label]['f3']-summary[label]['sigmoid']
        summary[label]['sigmoid_saving_vs_linear']=summary[label]['linear']-summary[label]['sigmoid']
        summary[label]['sigmoid_wins_vs_f3']=sum(r['sigmoid']['total_s']<r['f3']['total_s'] for r in selected)
        summary[label]['sigmoid_wins_vs_linear']=sum(r['sigmoid']['total_s']<r['linear']['total_s'] for r in selected)
    d={'rows':rows,'summary':summary,'all_clear':True,'new_episodes':10,
       'equivalence':json.loads((OUT/'equivalence.json').read_text(encoding='utf-8'))}
    (OUT/'comparison.json').write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 只改变补测效用函数的对照','',
       '原F3没有待替换的半径激活函数，它按条件完整续行时间比较动作。因此采用三组：原F3；F3加线性效用共享补测筛选；F3加指定Sigmoid共享补测筛选。后两组仅函数不同。',
       '', '保留F3初始选择、候选测点、清除规则、查漏路线、条件F1续行。只筛选非初始、非主目标的已知频道共享扫描；不筛未知频道。空站保留一条原动作，与旧调度器约束一致。没有增加30米禁测、0.8门槛、强制两圆清除或内侧偏好。',
       '', '两组用相同12个条件位置/半径样本、相同三节点测角积分，比较当前扫描预期效用增量/扫描秒数与原两侧视角的效用增量/移动检测秒数。线性U=min(1,max(0,(1500-r)/1480))；Sigmoid为用户确认版本。线性归一化斜率在比率比较中抵消，代表按绝对半径缩小进行比较；不冒充原F3已有函数。',
       '', '关闭筛选后139条动作的类别、频道、原因和坐标与原F3完全一致。两项检查通过；所有10次新增完整运行逐动作独立复算反馈和费用。使用已看过的5个本地场景，属于机制消融而非独立泛化确认。','',
       '|场景|源数|原F3/分钟|线性/分钟|Sigmoid/分钟|Sigmoid相对F3节省|','|---|---:|---:|---:|---:|---:|']
    for r in rows:lines.append('|'+r['case']+'|'+str(r['sources'])+'|'+'|'.join(f"{r[m]['total_s']/60:.4f}" for m in ('f3','linear','sigmoid'))+f"|{(r['f3']['total_s']-r['sigmoid']['total_s'])/60:.4f}|")
    for label,title in [('all5','全部5例'),('other4','除演示外4例')]:
        s=summary[label]
        lines.extend(['',f"{title}：F3 {s['f3']:.4f}分钟，线性 {s['linear']:.4f}分钟，Sigmoid {s['sigmoid']:.4f}分钟；Sigmoid相对F3节省{s['sigmoid_saving_vs_f3']:.4f}分钟，相对线性节省{s['sigmoid_saving_vs_linear']:.4f}分钟。"])
    lines.extend(['','代码：activation_only.py；运行run_activation.py；检查test_activation.py；汇总summarize_activation.py。所有版本和原始动作保留，不修改此前F3与clearability策略。'])
    (HERE/'ACTIVATION_ONLY.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
