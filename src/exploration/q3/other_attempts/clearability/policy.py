"""用户指定陡峭效用：测量突破、认证多次清除和逐频道查漏。"""
import copy
import hashlib
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'refinement'))
from posterior import a, g, pool
from refined import clearing_plans, dominated_negative
from patrol import major_axis
from covering_route import covering_route


def utility(r):
    if r<=20:return 1.
    z=(r-35)/3.5
    return (1+math.exp(-15/3.5))*math.exp(-z)/(1+math.exp(-z)) if z>=0 else (1+math.exp(-15/3.5))/(1+math.exp(z))


def reflect(q,origin,other):
    v=g.sub(other,origin);d=g.dot(v,v)
    if d<1e-9:return q
    foot=g.add(origin,g.mul(v,g.dot(g.sub(q,origin),v)/d))
    return g.sub(g.mul(foot,2),q)


class UtilityPolicy(a.AdaptivePolicy):
    def __init__(self,selected,level=1):
        super().__init__(selected)
        self.level=level
        self.predictions={};self.clouds={};self.choices=[];self.skips=[]
        self.multi=None;self.explicit_channels=None;self.priority=None
        self.initial_station=False;self.failures=[];self.view_cache={}

    def metadata(self):
        return dict(super().metadata(),utility_level=self.level,utility_choices=self.choices,
                    utility_skips=self.skips,prediction_failures=self.failures,
                    utility_spec={'midpoint_m':35,'scale_m':3.5,'near_repeat_m':30,'breakthrough':.8})

    def key(self,c):
        return (c.channel,tuple(c.observations),tuple(c.exclusions))

    def cloud(self,state,c):
        key=self.key(c)
        if key not in self.clouds:
            seed=int.from_bytes(hashlib.sha256(repr(key).encode()).digest()[:8],'big')
            rng=random.Random(seed)
            try:
                xs,rs,ws,_=pool(state,c,rng,256)
                out=[]
                for i in rng.choices(range(len(xs)),ws,k=12):
                    lo,hi=rs[i];out.append((xs[i],rng.uniform(lo,hi)))
                self.clouds[key]=out
            except ValueError as exc:
                self.failures.append({'at_action':state.actions,'channel':c.channel,'error':str(exc)})
                self.clouds[key]=None
        return self.clouds[key]

    def predict(self,state,c,q):
        q=tuple(q);u=utility(c.circle()[1]);key=(self.key(c),q)
        if key in self.predictions:return self.predictions[key]
        if q in c.measured or dominated_negative(c,q):return {'mean_u':u,'gain':0.,'certain_redundant':True}
        cloud=self.cloud(state,c)
        if cloud is None:return {'mean_u':u,'gain':None,'fallback':True}
        values=[]
        for x,r in cloud:
            distance=math.dist(x,q)
            for error in (-math.sqrt(3/5),0.,math.sqrt(3/5)):
                weight=4/9 if error==0 else 5/18
                if distance>r:value=u
                elif distance<=5:value=1.
                else:
                    angle=round((math.degrees(math.atan2(x[1]-q[1],x[0]-q[0]))+error)%360,2)
                    poly=g.wedge(c.support(),q,angle)
                    poly=g.intersect_disk_outer(poly,q,1500)
                    value=utility(g.enclosing_circle(poly)[1]) if poly else u
                values.append(weight*value/len(cloud))
        mean=sum(values)
        out={'mean_u':mean,'gain':max(0.,mean-u),'before_u':u}
        self.predictions[key]=out
        return out

    def candidate_points(self,state,c):
        center,r=c.circle();axis=major_axis(c.support());normal=(-axis[1],axis[0])
        old=super().local_point(state,c)
        points=[old,g.sub(g.mul(center,2),old)]
        if self.level>=2:
            for dist in (100.,300.):
                for sign in (-1,1):
                    points.append(g.add(center,g.mul(normal,sign*dist)))
                    points.append(g.add(state.position,g.mul(normal,sign*dist)))
            nearby=sorted([x.circle()[0] for x in state.channels.values() if x.first is not None and x.channel!=c.channel],
                          key=lambda q:math.dist(q,center))[:4]
            for other in nearby:
                points.extend([other,g.mul(g.add(center,other),.5),reflect(old,center,other)])
            points.append(reflect(old,state.position,center))
        return list(dict.fromkeys(tuple(q) for q in points if math.hypot(*q)<5000 and q not in c.measured))

    def best_view(self,state,c):
        key=(state.actions,c.channel)
        if key in self.view_cache:return self.view_cache[key]
        records=[]
        for q in self.candidate_points(state,c):
            pred=self.predict(state,c,q)
            if pred.get('gain') is None:continue
            seconds=math.dist(state.position,q)/5+5+(state.measuring_channel!=c.channel)
            records.append(dict(q=q,seconds=seconds,rate=pred['gain']/seconds,**pred))
        best=max(records,key=lambda r:(r['rate'],-r['seconds'])) if records else {'q':super().local_point(state,c),'rate':0.,'gain':None}
        self.view_cache[key]=(best,records)
        return best,records

    def local_point(self,state,c):
        return self.best_view(state,c)[0]['q'] if self.level>=2 else super().local_point(state,c)

    def worthwhile(self,state,c,q,force=False):
        pred=self.predict(state,c,q)
        if pred.get('certain_redundant'):return False,'provable_negative_or_same_location',pred
        if force or pred['gain'] is None:return True,'target_measurement_or_sampling_fallback',pred
        if any(math.dist(p,q)<30 for p,result,_ in c.observations if result=='direction') and pred['mean_u']<.8:
            return False,'near_repeat_without_breakthrough',pred
        best,_=self.best_view(state,c)
        rate=pred['gain']/(5+(state.measuring_channel!=c.channel))
        keep=pred['gain']>1e-8 and rate>=best['rate']
        return keep,'current_vs_better_view',dict(pred,rate=rate,alternative_rate=best['rate'])

    def start_station(self,state,q,reason,priority=None,initial=False,scan_unknown=True):
        super().start_station(state,q,reason,priority,initial,scan_unknown)
        self.priority=priority;self.initial_station=initial

    def station_action(self,state):
        while self.station_channels:
            j=self.station_channels.pop(0);c=state.channels[j]
            if c.status in ('cleared','absent') or self.station in c.measured:continue
            if not self.initial_station:
                if c.status=='unknown' and self.explicit_channels is not None and j not in self.explicit_channels:continue
                if c.status=='found':
                    if c.circle()[1]<=20:continue
                    keep,why,pred=self.worthwhile(state,c,self.station,force=j==self.priority)
                    record={'at_action':state.actions,'channel':j,'q':self.station,'why':why,**pred}
                    if not keep:self.skips.append(record);continue
                    self.choices.append(record)
            return self.action('measure',self.station,j,self.station_reason)
        self.station=None;self.explicit_channels=None
        return None

    def choose_joint(self,state):
        for c in state.channels.values():
            if c.status=='found' and all(math.dist(state.position,p)<=20-1e-6 for p in c.support()):
                return self.action('clear',state.position,c.channel,'certain_here')
        if self.multi:
            j=self.multi['channel']
            if state.channels[j].status=='cleared':
                self.after_arrival_scan=(state.position,self.multi['scan_unknown'],j)
                self.multi=None
            else:
                if not self.multi['points']:raise AssertionError('certified cover exhausted')
                return self.action('clear',self.multi['points'].pop(0),j,'utility_certified_multi_clear')
        if self.station is not None:
            action=self.station_action(state)
            if action:return action
        if self.after_arrival_scan:
            q,scan_unknown,j=self.after_arrival_scan;self.after_arrival_scan=None
            self.start_station(state,q,'utility_clearance_scan',scan_unknown=scan_unknown)
            action=self.station_action(state)
            if action:return action
        found=[c for c in state.channels.values() if c.status=='found']
        self.phase='service' if found else 'completion'
        jobs=[];clears={}
        for c in found:
            center,r=c.circle()
            plans=clearing_plans(state,c) if r>20 else []
            if plans:
                plan=min(plans,key=lambda p:p['worst_local_s']);clears[c.channel]=plan
                q=plan['points'][0]
            else:q=center if r<=20 else self.local_point(state,c)
            jobs.append({'kind':'service','channel':c.channel,'position':q})
        if self.level>=3:
            from channel_route import channel_route
            route,info=channel_route(state,jobs)
        else:route,info=covering_route(state,jobs)
        self.decision_data=info
        if not route:raise AssertionError('incomplete state without plan')
        job=route[0];q=tuple(job['position']);self.explicit_channels=job.get('channels')
        if job['kind']=='scan':
            self.start_station(state,q,'channel_cover_scan',scan_unknown=True)
        else:
            j=job['channel'];c=state.channels[j];self.target=j
            scan_unknown=job.get('scan_unknown',False)
            if c.circle()[1]<=20:
                self.after_arrival_scan=(q,scan_unknown,j)
                return self.action('clear',q,j,'certain_center')
            if j in clears:
                plan=clears[j]
                self.multi={'channel':j,'points':list(plan['points'][1:]),'scan_unknown':scan_unknown}
                self.choices.append({'at_action':state.actions,'channel':j,'why':'certified_cover','plan':plan})
                return self.action('clear',q,j,'utility_certified_multi_clear')
            keep,_,_=self.worthwhile(state,c,state.position)
            if keep and state.position not in c.measured:
                return self.action('measure',state.position,j,'utility_current_view')
            count=self.local_counts.get(j,0);self.local_counts[j]=count+1
            if count>=16:
                cells=c.possible_cells();q=min(cells,key=lambda x:math.dist(state.position,x['position']))['position']
                return self.action('clear',q,j,'finite_cell_clear')
            if dominated_negative(c,q):q=self.best_view(state,c)[0]['q']
            self.start_station(state,q,'utility_transverse_scan',priority=j,scan_unknown=scan_unknown)
        action=self.station_action(state)
        if action:return action
        raise AssertionError('empty proposed station: no useful primary or unknown scan')
