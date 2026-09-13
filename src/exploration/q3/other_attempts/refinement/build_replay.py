"""随机场景四版本回放：只从已执行日志重建公开几何，不重新选案例。"""
import argparse
import json
import math
from pathlib import Path

from posterior import a
from diagnose import replay as verify_replay

HERE=Path(__file__).resolve().parent
LABELS={'current':'本轮修改前','f1':'F1 冗余过滤','f3':'F3 完整改进','f4':'F4 独立抽样复查'}


def snapshot(state):
    channels=[]
    for j,c in state.channels.items():
        row={'j':j,'status':c.status}
        if c.status=='found':
            q,r=c.circle();row.update(center=q,radius=r,polygon=c.support())
        channels.append(row)
    return {'q':state.position,'time':state.virtual_time_s,'channels':channels,
            'seen':sorted(state.ever_seen),'complete':state.complete,'absence_reasons':state.absence_reasons.copy()}


def channels(values):
    return '、'.join('C'+str(j) for j in sorted(set(values))) or '无'


def build_variant(root,case,mode,selection):
    directory=root/case['name']/mode
    actions=[json.loads(x) for x in (directory/'actions.jsonl').read_text().splitlines()]
    result=json.loads((directory/'result.json').read_text())
    metadata=json.loads((directory/'metadata.json').read_text())
    decisions={x['at_action']:x for x in metadata.get('refinement_decisions',[])}
    state=a.CoverageInformationState();frames=[snapshot(state)]
    for row in actions:
        state.update(row,row['response']);frames.append(snapshot(state))
    assert state.complete and abs(state.virtual_time_s-result['total_s'])<1e-6
    verified=verify_replay(directory,a.Scenario.from_dict(case))
    names={'initial_1':'第一轮搜索','initial_2':'自适应第二轮','joint_cover_scan':'查漏并共享定位',
           'planned_transverse_scan':'横向补测','planned_clearance_scan':'清除停点共享扫描',
           'current_view':'当前位置补测','certain_here':'原地保证清除','certain_center':'到定位中心清除',
           'single_center_try':'中心尝试清除','finite_cell_clear':'剩余小格清除',
           'refined_shared_scan':'试算选出的共享测点','certified_multi_clear':'有覆盖保证的多次清除'}
    def detail(start,end):
        batch=actions[start-1:end];first=batch[0];before=frames[start-1];after=frames[end]
        new=set(after['seen'])-set(before['seen'])
        positives=[x['channel'] for x in batch if x['response'].get('measure_result') in ('direction','near')]
        negatives=[x['channel'] for x in batch if x['response'].get('measure_result')=='no_signal']
        cleared=[x['channel'] for x in batch if x['response'].get('clear_result')=='success']
        failed=[x['channel'] for x in batch if x['response'].get('clear_result')=='no_target_in_range']
        costs={k:sum(x['independent_costs'][k] for x in batch) for k in first['independent_costs']}
        q=first['position'];j=first['channel'];reason=first['reason']
        action=(f'移动{costs["move_s"]*5:.0f}米，耗时{costs["move_s"]:.1f}秒；' if costs['move_s']>1e-5 else '留在原处；')
        if first['kind']=='measure':
            action+=f'检测{channels(x["channel"] for x in batch)}，扫描{costs["measure_s"]:.0f}秒，切频{costs["switch_s"]:.0f}秒。'
        else:
            action+=f'对C{j}尝试20米范围清除，操作{costs["success_clear_s"]+costs["fail_clear_s"]:.0f}秒。'
        feedback=[]
        if new:feedback.append('新发现'+channels(new))
        if set(positives)-new:feedback.append('再次测到'+channels(set(positives)-new))
        if negatives:feedback.append('无信号'+channels(negatives))
        if cleared:feedback.append('清除成功'+channels(cleared))
        if failed:feedback.append('清除失败'+channels(failed)+'，排除本次20米范围')
        newly_absent={c['j'] for c in after['channels'] if c['status']=='absent'}-{c['j'] for c in before['channels'] if c['status']=='absent'}
        if newly_absent:feedback.append('累计证据终结'+channels(newly_absent))
        if after['complete']:feedback.append('全部频道终结，整局完成')
        why={
            'initial_1':'先到既定首点扫描20个频道，形成公开反馈。',
            'initial_2':f'第一轮后，对16个相容场景做完整续行试算，选中{selection["selected"]["id"]}；四个展示版本使用相同第二站。',
            'joint_cover_scan':'已知源服务与未知频道查漏合并排路，补足保守覆盖证据。',
            'planned_transverse_scan':'按目标可能区域长轴的垂直方向安排补测，以增加交会角；同站共享扫描。',
            'planned_clearance_scan':'利用刚完成清除的停留地点共享扫描，节省另设测点的路程。',
            'current_view':'当前地点尚未测过该频道，原规则先补一次测量；近距离并不自动表示无效。',
            'certain_here':'整个保守可能区域已被当前位置20米圆覆盖。',
            'certain_center':'保守可能区域包围半径不超过20米，去圆心可保证覆盖。',
            'single_center_try':'原规则对20—30米包围半径允许中心试清一次，失败后保留剩余区域。',
            'certified_multi_clear':'整个可行多边形已被2或3个20米圆覆盖；按访问顺序尝试，成功后立即停止。',
            'finite_cell_clear':'原控制器的局部动作上限触发，访问剩余可行小格。',
            'refined_shared_scan':'比较两侧测点及是否扫未知频道，以相容场景的完整续行时间选择。'
        }.get(reason,'继续当前服务队列。')
        d=decisions.get(start-1)
        if d and 'options' in d:
            why+=f' 本次第一批试算选择{d["chosen"]}，预测比原动作省{d["predicted_saving_s"]:.1f}秒。'
            check=d.get('recheck',{})
            if check.get('performed'):
                why+=f' 独立8场景复查{check["proposed"]}：均值省{check["mean_saving_s"]:.1f}秒，因此'+('采纳。' if check['accepted'] else '保留原动作。')
        focus=(cleared or failed or sorted(new) or positives or [j])[0]
        return {'start':start,'end':end,'title':names.get(reason,reason),
                'action':'动作：'+action,'feedback':'反馈：'+'；'.join(feedback)+'。','why':'理由：'+why,'focus':focus}
    groups=[];start=1
    for i in range(1,len(actions)):
        x,y=actions[i-1],actions[i]
        same=(x['kind']==y['kind']=='measure' and x['reason']==y['reason'] and math.dist(x['position'],y['position'])<1e-6)
        # 试算发生处单独分段，以免把该次决策的理由隐去。
        if not same or i in decisions:
            groups.append(detail(start,i));start=i+1
    groups.append(detail(start,len(actions)))
    data={'case':case,'frames':frames,'groups':groups,'single':[detail(i,i) for i in range(1,len(actions)+1)],
          'actions':[{'kind':r['kind'],'channel':r['channel'],'position':r['position'],
                      'result':r['response'].get('measure_result',r['response'].get('clear_result')),
                      'bearing':r['response'].get('svd_deg')} for r in actions],
          'options':[{'name':c['id'],'q':c['q'],'channels':len(c['channels']),'mean':c['mean_s']/60,
                      'selected':c['id']==selection['selected']['id']} for c in selection['candidates']],
          'first_end':20}
    lines=[f'# {LABELS[mode]}：逐步回放','',f'种子{case["seed"]}，一次抽取，不重抽。{len(case["sources"])}个源，{len(actions)}条动作，{result["total_s"]/60:.6f}分钟全清。',
           '真实位置只供事后讲解；所有决策和几何更新只读取已经得到的反馈。±1°方向误差使用±1.005°的保守取整余量。','']
    for item in groups:
        lines.extend([f'## 动作{item["start"]}—{item["end"]}：{item["title"]}',
                      f'累计{frames[item["end"]]["time"]/60:.3f}分钟。',item['action'],item['feedback'],item['why'],''])
    (directory/'WALKTHROUGH.md').write_text('\n\n'.join(lines),encoding='utf-8')
    return data,{'actions':len(actions),'groups':len(groups),'replayed':verified,'total_s':result['total_s']}


def rounded(x):
    if isinstance(x,float):return round(x,2)
    if isinstance(x,dict):return {k:rounded(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)):return [rounded(v) for v in x]
    return x


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
    root=HERE/'runs/random_audit';case=json.loads((root/'cases.json').read_text())[0]
    selection=json.loads((root/case['name']/'selection.json').read_text())
    variants={};receipts={}
    for mode in LABELS:variants[mode],receipts[mode]=build_variant(root,case,mode,selection)
    compact=rounded({'variants':variants})
    pool=[];index={}
    for data in compact['variants'].values():
        for frame in data['frames']:
            ids=[]
            for channel in frame['channels']:
                key=json.dumps(channel,ensure_ascii=False,separators=(',',':'))
                if key not in index:index[key]=len(pool);pool.append(channel)
                ids.append(index[key])
            frame['channels']=ids
    compact['channelPool']=pool
    payload=json.dumps(compact,ensure_ascii=False,separators=(',',':')).replace('</',r'<\/')
    html=(HERE/'replay-template.html').read_text(encoding='utf-8').replace('__REPLAY_DATA__',payload)
    assert len(html.encode())<1_000_000
    assert '__REPLAY_DATA__' not in html
    args.out.write_text(html,encoding='utf-8')
    actual_bytes=args.out.stat().st_size
    assert actual_bytes<1_000_000
    a.base.dump(root/'replay_receipt.json',{'file':str(args.out),'bytes':actual_bytes,'variants':receipts})
    print(json.dumps({'bytes':actual_bytes,'variants':receipts},ensure_ascii=False))


if __name__=='__main__':main()
