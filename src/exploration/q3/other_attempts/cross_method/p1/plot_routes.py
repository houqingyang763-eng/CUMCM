"""事后画真实路线；真实源仅用于解释，不进入策略。"""
import argparse
import json
import math
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle


def load(p): return json.loads(p.read_text(encoding='utf-8'))


def main():
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);args=p.parse_args()
    root=Path(__file__).resolve().parents[4]
    analysis=load(args.run/'analysis.json'); frozen=load(args.run/'manifest.json')
    items={x['name']:x for x in frozen['baseline_manifest']['screening_cases']}
    cases={c['name']:c for c in load(args.run/'cases.json')}
    pairs=analysis['pairs']
    fig,axes=plt.subplots(4,2,figsize=(12,21))
    for ax,pair in zip(axes.flat,pairs):
        name=pair['case']; case=cases[name]
        ax.add_patch(Circle((0,0),1800,fill=False,color='0.65',linewidth=.8))
        oldpath=root/items[name]['artifacts']['f3/actions.jsonl']['path']
        for path,label,color in [(oldpath,'F3','#b55b2a'),(args.run/name/'actions.jsonl','P1','#1766ad')]:
            rows=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
            points=[(0,0)]+[r['position'] for r in rows]
            ax.plot([q[0] for q in points],[q[1] for q in points],color=color,alpha=.8,lw=1,label=label)
            clears=[r['position'] for r in rows if r['kind']=='clear' and r['response']['clear_result']=='success']
            ax.scatter([q[0] for q in clears],[q[1] for q in clears],s=18,facecolors='none',edgecolors=color)
        for src in case['sources']:
            q=src['position']; ax.plot(*q,'k+',ms=5)
        d=pair['first_divergence']
        if d:
            for label,kind,col in [('F3','old','#b55b2a'),('P1','new','#1766ad')]:
                q=d[kind]['position']; ax.scatter(*q,s=50,edgecolors=col,facecolors='white',zorder=5)
                ax.annotate(f'{label} first difference: {d["step"]}',q,xytext=(5,8 if kind=='old' else -16),
                            textcoords='offset points',fontsize=6,color=col)
        saving=pair.get('saving',{}).get('total_s')
        text='FAILED' if saving is None else f'saving {saving/60:+.2f} min'
        ax.set_title(f'{name} | N={pair["n"]} | {text}',fontsize=10)
        ax.set(xlim=(-2050,2050),ylim=(-2050,2050),xlabel='x (m)',ylabel='y (m)')
        ax.set_aspect('equal');ax.grid(alpha=.15);ax.legend(loc='lower right',fontsize=7)
    fig.suptitle('Paired complete routes | crosses: true sources for post-hoc review only',fontsize=13)
    fig.tight_layout(rect=(0,0,1,.98));fig.savefig(args.run/'paired_routes.png',dpi=170);plt.close(fig)
    complete=[x for x in pairs if 'saving' in x]
    if not complete: return
    worst=min(complete,key=lambda x:x['saving']['total_s'])
    if worst['saving']['total_s']>=0: return
    name=worst['case']; case=cases[name]
    oldpath=root/items[name]['artifacts']['f3/actions.jsonl']['path']
    oldsegments=worst['clearance_segments']['baseline']; newsegments=worst['clearance_segments']['candidate']
    if worst['same_clearance_order']:
        selected=sorted(zip(oldsegments,newsegments),key=lambda x:x[1]['move_s']-x[0]['move_s'],reverse=True)[:3]
    else:
        selected=[(None,x) for x in sorted(newsegments,key=lambda x:x['move_s'],reverse=True)[:3]]
    fig,axes=plt.subplots(1,2,figsize=(13,6.5))
    for index,(ax,path,label) in enumerate(zip(axes,[oldpath,args.run/name/'actions.jsonl'],['F3','P1'])):
        rows=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines()]
        points=[(0,0)]+[x['position'] for x in rows]
        ax.plot([x[0] for x in points],[x[1] for x in points],color='.7',lw=1)
        ax.add_patch(Circle((0,0),1800,fill=False,color='.6',lw=.8))
        for src in case['sources']:
            ax.plot(*src['position'],'k+',ms=6)
        for color,segment_pair in zip(['#c23b22','#2879ad','#7b4caa'],selected):
            segment=segment_pair[index]
            if not segment: continue
            part=points[segment['start_step']-1:segment['end_step']+1]
            ax.plot([x[0] for x in part],[x[1] for x in part],color=color,lw=2,
                    label=f"to channel {segment['channel']}: {segment['move_s']:.1f} s moving")
            last=None; nearby=0
            for point in segment['movement_steps']:
                nearby=nearby+1 if last is not None and math.hypot(point['position'][0]-last[0],point['position'][1]-last[1])<120 else 0
                ax.plot(*point['position'],'o',ms=3,color=color)
                ax.annotate(str(point['step']),point['position'],xytext=(5,5+10*nearby),textcoords='offset points',fontsize=7,color=color)
                last=point['position']
        ax.set(xlim=(-2050,2050),ylim=(-2050,2050),xlabel='x (m)',ylabel='y (m)',title=label)
        ax.set_aspect('equal');ax.grid(alpha=.15);ax.legend(fontsize=7,loc='lower right')
    fig.suptitle(f"{name} | P1 slower by {-worst['saving']['total_s']/60:.2f} min | labels: action numbers")
    fig.tight_layout(rect=(0,0,1,.95));fig.savefig(args.run/'worst_routes.png',dpi=170);plt.close(fig)


if __name__=='__main__': main()
