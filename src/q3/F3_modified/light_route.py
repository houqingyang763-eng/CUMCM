"""已批准的两个轻量路线算子；真实状态只读，F3源文件不改。"""
import copy
import math
import sys
import time
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

Q3=Path(__file__).resolve().parents[2]
ROOT=Q3.parents[1]
sys.path.insert(0,str(Q3/'refinement'))
from refined import RefinedPolicy
from posterior import a
import covering_route as cr

ORIGINAL_ROUTE=cr.covering_route
CURRENT=ContextVar('light_route_context',default=None)
SIMULATING=ContextVar('light_route_simulating',default=False)
MODES={'A':(True,False),'B':(False,True),'AB':(True,True),'OFF':(False,False)}


def nominal(start,route,unknown):
    return cr.route_length(start,route)/5+6*unknown*sum(bool(j.get('scan_unknown')) for j in route)


def proof_function(past,check):
    cache={}
    def certified(route):
        check()
        circles=list(past)+[(tuple(j['position']),1000.) for j in route if j.get('scan_unknown')]
        key=tuple(sorted(set((tuple(q),r) for q,r in circles)))
        if key not in cache: cache[key]=cr.coverage_certificate(key)
        p=cache[key]
        return p.complete and p.rational_verified
    return certified


def transfer(start,jobs,unknown,certified,check=lambda:None):
    route=copy.deepcopy(jobs); events=[]; attempts=0
    for identity in [j['_light_id'] for j in jobs if j['kind']=='scan']:
        check(); attempts+=1
        index=next(i for i,j in enumerate(route) if j['_light_id']==identity)
        trial=copy.deepcopy(route); removed=trial.pop(index)
        added=[]
        for job in trial:
            if job['kind']=='service' and not job.get('scan_unknown'):
                job['scan_unknown']=True; added.append(job['_light_id'])
        if not certified(trial): continue
        for identifier in reversed(added):
            job=next(j for j in trial if j['_light_id']==identifier)
            job['scan_unknown']=False
            if not certified(trial): job['scan_unknown']=True
        before,after=nominal(start,route,unknown),nominal(start,trial,unknown)
        if after < before-1e-7:
            kept=[j['_light_id'] for j in trial if j['_light_id'] in added and j.get('scan_unknown')]
            events.append(dict(removed=identity,position=removed['position'],added_service_labels=kept,
                               before_s=before,after_s=after))
            route=trial
    return route,dict(attempts=attempts,accepted=len(events),events=events)


def reinsert(start,jobs,check=lambda:None):
    route=copy.deepcopy(jobs); events=[]; attempts=0
    for identity in [j['_light_id'] for j in jobs if j['kind']=='scan']:
        check(); attempts+=1
        index=next(i for i,j in enumerate(route) if j['_light_id']==identity)
        trial=list(route); job=trial.pop(index)
        _,new_index=cr.insertion(start,trial,job['position'])
        trial.insert(new_index,job)
        before,after=cr.route_length(start,route),cr.route_length(start,trial)
        if after < before-1e-7:
            events.append(dict(station=identity,from_index=index,to_index=new_index,before_m=before,after_m=after))
            route=trial
    return route,dict(attempts=attempts,accepted=len(events),events=events)


def process(state,jobs,mode,check=lambda:None):
    switch_a,switch_b=MODES[mode]
    if not switch_a and not switch_b: return jobs,{}
    unknown=sum(c.status=='unknown' for c in state.channels.values())
    route=[dict(j,_light_id=i) for i,j in enumerate(jobs)]
    before=copy.deepcopy(route)
    empty=dict(attempts=0,accepted=0,events=[])
    ar,br=copy.deepcopy(empty),copy.deepcopy(empty)
    if switch_a and unknown:
        cert=proof_function(cr.common_negative_circles(state),check)
        assert cert(route),'original route has no complete continuous certificate'
        route,ar=transfer(state.position,route,unknown,cert,check)
        assert cert(route),'A lost conditional coverage'
    if switch_b:
        route,br=reinsert(state.position,route,check)
    assert [j['_light_id'] for j in route if j['kind']=='service']==[j['_light_id'] for j in before if j['kind']=='service']
    assert nominal(state.position,route,unknown)<=nominal(state.position,before,unknown)+1e-6
    record=dict(at_action=state.actions,position=state.position,unknown=unknown,A=ar,B=br,
        before_nominal_s=nominal(state.position,before,unknown),after_nominal_s=nominal(state.position,route,unknown),
        before_route=before,after_route=copy.deepcopy(route))
    for j in route: j.pop('_light_id')
    return route,record


class RunContext:
    def __init__(self,mode,deadline=math.inf):
        self.mode=mode;self.deadline=deadline
        self.counts={'online':Counter(),'rollout':Counter()}
        self.online_plans=[]
        self.rollout_calls=0;self.rollout_choose_calls=0
    def check(self):
        if time.perf_counter()>=self.deadline: raise TimeoutError('lightweight accounted wall limit')


def routed(state,service_jobs):
    context=CURRENT.get()
    if context is None or context.mode=='OFF': return ORIGINAL_ROUTE(state,service_jobs)
    context.check()
    route,info=ORIGINAL_ROUTE(state,service_jobs)
    updated,record=process(state,route,context.mode,context.check)
    kind='rollout' if SIMULATING.get() else 'online'
    counts=context.counts[kind]; counts['plans']+=1
    for label in ('A','B'):
        counts[label+'_attempts']+=record[label]['attempts'];counts[label+'_accepted']+=record[label]['accepted']
    if kind=='online': context.online_plans.append(record)
    info=dict(info,planned_jobs=updated,planned_route_m=cr.route_length(state.position,updated),
              planned_unknown_stops=sum(bool(j.get('scan_unknown')) for j in updated),
              planned_travel_unknown_scan_s=record['after_nominal_s'],light_mode=context.mode)
    return updated,info


@contextmanager
def route_context(context):
    previous=cr.covering_route; token=CURRENT.set(context)
    cr.covering_route=routed
    try: yield context
    finally:
        cr.covering_route=previous;CURRENT.reset(token)


class LightPolicy(RefinedPolicy):
    def __init__(self,selected=None): super().__init__(selected,level=3,samples=4)
    def choose(self,state):
        context=CURRENT.get()
        if context:
            context.check()
            if SIMULATING.get(): context.rollout_choose_calls+=1
        return super().choose(state)
    def simulate(self,state,world,option,original):
        context=CURRENT.get()
        if context:context.check();context.rollout_calls+=1
        token=SIMULATING.set(True)
        try:return super().simulate(state,world,option,original)
        finally:SIMULATING.reset(token)
    def metadata(self):
        result=super().metadata();context=CURRENT.get()
        if context:
            result['lightweight']=dict(mode=context.mode,counts={k:dict(v) for k,v in context.counts.items()},
                online_plans=context.online_plans,rollout_calls=context.rollout_calls,
                rollout_choose_calls=context.rollout_choose_calls)
        return result
