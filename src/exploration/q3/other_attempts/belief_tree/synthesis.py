"""由完整配对结果和独立重放账本生成结论数据、逐站审查及图表。"""
import hashlib
import argparse
import json
import math
import statistics
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def trace_review(path):
    actions=[json.loads(x) for x in path.with_name('actions.jsonl').read_text(encoding='utf-8').splitlines()]
    stops=[]
    close=[]
    measured={}
    for x in actions:
        q=tuple(x['position'])
        if not stops or stops[-1]['position']!=q:
            stops.append(dict(position=q,start_step=x['step'],end_step=x['step'],
                              move_s=x['independent_costs']['move_s'],measure_channels=[],cleared=[],failed=[]))
        stop=stops[-1]
        stop['end_step']=x['step']
        stop['time_min']=x['response']['virtual_time_s']/60
        j=x['channel']
        if x['kind']=='measure':
            stop['measure_channels'].append(j)
            for step,p in measured.get(j,[]):
                d=math.dist(p,q)
                if d<30:
                    close.append(dict(step=x['step'],prior_step=step,channel=j,distance_m=d,
                                      response=x['response']['measure_result']))
            measured.setdefault(j,[]).append((x['step'],q))
        else:
            stop['cleared' if x['response']['clear_result']=='success' else 'failed'].append(j)
    last_clear=max(x['step'] for x in actions if x['kind']=='clear' and x['response']['clear_result']=='success')
    last_clear_time=next(x['response']['virtual_time_s'] for x in actions if x['step']==last_clear)
    return dict(stops=stops,close_measure_pairs_under30m=close,last_true_clear_step=last_clear,
                last_true_clear_min=last_clear_time/60,
                post_last_clear=[x for x in actions if x['step']>last_clear],
                warning='近邻测量不自动等于冗余；最后一个实际源的身份仅用于事后诊断，策略不知道真实总数')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--plot',action='store_true',help='需要另有matplotlib环境；默认仅生成数据和逐站审查')
    args=parser.parse_args()
    data=read(HERE/'runs/development_comparison.json')
    rows=data['rows']
    summary={}
    for mode in ('baseline','f3','m3'):
        results=[r['versions'][mode]['result'] for r in rows]
        paths=[ROOT/r['versions'][mode]['path'] for r in rows]
        audits=[read(p.with_name('audit.json')) for p in paths]
        summary[mode]=dict(cases=len(results),all_clear=all(x['success'] for x in results),
                          mean_min=statistics.mean(x['total_s']/60 for x in results),
                          per_source_min=statistics.mean(x['per_source_s']/60 for x in results),
                          worst_min=max(x['total_s']/60 for x in results),
                          mean_moves=statistics.mean(x['moves'] for x in audits),
                          pooled_mean_move_s=sum(x['move_s'] for x in results)/sum(x['moves'] for x in audits),
                          mean_post_clear_min=statistics.mean(x['final_post_clear_check_min'] for x in audits),
                          mean_wall_min=statistics.mean(x['wall_s']/60 for x in results),
                          max_wall_min=max(x['wall_s']/60 for x in results),
                          search_calls=sum(x.get('search_calls',0) for x in audits),
                          search_errors=sum(x['search_errors'] for x in audits),
                          costs_mean_min={k:statistics.mean(x[k]/60 for x in results) for k in
                                          ('move_s','measure_s','switch_s','success_clear_s','fail_clear_s')})
    reviews={}
    for name in ('uniform_biased_330011','line_biased_330020','edge_biased_330014'):
        row=next(r for r in rows if r['case']['name']==name)
        reviews[name]={m:trace_review(ROOT/row['versions'][m]['path']) for m in ('f3','m3')}
    output=dict(summary=summary,reviews=reviews)
    (HERE/'runs/synthesis.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 三个关键案例的逐站审查','',
           '从原始逐动作日志生成，非人工重编路线。近邻测量只标记距离，不直接判成无效。','']
    for name,modes in reviews.items():
        lines+=['## '+name,'']
        for mode,r in modes.items():
            lines += ['### '+mode,'',f"最后一个实际源清除：步骤{r['last_true_clear_step']}，{r['last_true_clear_min']:.3f}分钟；此时间只可事后观察。",'',
                      '|步骤|位置/m|到站移动/s|扫描频道|成功清除|失败清除|累计/min|',
                      '|---|---|---:|---|---|---|---:|']
            for s in r['stops']:
                lines.append(f"|{s['start_step']}—{s['end_step']}|({s['position'][0]:.1f},{s['position'][1]:.1f})|{s['move_s']:.1f}|{','.join(map(str,s['measure_channels']))}|{s['cleared']}|{s['failed']}|{s['time_min']:.3f}|")
            lines += ['',f"同频道30米以内测量对：{len(r['close_measure_pairs_under30m'])}；具体步骤见synthesis.json。",'']
    (HERE/'TRACE_REVIEW.md').write_text('\n'.join(lines),encoding='utf-8')
    if not args.plot:
        print(json.dumps(summary,ensure_ascii=False))
        return
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['font.sans-serif']=['Microsoft YaHei']
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
    ax=axes[0]
    modes=['baseline','f3','m3']
    bottoms=[0.,0.,0.]
    for key,label,color in [('move_s','移动','#477aab'),('measure_s','扫描','#db9b45'),
                            ('switch_s','切频','#d5c59c'),('success_clear_s','成功清除','#529880'),
                            ('fail_clear_s','失败清除','#b34b50')]:
        vals=[summary[m]['costs_mean_min'][key] for m in modes]
        ax.bar(modes,vals,bottom=bottoms,label=label,color=color)
        bottoms=[b+v for b,v in zip(bottoms,vals)]
    for i,m in enumerate(modes):ax.text(i,bottoms[i]+.6,f'{bottoms[i]:.2f}',ha='center')
    ax.set_xticks(range(3),['七点 baseline','旧版 F3','整站树 M3'])
    ax.set_ylabel('虚拟分钟')
    ax.set_title('8个开发案例的平均完整成本')
    ax.set_ylim(0,78)
    ax.legend(fontsize=8,ncol=3,loc='upper center')
    ax=axes[1]
    name='line_biased_330020'
    row=next(r for r in rows if r['case']['name']==name)
    totals=[row['versions'][m]['result']['total_s']/60 for m in ('f3','m3')]
    clears=[reviews[name][m]['last_true_clear_min'] for m in ('f3','m3')]
    tails=[t-c for t,c in zip(totals,clears)]
    ax.barh(['旧版 F3','整站树 M3'],clears,color='#477aab',label='直到最后实际清除')
    ax.barh(['旧版 F3','整站树 M3'],tails,left=clears,color='#bd665d',label='之后的查漏')
    for i,(c,t,total) in enumerate(zip(clears,tails,totals)):
        ax.text(c/2,i,f'{c:.2f}',ha='center',va='center',color='white')
        if t:ax.text(c+t/2,i,f'{t:.2f}',ha='center',va='center',color='white')
        ax.text(total+1,i,f'{total:.2f}',va='center')
    ax.set_xlim(0,68)
    ax.set_xlabel('虚拟分钟')
    ax.set_title('直线/偏置案例：提前清除的收益被查漏抵消')
    ax.legend(fontsize=8,loc='upper center')
    fig.savefig(HERE/'time_breakdown.png',dpi=170)
    plt.close(fig)
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':main()
