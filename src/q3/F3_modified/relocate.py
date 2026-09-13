"""A后的一个有界一维几何算子；不修改冻结的A/F3源码。"""
import copy
import math
from collections import Counter
from contextlib import contextmanager
import light_route as lr

BISECTIONS=10


def relocation(state,jobs,check=lambda:None):
    eligible=not any(c.status=='found' for c in state.channels.values()) and any(c.status=='unknown' for c in state.channels.values())
    if not eligible:return jobs,dict(eligible=False,events=[],attempts=0,certificate_calls=0)
    route=copy.deepcopy(jobs);before=copy.deepcopy(jobs);events=[];attempts=0;calls=0
    proof=lr.proof_function(lr.cr.common_negative_circles(state),check)
    def cert(route):
        nonlocal calls
        calls+=1
        return proof(route)
    assert cert(route),'relocation original plan has no complete certificate'
    forbidden={tuple(state.position)}
    for c in state.channels.values():
        if c.status=='unknown':forbidden.update(tuple(q) for q in c.measured)
    for index,job in enumerate(route):
        check()
        if job['kind']!='scan':continue
        attempts+=1
        old=tuple(job['position']);target=tuple(state.position if index==0 else route[index-1]['position'])
        if math.dist(old,target)<1e-3:continue
        forbidden_here=list(forbidden)+[tuple(j['position']) for i,j in enumerate(route) if i!=index]
        lo,hi=0.,1.;best=old
        before_m=lr.cr.route_length(state.position,route)
        for _ in range(BISECTIONS):
            check();t=(lo+hi)/2
            q=tuple(old[k]+t*(target[k]-old[k]) for k in (0,1))
            if any(math.dist(q,p)<1e-3 for p in forbidden_here):hi=t;continue
            job['position']=q
            if cert(route):lo=t;best=q
            else:hi=t
        job['position']=best
        after_m=lr.cr.route_length(state.position,route)
        if after_m<before_m-1e-6 and math.dist(old,best)>1e-3:
            assert cert(route),'relocation final coordinates lost certificate'
            events.append(dict(index=index,old_position=old,new_position=best,toward=target,fraction=lo,
                displacement_m=math.dist(old,best),before_m=before_m,after_m=after_m,saving_s=(before_m-after_m)/5))
        else:job['position']=old
    assert len(route)==len(before)
    assert all({k:v for k,v in x.items() if k!='position'}=={k:v for k,v in y.items() if k!='position'} for x,y in zip(before,route))
    assert cert(route),'relocation final plan lost coverage'
    after_m=lr.cr.route_length(state.position,route);before_m=lr.cr.route_length(state.position,before)
    assert after_m<=before_m+1e-6
    return route,dict(eligible=True,at_action=state.actions,position=state.position,events=events,attempts=attempts,
        certificate_calls=calls,before_route=before,after_route=copy.deepcopy(route),before_m=before_m,after_m=after_m,
        nominal_saving_s=(before_m-after_m)/5)


@contextmanager
def relocation_context(context,enabled=True):
    context.relocation_counts={'online':Counter(),'rollout':Counter()};context.relocation_plans=[]
    with lr.route_context(context):
        base=lr.cr.covering_route
        def routed(state,services):
            route,info=base(state,services)
            if not enabled:return route,info
            updated,record=relocation(state,route,context.check)
            if record['eligible']:
                scope='rollout' if lr.SIMULATING.get() else 'online'
                counts=context.relocation_counts[scope];counts['plans']+=1
                counts['attempts']+=record['attempts'];counts['accepted']+=len(record['events'])
                counts['certificate_calls']+=record['certificate_calls']
                if scope=='online':context.relocation_plans.append(record)
                info=dict(info,planned_jobs=updated,planned_route_m=record['after_m'],
                    planned_travel_unknown_scan_s=lr.nominal(state.position,updated,record.get('unknown',sum(c.status=='unknown' for c in state.channels.values()))),relocated=True)
            return updated,info
        lr.cr.covering_route=routed
        try:yield context
        finally:lr.cr.covering_route=base


class RelocationPolicy(lr.LightPolicy):
    def metadata(self):
        result=super().metadata();context=lr.CURRENT.get()
        if context is not None and hasattr(context,'relocation_counts'):
            result['relocation']=dict(bisections=BISECTIONS,counts={k:dict(v) for k,v in context.relocation_counts.items()},
                online_plans=context.relocation_plans)
        return result
