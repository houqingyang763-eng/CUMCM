"""补充回放中的数值讲解和证据记录；不运行或修改策略。"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True)
    p.add_argument('--visual',type=Path,required=True)
    args=p.parse_args()
    case=json.loads((args.root/'cases.json').read_text(encoding='utf-8'))[0]
    folder=args.root/case['name']/'f3'
    data=json.loads((folder/'view_data.json').read_text(encoding='utf-8'))
    actions=[json.loads(x) for x in (folder/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    for item,action in zip(data['single'],actions):
        if action['response'].get('measure_result')=='direction':
            item['feedback']+=f" 测得方向 {action['response']['svd_deg']:.2f}°。"
        j=action['channel']
        before=next(c for c in data['frames'][action['step']-1]['channels'] if c['j']==j)
        after=next(c for c in data['frames'][action['step']]['channels'] if c['j']==j)
        if action['kind']=='clear' and before['status']=='found':
            item['why']+=f" 清除前的可能区域包围半径为 {before['radius']:.2f} 米。"
        if before['status']==after['status']=='found':
            item['feedback']+=f" 包围半径 {before['radius']:.2f} → {after['radius']:.2f} 米。"
    data['options']=[v for v in data['options'] if v['name'].endswith('_all')]
    # Full-precision frames remain in view_data; the UI uses display-only rounding.
    (folder/'view_data.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    def rounded(x):
        if isinstance(x,float):return round(x,2)
        if isinstance(x,dict):return {k:rounded(v) for k,v in x.items()}
        if isinstance(x,list):return [rounded(v) for v in x]
        return x
    compact=rounded({'variants':{'f3':data}})
    pool=[];index={}
    for frame in compact['variants']['f3']['frames']:
        ids=[]
        for c in frame['channels']:
            key=json.dumps(c,ensure_ascii=False,separators=(',',':'))
            if key not in index:index[key]=len(pool);pool.append(c)
            ids.append(index[key])
        frame['channels']=ids
    compact['channelPool']=pool
    payload=json.dumps(compact,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
    html=args.visual.read_text(encoding='utf-8')
    html=re.sub(r'(<script type="application/json" id="patrol-refinement-data">).*?(</script>)',
                lambda m:m[1]+payload+m[2],html,count=1,flags=re.S)
    # Place measured-point labels using the same collision avoidance as target labels.
    html=html.replace('    const placed=[];','')
    html=html.replace('    if(chosen){','    const placed=[];\n    if(chosen){',1)
    html=html.replace("if(ui.zoom.checked || histories.length<8)scene.append(svg('text',{x:x+6,y:y-6},`测${a.step}`));",
                      "if(ui.zoom.checked || histories.length<8)label(x,y,`测${a.step}`);")
    # Unique DOM and SVG identifiers when several replays occur in one conversation.
    html=html.replace('patrol-refinement','f3-fresh-replay').replace('refinement-domain','f3-fresh-domain').replace('refinement-viewport','f3-fresh-viewport')
    assert len(html.encode('utf-8'))<1_000_000
    args.visual.write_text(html,encoding='utf-8')
    final=data['frames'][-1]
    assert final['complete'] and all(c['status'] in ('cleared','absent') for c in final['channels'])
    assert len(data['frames'])==len(actions)+1 and len(data['single'])==len(actions)
    assert sorted(i for g in data['groups'] for i in range(g['start'],g['end']+1))==list(range(1,len(actions)+1))
    initial=data['frames'][40]
    clears=[a for a in actions if a['response'].get('clear_result')=='success']
    core=Path(__file__).parent
    prior=json.loads((core/'VALIDATION.json').read_text(encoding='utf-8'))['runtime_sha256']
    matches={name:hashlib.sha256((core/name).read_bytes()).hexdigest()==next(h for p,h in prior.items() if p.endswith(name))
             for name in ['refined.py','posterior.py']}
    assert all(matches.values())
    receipt=json.loads((args.root/'replay_receipt.json').read_text(encoding='utf-8'))
    receipt.update(core_matches_previous_validation=matches,frame_sequence_checked=True,
        first_two_stations_seen=len(initial['seen']),first_clear_step=clears[0]['step'],
        first_clear_min=clears[0]['response']['virtual_time_s']/60,
        last_clear_step=clears[-1]['step'],last_clear_min=clears[-1]['response']['virtual_time_s']/60,
        tail_after_last_clear_min=(final['time']-clears[-1]['response']['virtual_time_s'])/60,
        bytes=args.visual.stat().st_size,visual_sha256=hashlib.sha256(args.visual.read_bytes()).hexdigest())
    (args.root/'replay_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# F3 新随机场景逐动作讲解','',f"种子 {case['seed']}；一次抽样，未重抽。共 {len(case['sources'])} 源，{len(actions)} 条动作，{final['time']/60:.3f} 分钟完成。",
           '自建场景；真实位置只用于事后讲解。F3 代码未改。理由解释实际规则和有限试算结果，不表示该步已证明最优。','']
    for item in data['single']:
        lines.extend([f"## 第 {item['start']} 步：{item['title']}",item['action'],item['feedback'],item['why'],''])
    (folder/'WALKTHROUGH.md').write_text('\n\n'.join(lines),encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__':main()
