"""仅审查用户指出的演示步骤；不修改实际策略或历史轨迹。"""
import copy
import itertools
import json
import math
from pathlib import Path
import numpy as np
import adaptive as a
import geometry as g
from patrol import major_axis

OUT=Path(__file__).resolve().parent/'demonstration'


def area(poly):
    return abs(sum(g.cross(x,y) for x,y in zip(poly,poly[1:]+poly[:1])))/2 if poly else 0


def main():
    raw=json.loads((OUT/'replay.json').read_text())
    actions=raw['actions'];frames=raw['frames'];case=a.Scenario.from_dict(raw['case'])
    sources={s.channel:s for s in case.sources}
    states=[a.CoverageInformationState()]
    for action in actions:
        s=copy.deepcopy(states[-1]);s.update(action,action['response']);states.append(s)
    def geometry_pair(channel,steps):
        s=a.CoverageInformationState()
        for step in steps:
            action=actions[step-1];assert action['channel']==channel
            s.update(action,action['response'])
        c=s.channels[channel]
        return {'steps':steps,'radius':c.circle()[1],'area':area(c.support())}
    measurements=[]
    for row in actions:
        i=row['step'];j=row['channel']
        if row['kind']!='measure':continue
        before=states[i-1].channels[j];after=states[i].channels[j]
        prior=[r for r in actions[:i-1] if r['channel']==j and r['kind']=='measure']
        dominated=[]
        if before.status=='found':
            q=row['position'];poly=before.support()
            for prior_row in prior:
                if prior_row['response'].get('measure_result')!='no_signal':continue
                p=prior_row['position']
                margin=min(sum((q[k]-x[k])**2-(p[k]-x[k])**2 for k in range(2)) for x in poly)
                if margin>=1e-4:dominated.append(prior_row['step'])
        measurements.append({'step':i,'channel':j,'position':row['position'],'result':row['response']['measure_result'],
            'radius_before':before.circle()[1] if before.status=='found' else None,
            'radius_after':after.circle()[1] if after.status=='found' else None,
            'area_before':area(before.support()) if before.status=='found' else None,
            'area_after':area(after.support()) if after.status=='found' else None,
            'nearest_same_channel_distance':min((math.dist(row['position'],r['position']) for r in prior),default=None),
            'provably_no_signal_by_prior_step':dominated})
    c4_steps=[r['step'] for r in actions if r['channel']==4 and r['response'].get('measure_result')=='direction']
    c4pairs=[geometry_pair(4,[c4_steps[0],step]) for step in c4_steps[1:]]

    # Certify multi-clear coverage by partitioning convex support into disjoint slabs.
    # Every slab is convex and contained in a radius20 disk if all its vertices are.
    def multi_clear(state,j):
        c=state.channels[j];poly=c.support();axis=major_axis(poly)
        values=[g.dot(p,axis) for p in poly];lo,hi=min(values),max(values)
        plans=[]
        for k in (2,3):
            centers=[];radii=[];slabs=[]
            for t in range(k):
                left=lo+(hi-lo)*t/k;right=lo+(hi-lo)*(t+1)/k
                part=g.clip(g.clip(poly,axis,right),g.mul(axis,-1),-left)
                center,radius=g.enclosing_circle(part)
                centers.append(center);radii.append(radius);slabs.append(part)
            vertex_radii=[max(math.dist(center,p) for p in part) for center,part in zip(centers,slabs)]
            certified=all(r<=20-1e-6 for r in vertex_radii)
            if not certified:
                plans.append({'k':k,'radii':radii,'certified':False});continue
            order=min(itertools.permutations(range(k)),key=lambda order:math.dist(state.position,centers[order[0]])+sum(math.dist(centers[x],centers[y]) for x,y in zip(order,order[1:])))
            q=state.position;elapsed=0.;attempts=[]
            for index in order:
                center=centers[index];elapsed+=math.dist(q,center)/5
                success=math.dist(center,sources[j].position)<=20
                elapsed+=5 if success else 3
                attempts.append({'position':center,'success':success,'elapsed_s':elapsed})
                if success:break
                q=center
            worst=math.dist(state.position,centers[order[0]])/5+sum(math.dist(centers[x],centers[y])/5 for x,y in zip(order,order[1:]))+3*(k-1)+5
            plans.append({'k':k,'radii':radii,'checked_vertex_radii':vertex_radii,'certified':True,'centers':centers,'order':order,
                          'worst_completion_s':worst,'actual_attempts':attempts,'actual_completion_s':elapsed})
        return plans
    multi=multi_clear(states[86],20)
    # Alternative transverse point already in the original local geometry generator.
    state=states[74];center,radius=state.channels[20].circle();normal=major_axis(state.channels[20].support());normal=(-normal[1],normal[0])
    offset=min(300,max(30,radius/2));points=[g.add(center,g.mul(normal,sign*offset)) for sign in (-1,1)]
    actual=tuple(actions[74]['position']);alternative=max(points,key=lambda q:math.dist(q,actual))
    distance=math.dist(state.position,actual);left=(state.position[0]-distance,state.position[1])
    rng=np.random.default_rng(291012);angles=rng.uniform(0,2*math.pi,200000);r=1800*np.sqrt(rng.random(200000));xy=np.column_stack([r*np.cos(angles),r*np.sin(angles)])
    unknown=[c for c in state.channels.values() if c.status=='unknown']
    histories=[{tuple(p) for p,result,_ in c.observations if result=='no_signal'} for c in unknown]
    common=set.intersection(*histories)
    uncovered=np.ones(len(xy),bool)
    for p in common:uncovered&=np.linalg.norm(xy-np.array(p),axis=1)>1000
    def probe(q):
        policy=a.PatrolPolicy(a.CONFIG);policy.phase='service';policy.start_station(state,q,'diagnostic',priority=20,scan_unknown=True)
        env=a.LocalEnvironment(case);env.position=state.position;env.channel=state.measuring_channel;env.virtual_time_s=state.virtual_time_s
        env.cleared={j for j,c in state.channels.items() if c.status=='cleared'}
        s=copy.deepcopy(state);found_before=set(s.ever_seen)
        replies=[]
        while policy.station_channels:
            action=policy.station_action(s)
            if action is None:break
            reply=env.act(action);s.update(action,reply)
            a.audit_state(s,env)
            replies.append((action['channel'],reply['measure_result']))
        visible=[j for j,src in sources.items() if j not in env.cleared and math.dist(q,src.position)<=src.radius]
        mask=np.linalg.norm(xy-np.array(q),axis=1)<=1000
        return {'q':q,'radius_from_origin':math.hypot(*q),'move_s':math.dist(state.position,q)/5,
                'visible_true_channels':visible,'new_found':sorted(set(s.ever_seen)-found_before),'replies':replies,
                'c20_radius_after':s.channels[20].circle()[1],
                'radii_after':{j:c.circle()[1] for j,c in s.channels.items() if c.status=='found'},
                'area_fraction_r1000':float(mask.mean()),'new_area_fraction_r1000':float((mask&uncovered).mean()),
                'batch_elapsed_s':env.virtual_time_s-state.virtual_time_s}
    probes={name:probe(q) for name,q in [('actual',actual),('reflected',alternative),('equal_distance_left',left)]}
    c10=[]
    for i in (75,87,92,95,98,100,102):
        state=states[i-1];q=tuple(actions[i-1]['position']);c=state.channels[10]
        c10.append({'step':i,'status_before':c.status,'q':q,'detectable_true':math.dist(q,sources[10].position)<=sources[10].radius,'distance_true':math.dist(q,sources[10].position),'source_radius_true':sources[10].radius,'reason':actions[i-1]['reason']})
    disk={'r':34.72,'area':math.pi*34.72**2,'three_clear_disk_area_upper':3*math.pi*20**2}
    result={'measurements':measurements,'c4_direction_steps':c4_steps,'c4_first_last_pairs':c4pairs,
            'c20_multiclear_at86':multi,'c4_multiclear_at56':multi_clear(states[56],4),
            'c20_original_87_to91_s':sum(sum(r['independent_costs'].values()) for r in actions[86:91]),
            'step75_alternatives':probes,'c10_omission':c10,'disk_area_warning':disk}
    a.base.dump(OUT/'review_findings.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='measurements'},ensure_ascii=False,indent=2))
    print('C3:',json.dumps([x for x in measurements if x['channel']==3 and x['step']<60]))
    print('ZERO GEOMETRY:',json.dumps([x for x in measurements if x['radius_before'] is not None and x['area_before']==x['area_after'] and 45<=x['step']<=101]))


if __name__=='__main__':main()
