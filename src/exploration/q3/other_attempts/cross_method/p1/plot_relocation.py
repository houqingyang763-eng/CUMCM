"""既有三条长尾的A/R完整真实路线；不导入或运行策略。"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    args = parser.parse_args(); run = args.run.resolve()
    root = Path(__file__).resolve().parents[4]
    analysis = read(run/'analysis.json'); frozen = read(run/'manifest.json')
    prior = root/frozen['prior_run']; cases = {c['name']:c for c in read(run/'cases.json')}
    pairs = {p['case']:p for p in analysis['pairs']}
    names = analysis['long_tail_cases']
    fig,axes = plt.subplots(len(names),2,figsize=(12,16))
    for row,name in enumerate(names):
        pair = pairs[name]; divergence = pair['first_divergence']
        for col,mode in enumerate(('A','R')):
            path = (prior/'A'/name if mode == 'A' else run/name)/'actions.jsonl'
            assert hashlib.sha256(path.read_bytes()).hexdigest() == analysis['source_hashes'][path.relative_to(root).as_posix()]
            rows = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
            value = analysis['data'][name][mode]; ax = axes[row,col]
            points = [(0,0)]+[r['position'] for r in rows]
            ax.add_patch(Circle((0,0),1800,fill=False,color='.65',linewidth=.8))
            ax.plot([q[0] for q in points],[q[1] for q in points],color='#2665a8',lw=1,alpha=.55,label='actual full route')
            clear_indices = [i for i,r in enumerate(rows) if r['kind']=='clear' and r['response'].get('clear_result')=='success']
            if clear_indices:
                tail = [rows[clear_indices[-1]]['position']]+[r['position'] for r in rows[clear_indices[-1]+1:]]
                ax.plot([q[0] for q in tail],[q[1] for q in tail],color='#c8561d',lw=2,alpha=.9,label='after final clearance')
            for kind,marker,color in [('pure_scan','s','#d77a22'),('service','o','#23834b'),('discovery','^','#8b459d')]:
                qs = [s['position'] for s in value['diagnostics']['stops'] if s['type']==kind]
                if qs:
                    ax.scatter([q[0] for q in qs],[q[1] for q in qs],marker=marker,s=30,facecolors='none',edgecolors=color,label=kind)
            for source in cases[name]['sources']:
                ax.plot(*source['position'],'k+',ms=6)
            d = divergence['old' if mode=='A' else 'new'] if divergence else None
            if d:
                ax.plot(*d['position'],'r*',ms=11)
                ax.annotate('first difference '+str(divergence['step']),d['position'],xytext=(5,6),textcoords='offset points',fontsize=8)
            result = value['result']; tail_s = value['extra']['tail_s']
            tail_label = 'NA' if tail_s is None else '{:.1f}s'.format(tail_s)
            ax.set_title('{} | {}\n{:.2f} min | tail {} | {}'.format(mode,name,result['total_s']/60,tail_label,
                         'all clear' if result['success'] else 'FAILED'),fontsize=9)
            limit = max(2020,max((max(abs(q[0]),abs(q[1])) for q in points),default=0)+80)
            ax.set(xlim=(-limit,limit),ylim=(-limit,limit),xlabel='x (m)',ylabel='y (m)')
            ax.set_aspect('equal');ax.grid(alpha=.15);ax.legend(fontsize=6,loc='lower right')
        saving = pair.get('A_saving',{}).get('total_s')
        axes[row,0].text(.02,.98,'R saving vs A: '+('not ranked' if saving is None else '{:+.1f}s'.format(saving)),
                        transform=axes[row,0].transAxes,va='top',fontsize=9)
    fig.suptitle('A vs R: complete actual routes | crosses: true sources, post-hoc only',fontsize=11)
    fig.tight_layout(rect=(0,0,1,.97))
    output = run/'routes_long_tails.png';fig.savefig(str(output),dpi=140);plt.close(fig)
    print(str(output))


if __name__ == '__main__':
    main()
