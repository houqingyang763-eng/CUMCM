"""F3只增加可选共享补测筛选，线性/Sigmoid仅函数不同。"""
import importlib.util
import math
from pathlib import Path
import sys

spec=importlib.util.spec_from_file_location('activation_predictor_base',Path(__file__).with_name('policy.py'))
module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from refined import RefinedPolicy,dominated_negative
from posterior import a,g


def linear(r):
    return min(1.,max(0.,(1500-r)/1480))


class Predictor(module.UtilityPolicy):
    def __init__(self,fn):
        super().__init__(None,level=1);self.fn=fn

    def predict(self,state,c,q):
        q=tuple(q);u=self.fn(c.circle()[1]);key=(self.key(c),q)
        if key in self.predictions:return self.predictions[key]
        if q in c.measured or dominated_negative(c,q):return {'mean_u':u,'gain':0.}
        cloud=self.cloud(state,c)
        if cloud is None:return {'mean_u':u,'gain':None}
        values=[]
        for x,r in cloud:
            distance=math.dist(x,q)
            for error,weight in ((-math.sqrt(3/5),5/18),(0.,4/9),(math.sqrt(3/5),5/18)):
                if distance>r:value=u
                elif distance<=5:value=1.
                else:
                    angle=round((math.degrees(math.atan2(x[1]-q[1],x[0]-q[0]))+error)%360,2)
                    poly=g.intersect_disk_outer(g.wedge(c.support(),q,angle),q,1500)
                    value=self.fn(g.enclosing_circle(poly)[1]) if poly else u
                values.append(weight*value/len(cloud))
        mean=sum(values);result={'mean_u':mean,'gain':max(0.,mean-u),'before_u':u}
        self.predictions[key]=result
        return result


class ActivationOnly(RefinedPolicy):
    def __init__(self,selected,shape):
        super().__init__(selected,3,4)
        self.shape=shape;self.predictor=Predictor(module.utility if shape=='sigmoid' else linear)
        self.activation_priority=None;self.activation_initial=False
        self.activation_log=[];self.activation_empty_kept=[]

    def start_station(self,state,q,reason,priority=None,initial=False,scan_unknown=True):
        self.activation_priority=priority;self.activation_initial=initial
        return super().start_station(state,q,reason,priority,initial,scan_unknown)

    def station_action(self,state):
        # F3's conditional F1 continuations are unchanged. Gate only actual F3
        # optional shared scans, not primary-target, initial or unknown scans.
        if self.shape=='off' or self.level<3 or self.activation_initial:
            return super().station_action(state)
        original=list(self.station_channels);kept=[];decisions=[]
        for j in original:
            c=state.channels[j]
            if c.status!='found' or j==self.activation_priority or c.circle()[1]<=20:
                kept.append(j);continue
            pred=self.predictor.predict(state,c,self.station)
            if pred['gain'] is None:kept.append(j);continue
            best,_=self.predictor.best_view(state,c)
            rate=pred['gain']/(5+(state.measuring_channel!=j))
            # No 30m exclusion, .8 threshold, new points or clearance rule.
            keep=rate>=best['rate']
            if keep:kept.append(j)
            decisions.append({'at_action':state.actions,'channel':j,'q':self.station,'keep':keep,
                              'gain':pred['gain'],'mean_u':pred['mean_u'],'rate':rate,'alternative_rate':best['rate']})
        if not kept and original:
            # Preserve the original scheduler's non-empty-station contract.
            kept=original[:1]
            self.activation_empty_kept.append({'at_action':state.actions,'channel':kept[0]})
        self.station_channels=kept;self.activation_log.extend(decisions)
        return super().station_action(state)

    def metadata(self):
        return dict(super().metadata(),activation_shape=self.shape,
                    activation_decisions=self.activation_log,activation_empty_kept=self.activation_empty_kept)
