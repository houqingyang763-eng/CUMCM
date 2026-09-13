"""每个轻量策略的最好/最差整局配对轨迹，事后绘制。"""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

def read(p):return json.loads(p.read_text(encoding='utf-8'))

def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);args=p.parse_args();run=args.run.resolve()
    root=Path(__file__).resolve().parents[4]
    analysis=read(run/'analysis.json');manifest=read(run/'manifest.json')['baseline_manifest']
    items={c['name']:c for c in manifest['cases']};cases={c['name']:c for c in read(run/'cases.json')}
    for mode,group in analysis['groups'].items():
        valid=[p for p in group['pairs'] if 'saving' in p]
        if not valid:continue
        selected=[max(valid,key=lambda p:p['saving']['total_s']),min(valid,key=lambda p:p['saving']['total_s'])]
        fig,axes=plt.subplots(2,2,figsize=(12,12))
        for row,pair in enumerate(selected):
            name=pair['case'];d=pair['first_divergence']
            paths=[root/items[name]['baseline_actions'],run/mode/name/'actions.jsonl']
            for col,(path,label) in enumerate(zip(paths,['F3',mode])):
                ax=axes[row,col];rows=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
                points=[(0,0)]+[r['position'] for r in rows]
                ax.add_patch(Circle((0,0),1800,fill=False,color='.65',linewidth=.8))
                ax.plot([q[0] for q in points],[q[1] for q in points],color='#2665a8',lw=1,alpha=.7)
                stops=analysis['data'][name][label]['diagnostics']['stops']
                for kind,marker,color in [('pure_scan','s','#d77a22'),('service','o','#23834b'),('discovery','^','#8b459d')]:
                    q=[s['position'] for s in stops if s['type']==kind]
                    if q:ax.scatter([x[0] for x in q],[x[1] for x in q],marker=marker,s=30,facecolors='none',edgecolors=color,label=kind)
                for s in cases[name]['sources']:ax.plot(*s['position'],'k+',ms=6)
                if d:
                    q=d['old' if col==0 else 'new']['position'];ax.plot(*q,'r*',ms=10)
                    ax.annotate('first difference '+str(d['step']),q,xytext=(5,6),textcoords='offset points',fontsize=8)
                result=analysis['data'][name][label]['result']
                ax.set_title('{} | {} | {:.2f} min'.format(label,name,result['total_s']/60),fontsize=9)
                ax.set(xlim=(-2020,2020),ylim=(-2020,2020),xlabel='x (m)',ylabel='y (m)')
                ax.set_aspect('equal');ax.grid(alpha=.15);ax.legend(fontsize=7,loc='lower right')
            axes[row,0].text(.02,.98,'{}: saving {:+.2f} min'.format('Best' if row==0 else 'Worst',pair['saving']['total_s']/60),
                transform=axes[row,0].transAxes,va='top',fontsize=9)
        fig.suptitle('Full actual routes | crosses: true sources, post-hoc only | '+mode)
        fig.tight_layout(rect=(0,0,1,.97));fig.savefig(str(run/('routes_'+mode+'.png')),dpi=140);plt.close(fig)

if __name__=='__main__':main()
