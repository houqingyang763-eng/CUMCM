"""由冻结批次生成可导出论文图：主指标、成本分解、配对散点与路线例图。"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

NAMES = {'baseline': '简单基线 B0', 'joint25': '已有方案', 'selected': '第四问新模型', 'shared': '第四问新模型'}
COLORS = {'baseline': '#9aa5b1', 'joint25': '#c9883b', 'selected': '#087e8b', 'shared': '#087e8b'}


def load_batch(path):
    rows = json.loads((path/'results.json').read_text(encoding='utf-8'))
    if not rows or not all(r['success'] for r in rows):
        raise ValueError('存在失败时不能生成全部全清的速度比较图')
    return rows


def save(fig, folder, stem):
    fig.savefig(folder/f'{stem}.png', dpi=200, facecolor='white')
    fig.savefig(folder/f'{stem}.pdf', facecolor='white')
    plt.close(fig)


def plot(batches, output, chosen='selected'):
    output.mkdir(parents=True, exist_ok=False)
    plt.rcParams.update({'font.family': ['Microsoft YaHei', 'SimHei', 'DejaVu Sans'],
        'axes.unicode_minus': False, 'font.size': 10, 'axes.spines.top': False,
        'axes.spines.right': False, 'pdf.fonttype': 42, 'savefig.bbox': 'tight'})
    groups = [(label, path, load_batch(path)) for label, path in batches]
    policies = ['baseline', 'joint25', chosen]
    figure_data = dict(groups={}, matplotlib_version=matplotlib.__version__,
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    fig, axes = plt.subplots(1, len(groups), figsize=(5*len(groups), 4.6), squeeze=False)
    for ax, (label, path, rows) in zip(axes[0], groups):
        stats = []
        for policy in policies:
            current = [r for r in rows if r['policy'] == policy]
            if not current:
                raise ValueError(f'缺少策略 {policy}')
            stats.append(statistics.mean(r['average_localization_clear_s'] for r in current))
        ax.bar(range(3), stats, color=[COLORS[p] for p in policies], width=.62)
        for i, value in enumerate(stats):
            ax.text(i, value+max(stats)*.024, f'{value:.1f}', ha='center', va='bottom', fontweight='bold')
        ax.set_xticks(range(3), [NAMES[p] for p in policies], fontsize=10)
        ax.set_ylabel('平均每源用时（秒/源）')
        count = len([r for r in rows if r['policy'] == chosen])
        ax.set_title(f'{label} · {count} 局全部清除', fontsize=13, pad=14)
        ax.set_ylim(0, max(stats)*1.2)
        ax.set_axisbelow(True)
        ax.grid(axis='y', alpha=.2)
        figure_data['groups'][label] = dict(batch=str(path), mean_seconds_per_source=dict(zip(policies,stats)),
            results_sha256=hashlib.sha256((path/'results.json').read_bytes()).hexdigest())
    fig.suptitle('同案例比较：先全清，再比较每局总时间 / 源数', fontsize=15, y=1.025)
    fig.tight_layout()
    save(fig, output, 'efficiency')

    fig, axes = plt.subplots(1, len(groups), figsize=(5*len(groups),4.7), squeeze=False)
    parts = [('move_s','移动','#31546d'), ('measure_s','测向','#63a6ae'),
             ('switch_s','切频','#a8c7c4'), ('clear','清除','#d9a763')]
    for ax, (label, path, rows) in zip(axes[0], groups):
        bottom = [0.]*3
        for key, name, color in parts:
            values = []
            for policy in policies:
                current = [r for r in rows if r['policy'] == policy]
                values.append(statistics.mean((r['ledger']['success_clear_s']+r['ledger']['failed_clear_s'])
                    if key=='clear' else r[key] for r in current)/60)
            ax.bar(range(3), values, bottom=bottom, label=name, color=color, width=.62)
            bottom = [a+b for a,b in zip(bottom,values)]
        for i, value in enumerate(bottom):
            ax.text(i,value+2,f'{value:.1f}',ha='center')
        ax.set_xticks(range(3),[NAMES[p] for p in policies],fontsize=10)
        ax.set_ylabel('平均整局用时（分钟）')
        ax.set_title(label,fontsize=13,pad=12)
        ax.set_ylim(0,max(bottom)*1.17)
    axes[0][-1].legend(ncol=4,loc='upper center',bbox_to_anchor=(.5,-.11),frameon=False)
    fig.tight_layout()
    save(fig, output, 'cost_breakdown')

    fig, axes = plt.subplots(1,2,figsize=(10,4.8))
    markers = ['o','^','s']
    for ax, reference in zip(axes,('baseline','joint25')):
        values = []
        for i,(label,path,rows) in enumerate(groups):
            ref = {r['case']:r for r in rows if r['policy']==reference}
            current = {r['case']:r for r in rows if r['policy']==chosen}
            if set(ref)!=set(current):
                raise ValueError('配对案例不相同')
            xs = [ref[c]['average_localization_clear_s'] for c in sorted(ref)]
            ys = [current[c]['average_localization_clear_s'] for c in sorted(ref)]
            ax.scatter(xs,ys,label=label,marker=markers[i%len(markers)],s=48,
                color=['#087e8b','#c9883b','#705880'][i%3],alpha=.85,edgecolors='white',linewidths=.5)
            values += xs+ys
        lo,hi = min(values)*.9,max(values)*1.06
        ax.plot([lo,hi],[lo,hi],'--',color='#89949b',lw=1)
        ax.set(xlim=(lo,hi),ylim=(lo,hi),xlabel=NAMES[reference]+'（秒/源）',ylabel='新模型（秒/源）')
        ax.set_aspect('equal',adjustable='box')
        ax.set_title('虚线下方表示新模型更快',fontsize=11)
        ax.legend(frameon=False)
    fig.tight_layout()
    save(fig, output, 'paired_cases')

    # 固定选择首个确认案例，避免为了展示只选择最大的节省局。
    label, path, rows = groups[0]
    case = sorted(r['case'] for r in rows if r['policy']==chosen)[0]
    fig, axes = plt.subplots(1,2,figsize=(10.5,5))
    for ax,policy in zip(axes,('baseline',chosen)):
        directory = path/'cases'/case/policy
        scene = json.loads((directory/'case.json').read_text(encoding='utf-8'))
        trace = [json.loads(s) for s in (directory/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
        points = [(0.,0.)]
        for row in trace:
            q=tuple(row['position'])
            if q!=points[-1]: points.append(q)
        ax.plot([p[0] for p in points],[p[1] for p in points],color=COLORS[policy],lw=.85,alpha=.75)
        measures={tuple(r['position']) for r in trace if r['kind']=='measure'}
        ax.scatter([p[0] for p in measures],[p[1] for p in measures],s=10,color=COLORS[policy],alpha=.75,label='测点')
        positions=[s['position'] for s in scene['sources']]
        ax.scatter([p[0] for p in positions],[p[1] for p in positions],marker='*',s=65,color='#be513f',label='源位置（事后显示）',zorder=5)
        ax.add_patch(Circle((0,0),1800,fill=False,linestyle='--',edgecolor='#9aa5b1',lw=1))
        ax.scatter([0],[0],s=38,marker='s',color='#1f2933',label='起点',zorder=6)
        result=next(r for r in rows if r['case']==case and r['policy']==policy)
        ax.set_title(f"{NAMES[policy]} · {result['virtual_time_s']/60:.1f} 分钟",fontsize=12)
        ax.set(xlabel='x（米）',ylabel='y（米）',xlim=(-2150,2150),ylim=(-2150,2150))
        ax.set_aspect('equal')
    axes[1].legend(loc='upper center',bbox_to_anchor=(.5,-.13),ncol=3,frameon=False,fontsize=9)
    fig.suptitle(f'固定展示确认集首局：{case}\n源真值仅用于事后作图，不提供给在线策略',fontsize=11,y=1.02)
    fig.tight_layout()
    save(fig,output,'example_routes')
    figure_data['example_case']=case
    (output/'figure_data.json').write_text(json.dumps(figure_data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--holdout',type=Path,required=True)
    parser.add_argument('--pressure',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--chosen',default='selected')
    args=parser.parse_args()
    plot([('独立确认集',args.holdout),('压力集',args.pressure)],args.output,args.chosen)
