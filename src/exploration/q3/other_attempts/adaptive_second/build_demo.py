"""由真实执行日志生成逐步图解；图中真值与算法可见状态明确分开。"""
import json
import math
from pathlib import Path
import adaptive as a
from diagnose import replay as audit_replay

HERE=Path(__file__).resolve().parent
OUT=HERE/'demonstration'
VIS=OUT/'patrol-replay.html'


def chans(js):
    js=sorted(set(js))
    if not js:
        return '无'
    if len(js)>3 and js==list(range(js[0],js[-1]+1)):
        return f'C{js[0]}—C{js[-1]}'
    return '、'.join(f'C{j}' for j in js)


def main():
    raw=json.loads((OUT/'replay.json').read_text())
    actions=raw['actions'];frames=raw['frames'];selection=raw['selection']
    chosen=next(c for c in selection['candidates'] if c['id']==selection['position'])
    fixed=next(c for c in selection['candidates'] if c['id']==selection['fixed'])
    names={'initial_1':'第一轮搜索','initial_2':'自适应第二轮','joint_cover_scan':'搜索未知目标',
           'planned_transverse_scan':'横向补测定位','planned_clearance_scan':'清除地点共享扫描',
           'current_view':'利用当前位置补测','certain_here':'原地保证清除','certain_center':'到定位中心清除',
           'single_center_try':'小范围内尝试清除','finite_cell_clear':'剩余可行区域逐格清除'}
    def explain(start,end):
        batch=actions[start-1:end];first=batch[0];last=batch[-1];before=frames[start-1];after=frames[end]
        new=sorted(set(after['seen'])-set(before['seen']))
        cleared=[r['channel'] for r in batch if r['response'].get('clear_result')=='success']
        failed=[r['channel'] for r in batch if r['response'].get('clear_result')=='no_target_in_range']
        detected=[r['channel'] for r in batch if r['response'].get('measure_result') in ('direction','near')]
        negatives=[r['channel'] for r in batch if r['response'].get('measure_result')=='no_signal']
        old_abs={c['j'] for c in before['channels'] if c['status']=='absent'}
        absent=[c['j'] for c in after['channels'] if c['status']=='absent' and c['j'] not in old_abs]
        move=sum(r['independent_costs']['move_s'] for r in batch)
        scan=sum(r['independent_costs']['measure_s'] for r in batch)
        switch=sum(r['independent_costs']['switch_s'] for r in batch)
        operation=sum(r['independent_costs']['success_clear_s']+r['independent_costs']['fail_clear_s'] for r in batch)
        q=first['position']
        verb=(f'移动{move*5:.0f}米（{move:.1f}秒）到({q[0]:.0f}, {q[1]:.0f})米；' if move>.001 else '留在当前位置；')
        if first['kind']=='measure':
            verb+=f'检测{chans([r["channel"] for r in batch])}，检测{scan:.0f}秒、切频{switch:.0f}秒。'
        else:
            verb+=f'对C{first["channel"]}启动20米内光学定位与清除，操作{operation:.0f}秒。'
        parts=[]
        if new:parts.append('新发现 '+chans(new))
        repeated=sorted(set(detected)-set(new))
        if repeated:parts.append('再次测到 '+chans(repeated))
        if negatives:parts.append('无信号 '+chans(negatives))
        if cleared:parts.append('成功清除 '+chans(cleared))
        if failed:parts.append('清除失败 '+chans(failed)+'，从可能区域排除本次20米范围')
        if absent:parts.append('累计证据确认不存在 '+chans(absent))
        if len(batch)==1 and last['response'].get('measure_result')=='direction':
            parts.append(f'测向角{last["response"]["svd_deg"]:.2f}°，用±1°约束收缩可能范围')
        if after['complete']:parts.append('全部目标清除且所有频道均已终结，任务结束')
        r=first['reason'];target=first.get('target')
        why={
            'initial_1':'首点沿用当前方案，先完整扫描尚未终结的频道，为下一步提供反馈。',
            'initial_2':f'首轮后用16个相容场景比较候选的完整后续耗时，选中{chosen["id"].split("_")[0].upper()}；预计剩余{chosen["mean_s"]/60:.2f}分钟，原固定点为{fixed["mean_s"]/60:.2f}分钟。这是估计，不是实际未来。',
            'joint_cover_scan':'该点用于补足未知频道的覆盖缺口，并与已知目标的服务点合并排路；沿途排查，减少末尾单独绕行。',
            'planned_transverse_scan':f'先服务C{target}：当前位置判断还不足以可靠清除，按可能区域长轴的垂直方向生成测点，再与查漏任务合并排路；到站共享测量。',
            'planned_clearance_scan':'机器狗已到清除位置，利用这个停点执行已安排的共享测量；测量仍计时，但不用另跑一趟。',
            'current_view':f'C{first["channel"]}此前未在这里测过，先利用当前视角补测，不增加移动；收到反馈后再规划。',
            'certain_here':'该目标整个保守可能区域都已落在机器狗当前位置20米以内，因此可以原地清除。',
            'certain_center':'该目标可能区域的包围半径不超过20米，走到包围圆心即可覆盖整个可能区域。',
            'single_center_try':f'清除前定位包围半径为{(first.get("before_radius") or 0):.1f}米，处于20—30米之间；现有规则允许在中心试一次，不能保证成功。',
            'finite_cell_clear':'多轮局部动作后仍未收敛，按现有规则改为访问剩余可行小格，尝试实际清除。'
        }.get(r,'继续执行当前停点的测量队列，依据反馈更新状态。')
        focus=(cleared or failed or new or ([target] if target else []) or detected or [last['channel']])[0]
        return {'start':start,'end':end,'title':names.get(r,r)+(f' · {len(batch)}次检测' if len(batch)>1 else ''),
                'action':'动作：'+verb,'feedback':'反馈：'+'；'.join(parts)+'。','why':'理由：'+why,'focus':focus}
    groups=[]
    start=1
    for i in range(1,len(actions)):
        x,y=actions[i-1],actions[i]
        same=(x['kind']==y['kind']=='measure' and x['reason']==y['reason'] and x['phase']==y['phase'] and math.dist(x['position'],y['position'])<1e-6)
        if not same:
            groups.append(explain(start,i));start=i+1
    groups.append(explain(start,len(actions)))
    compact_actions=[{'kind':r['kind'],'position':r['position'],'channel':r['channel'],
                      'result':r['response'].get('measure_result',r['response'].get('clear_result')),
                      'bearing':r['response'].get('svd_deg')} for r in actions]
    names2={'p0':'原固定第二点','p1':'不追加初始扫描','p2':'近目标横测点1','p3':'近目标横测点2','p4':'垂直偏移候选1','p5':'垂直偏移候选2'}
    options=[{'name':c['id'].split('_')[0].upper()+' · '+names2.get(c['id'].split('_')[0],''),
              'q':c['q'],'channels':len(c['channels']),'mean':c['mean_s']/60,'selected':c['id']==chosen['id']}
             for c in selection['candidates'] if c['set']=='all']
    data={'case':raw['case'],'actions':compact_actions,'frames':frames,'groups':groups,
          'single':[explain(i,i) for i in range(1,len(actions)+1)],'options':options,
          'first_end':next(g['end'] for g in groups if actions[g['start']-1]['reason']=='initial_1')}
    def rounded(x):
        if isinstance(x,float):return round(x,2)
        if isinstance(x,dict):return {k:rounded(v) for k,v in x.items()}
        if isinstance(x,list):return [rounded(v) for v in x]
        return x
    payload=json.dumps(rounded(data),ensure_ascii=False,separators=(',',':')).replace('</',r'<\/')
    template=(HERE/'replay-template.html').read_text(encoding='utf-8')
    html=template.replace('__REPLAY_DATA__',payload)
    assert len(html.encode('utf-8'))<1_000_000
    assert '__REPLAY_DATA__' not in html
    VIS.parent.mkdir(parents=True,exist_ok=True)
    VIS.write_text(html,encoding='utf-8')
    # Full source data remain in the experiment; the inline view is display-rounded only.
    a.base.dump(OUT/'view_data.json',data)
    lines=['# 随机案例逐步讲解','',f'种子：{raw["case"]["seed"]}。一次抽样，无筛选或重抽；真实源数{len(raw["case"]["sources"])}，共{len(actions)}条动作，最终{raw["total_s"]/60:.2f}分钟全部清除。',
           '', '图中真实位置仅供讲解，算法没有读取它们。定位填色来自实际反馈的保守几何约束，不是概率热图。', '']
    for i,g in enumerate(groups,1):
        lines.extend([f'## {i}. {g["title"]}（动作{g["start"]}—{g["end"]}）',
                      f'累计{frames[g["end"]]["time"]/60:.2f}分钟。',g['action'],g['feedback'],g['why'],''])
    (OUT/'WALKTHROUGH.md').write_text('\n\n'.join(lines),encoding='utf-8')
    audited=audit_replay(OUT,a.Scenario.from_dict(raw['case']))
    a.base.dump(OUT/'visualization_receipt.json',{'file':str(VIS),'bytes':len(html.encode()),'frames':len(frames),'groups':len(groups),
                                              'actions':len(actions),'independent_replay_passed':audited,'all_clear':True})
    print(json.dumps({'file':str(VIS),'bytes':len(html.encode()),'groups':len(groups),'actions':len(actions),'first_end':data['first_end']},ensure_ascii=False))


if __name__=='__main__':
    main()
