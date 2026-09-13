"""将指定的两局真实动作作Q4公开状态回放，与旧joint25并排；不运行策略。"""
import argparse
import collections
import hashlib
import html
import importlib.util
import json
import math
from pathlib import Path
import sys

import common

ROOT = Path(__file__).resolve().parents[2]
CASES = [('holdout01','holdout_943004_uniform_outward_hashed','q4-regression-2995','确认集：均匀分布、向外发射'),
         ('pressure01','pressure_944001_edge_tangent_hashed','q4-regression-2141','压力集：边界分布、切向发射')]
RULES = {
 'completion_shared_probe': ('旧方案原地补测','当前位置的检测预计可以减少已发现源的后续工作，按收益与检测费比较后原地补测。'),
 'completion_measure_then_clear': ('旧方案定位补测','按后续定位清除费用的估计安排补测，获得反馈后继续处理。'),
 'completion_certified_clear': ('旧方案保证清除','当前保守位置域被20米清除圆覆盖，前往该点清除。'),
 'completion_cell_clear': ('旧方案小格清除','访问仍相容的有限清除格；按实际反馈判断是否成功。'),
 'task_work_batch': ('旧方案测向任务','依据预期减少的定位工作和绕路代价选择测点与频道组合，执行本条检测。'),
 'q4_initial_scan': ('初始扫描','在预先固定的初始点逐频道获取反馈。'),
 'q4_joint_discovery_scan': ('发现与查漏扫描','按联合任务路线访问发现站，执行尚需频道的扫描。'),
 'q4_joint_local_scan': ('定向条件补测','到按定向条件费用选择的补测站执行队列；不表示为队列中的每个频道单独优化了测点。'),
 'q4_clearance_shared_scan': ('清除停点共享扫描','在已承诺的清除停点扫描未知频道及仍需定位的已知频道，履行该站的扫描任务。'),
 'q4_clear_clear': ('保证清除','当前保守位置域能被20米清除圆覆盖，执行清除。'),
 'q4_try_clear': ('中心试清','位置域较小时允许一次中心尝试；这里不是必然成功的保证清除。'),
 'q4_certified_multiclear': ('认证多圆清除','按能覆盖全部相容位置的二至三圆方案尝试；成功即停。'),
 'q4_certain_here': ('原地保证清除','当前点可以覆盖目标相容位置，直接原地清除。')}

def read(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,data): path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def channel_names(items): return '、'.join('C'+str(j) for j in sorted(set(items)))

def adapt(folder, builder):
    result, case = read(folder/'result.json'), read(folder/'case.json')
    records = [json.loads(line) for line in (folder/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    batch = folder.parents[2]
    manifest = read(batch/'manifest.json')
    for path,digest in manifest['code_sha256'].items():
        if sha(ROOT/path) != digest: raise ValueError('回放状态版本已改变：'+path)
    state = common.Q4State()
    cache = {}
    def frame():
        channels=[]
        for j,c in state.channels.items():
            stamp=(c.status,len(c.observations),len(c.exclusions))
            if j not in cache or cache[j][0]!=stamp:
                item=dict(j=j,status=c.status)
                if c.status=='found':
                    center,radius=c.circle()
                    item.update(center=list(center),radius=radius,polygon=[list(p) for p in c.support()])
                cache[j]=(stamp,item)
            channels.append(cache[j][1])
        return dict(q=list(state.position),time=state.virtual_time_s,complete=state.complete,
                    seen=sorted(state.ever_seen),channels=channels)
    frames=[frame()]
    costs=[]
    unknown_reasons=set()
    for i,a in enumerate(records,1):
        assert a['step']==i and a['response']['accepted']
        response=a['response']
        cost=dict(move_s=math.dist(state.position,a['position'])/5,measure_s=0.,switch_s=0.,clear_s=0.)
        if a['kind']=='measure':
            cost.update(measure_s=5.,switch_s=float(a['channel']!=state.measuring_channel))
        else: cost['clear_s']=5. if response['clear_result']=='success' else 3.
        assert math.isclose(sum(cost.values()),response['virtual_time_s']-state.virtual_time_s,rel_tol=0,abs_tol=1e-6)
        state.update(a,response)
        frames.append(frame()); costs.append(cost)
        if a['reason'] not in RULES: unknown_reasons.add(a['reason'])
    assert state.complete and result['success']
    assert sum(c.status=='cleared' for c in state.channels.values())==result['source_count']
    assert math.isclose(state.virtual_time_s,result['virtual_time_s'],abs_tol=1e-6)
    plans={p['at_action']:p for p in result.get('policy_metadata',{}).get('plans',[])}
    def detail(start,end):
        rows=records[start-1:end]; a=rows[0]; before=frames[start-1]; after=frames[end]
        title,rule=RULES.get(a['reason'],('执行记录','日志未记录可解释的选择依据。'))
        q=a['position']; js=channel_names(r['channel'] for r in rows)
        op='检测' if a['kind']=='measure' else '清除'
        c={k:sum(v[k] for v in costs[start-1:end]) for k in costs[0]}
        action=f'{op}{js}，位置({q[0]:.1f}, {q[1]:.1f})米；移动{c["move_s"]:.1f}秒，检测{c["measure_s"]:.0f}秒，切频{c["switch_s"]:.0f}秒，清除{c["clear_s"]:.0f}秒。'
        words=[]
        new=set(after['seen'])-set(before['seen'])
        if new: words.append('首次发现'+channel_names(new))
        for outcome,label in [('direction','有示向'),('near','5米近距'),('no_signal','无信号'),('success','清除成功'),('no_target_in_range','清除失败')]:
            found=[r['channel'] for r in rows if r['response'].get('measure_result',r['response'].get('clear_result'))==outcome]
            if found: words.append(label+'：'+channel_names(found))
        if len(rows)==1 and rows[0]['response'].get('svd_deg') is not None: words.append(f'示向{rows[0]["response"]["svd_deg"]:.2f}°')
        why='规则说明：'+rule
        p=plans.get(start-1)
        if p and p.get('adopted_substitution'):
            why+=f' 本次计划删去{len(p.get("removed_anchors",[]))}个发现站，预计省{p["base_estimated_cost_s"]-p["estimated_cost_s"]:.1f}秒（计划估计）。'
        return dict(start=start,end=end,title=title,action=action,feedback='；'.join(words),why=why,
                    focus=next(iter(sorted(new)),a['channel']) if len(rows)==1 or new else 0)
    single=[detail(i,i) for i in range(1,len(records)+1)]
    groups=[]; start=1
    for i in range(1,len(records)):
        a,b=records[i-1:i+1]
        same=a['kind']==b['kind']=='measure' and a['position']==b['position'] and a['reason']==b['reason']
        # 仅合并没有新发现、没有计划重算的连续同站阴性扫描；所有动作仍可逐条查看。
        neutral=a['response'].get('measure_result')=='no_signal' and b['response'].get('measure_result')=='no_signal'
        if not (same and neutral and i not in plans): groups.append(detail(start,i)); start=i+1
    groups.append(detail(start,len(records)))
    data=dict(title='旧方案 joint25' if result['policy']=='joint25' else '新模型 shared25',
        case=case,scene=dict(domain_radius=1800,clear_radius=20,bearing_length=1500,angle_error_deg=1.005,unit='米',agent_label='机器狗'),
        frames=frames,actions=[dict(kind=a['kind'],position=a['position'],channel=a['channel'],result=a['response'].get('measure_result',a['response'].get('clear_result')),bearing=a['response'].get('svd_deg')) for a in records],
        single=single,groups=groups,options=[],first_end=len(records)+1,
        initial_why='按本局公开反馈重建第四问状态；没有重新执行选点策略。',
        note='填色是相容位置外包；阴性不画第三问排除圆。',
        provenance=dict(adapter='src/q4/replay_compare.py',adapter_sha256=sha(Path(__file__)),
            inputs={str((folder/n).relative_to(ROOT)):sha(folder/n) for n in ['actions.jsonl','case.json','result.json']},
            state_dependencies=manifest['code_sha256'],ledger_checked=True,unknown_reasons=sorted(unknown_reasons),
            scope='公开状态与原账本重放；真值仅单独用于可关闭的讲解图层'))
    builder.validate(data)
    return data,result

HOOK = """
root.addEventListener('replay-seek-time',event=>{
 stop(); mode='actions'; ui.mode.value=mode;
 const t=Number(event.detail); let lo=0,hi=data.frames.length;
 // The bundled builder rounds displayed frame times to milliseconds.
 while(lo<hi){const mid=(lo+hi)>>1;if(data.frames[mid].time<=t+0.00051)lo=mid+1;else hi=mid;}
 cursor=Math.max(0,lo-1); render();
});
root.addEventListener('replay-focus-channel',event=>{chosen=Number(event.detail)||0;render(false);});
root.addEventListener('replay-zoom',event=>{ui.zoom.checked=Boolean(event.detail);draw();});
root.addEventListener('replay-truth',event=>{ui.truth.checked=Boolean(event.detail);render(false);});
"""
SECTOR = """
 if(ui.truth.checked&&chosen){const t=truth.find(v=>v.channel===chosen);
 if(t&&Number.isFinite(t.orientation)&&Number.isFinite(t.radius)){
 const ps=[t.position];for(let k=0;k<=48;k++){const a=(t.orientation-90+180*k/48)*Math.PI/180;ps.push([t.position[0]+t.radius*Math.cos(a),t.position[1]+t.radius*Math.sin(a)]);}
 scene.append(svg('polygon',{points:pts(ps),fill:color.truth,'fill-opacity':.09,stroke:'none'}));
 const a=t.orientation*Math.PI/180,end=[t.position[0]+Math.min(300,t.radius)*Math.cos(a),t.position[1]+Math.min(300,t.radius)*Math.sin(a)];
 scene.append(svg('line',{x1:X(t.position[0]),y1:Y(t.position[1]),x2:X(end[0]),y2:Y(end[1]),stroke:color.truth,'stroke-width':2}));
 label(X(end[0]),Y(end[1]),'发射方向');}}
"""

def widget(builder,data,path):
    receipt=builder.build(data,path,title=data['title'])
    fragment=path.read_text(encoding='utf-8')
    anchor='new ResizeObserver(draw).observe(ui.plot);render();'
    assert fragment.count(anchor)==1
    fragment=fragment.replace(anchor,HOOK+'\n'+anchor)
    anchor=' const histories=data.actions.slice(0,g.end)'
    assert fragment.count(anchor)==1
    fragment=fragment.replace(anchor,SECTOR+'\n'+anchor)
    # 局部图形仍遵循原模板；同页两个回放各有唯一ID。
    fragment=fragment.replace('填色：当前可能范围；细轮廓：上一步范围','填色：相容位置外包；细轮廓：上一步；灰扇形：所选源真实发射区')
    path.write_text(fragment,encoding='utf-8')
    receipt.update(bytes=path.stat().st_size,sha256=sha(path),input_sha256=sha(path.with_suffix('.json')),
                   adaptation='Q4省略阴性排除圆；增加真值定向扇形和共同时间/频道操作接口')
    dump(path.with_suffix('.receipt.json'),receipt)
    return fragment,receipt

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--visualization-dir',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists(): raise ValueError('保留已生成回放，请使用新的输出目录')
    args.output.mkdir(parents=True)
    spec=importlib.util.spec_from_file_location('run_replay_builder',args.skill/'scripts/build_replay.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    template=Path(__file__).with_name('replay_pair.html').read_text(encoding='utf-8')
    receipts=[]
    for batch,case,stem,title in CASES:
        pairdir=args.output/stem;pairdir.mkdir()
        panels=[]; results=[]; views=[]
        for policy in ('joint25','selected'):
            data,result=adapt(ROOT/'outputs/q4'/batch/'cases'/case/policy,builder)
            path=pairdir/(policy+'.html');dump(path.with_suffix('.json'),data)
            fragment,receipt=widget(builder,data,path)
            panels.append('<section>'+fragment+'</section>');results.append(result);views.append(data)
            print(json.dumps(dict(case=case,policy=policy,**receipt),ensure_ascii=False),flush=True)
        old,new=results
        info=dict(title=title,case=case,old_total=old['virtual_time_s'],new_total=new['virtual_time_s'],
            extra_s=new['virtual_time_s']-old['virtual_time_s'],sources=old['source_count'],
            cost_rows=[dict(name=d['title'],move=r['move_s'],measure=r['measure_s'],switch=r['switch_s'],clear=r['clear_s'],total=r['virtual_time_s']) for d,r in zip(views,results)],
            known_negative=[sum(1 for i,a in enumerate(d['actions']) if a['result']=='no_signal' and d['frames'][i]['channels'][a['channel']-1]['status']=='found') for d in views])
        tag=stem
        fragment=template.replace('__PAIR_ID__',tag).replace('__PAIR_TITLE__',html.escape(title)).replace('__PANELS__','\n'.join(panels)).replace('__PAIR_DATA__',json.dumps(info,ensure_ascii=False).replace('</','<\\/'))
        final=args.visualization_dir/(stem+'.html')
        assert len(fragment.encode('utf-8'))<1_000_000
        final.parent.mkdir(parents=True,exist_ok=True);final.write_text(fragment,encoding='utf-8')
        assert final.read_text(encoding='utf-8')==fragment
        dump(pairdir/'comparison.json',info)
        receipt=dict(case=case,output=str(final.resolve()),bytes=final.stat().st_size,sha256=sha(final),
            total_actions=sum(len(d['actions']) for d in views),all_complete=all(d['frames'][-1]['complete'] for d in views),
            inputs=[d['provenance'] for d in views],template_sha256=sha(Path(__file__).with_name('replay_pair.html')))
        dump(final.with_suffix('.receipt.json'),receipt);receipts.append(receipt)
    dump(args.output/'receipt.json',receipts)

if __name__=='__main__': main()
