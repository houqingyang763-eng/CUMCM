"""后续动作增量：逻辑冗余过滤、条件全程试算选测点、少量清除圆。"""
import copy
import itertools
import math
import statistics
import time

from posterior import a, g, sample_worlds
from patrol import major_axis


def dominated_negative(c, q):
    if c.status != 'found':
        return None
    poly = c.support()
    if not poly:
        return None
    for p, result, _ in c.observations:
        if result != 'no_signal':
            continue
        margin = min(sum((q[k]-x[k])**2-(p[k]-x[k])**2 for k in (0,1)) for x in poly)
        if margin >= 1e-4:
            return {'prior_position':p, 'squared_distance_margin':margin}
    return None


def transverse_points(state, c):
    center, radius = c.circle()
    axis = major_axis(c.support())
    normal = (-axis[1], axis[0])
    offset = min(300., max(30., radius/2))
    return [g.add(center, g.mul(normal, sign*offset)) for sign in (-1,1)]


def clearing_plans(state, c):
    """连续凸多边形分片覆盖；每片所有顶点都在20米圆内才允许执行。"""
    poly = c.support()
    axis = major_axis(poly)
    values = [g.dot(p, axis) for p in poly]
    lo, hi = min(values), max(values)
    plans = []
    for k in (2,3):
        centers, radii = [], []
        for i in range(k):
            left, right = lo+(hi-lo)*i/k, lo+(hi-lo)*(i+1)/k
            part = g.clip(g.clip(poly, axis, right), g.mul(axis,-1), -left)
            if not part:
                break
            center, _ = g.enclosing_circle(part)
            radius = max(math.dist(center,p) for p in part)
            centers.append(center)
            radii.append(radius)
        if len(centers) != k or max(radii) > 20-1e-6:
            continue
        order = min(itertools.permutations(range(k)), key=lambda ix:
                    math.dist(state.position,centers[ix[0]])+sum(math.dist(centers[u],centers[v]) for u,v in zip(ix,ix[1:])))
        qs = [centers[i] for i in order]
        cost = math.dist(state.position,qs[0])/5+sum(math.dist(p,q)/5 for p,q in zip(qs,qs[1:]))+3*(k-1)+5
        plans.append({'id':f'clear{k}', 'kind':'multiclear', 'channel':c.channel,
                      'points':qs, 'radii':radii, 'worst_local_s':cost})
    return plans


class RefinedPolicy(a.AdaptivePolicy):
    def __init__(self, selected=None, level=1, samples=4):
        super().__init__(selected)
        self.level = level
        self.samples = samples
        self.lookahead = True
        self.skipped = []
        self.kept_to_progress = []
        self.decisions = []
        self.multi = None
        self.pending_scan_unknown = True

    def start_station(self, state, q, reason, priority=None, initial=False, scan_unknown=True):
        if initial and self.initial_index == 1 and self.selected is None:
            sel = a.select(state, samples=16)
            self.selected = next(c for c in sel['candidates'] if c['id'] == sel['position'])
        super().start_station(state,q,reason,priority,initial,scan_unknown)
        self.pending_scan_unknown = scan_unknown
        if initial or self.level < 1:
            return
        original = list(self.station_channels)
        keep = []
        discarded = []
        for j in original:
            proof = dominated_negative(state.channels[j], self.station)
            if proof:
                discarded.append(dict(channel=j, position=self.station, at_action=state.actions, **proof))
            else:
                keep.append(j)
        if not keep and original:
            # 原调度器不能接受空服务站。保留一个合法动作，不虚构测量来改状态。
            keep = original[:1]
            self.kept_to_progress.append({'channel':keep[0], 'position':self.station})
            discarded = [x for x in discarded if x['channel'] != keep[0]]
        self.skipped.extend(discarded)
        self.station_channels = keep

    def metadata(self):
        return dict(super().metadata(), refinement_level=self.level, samples=self.samples,
                    skipped=self.skipped, kept_to_progress=self.kept_to_progress,
                    refinement_decisions=self.decisions)

    def _multi_action(self, state):
        if self.multi is None:
            return None
        j = self.multi['channel']
        if state.channels[j].status == 'cleared':
            self.after_arrival_scan = (state.position,self.multi['scan_unknown'],j)
            self.multi = None
            return None
        if not self.multi['points']:
            raise AssertionError('certified multiclear exhausted without clearance')
        q = self.multi['points'].pop(0)
        return self.action('clear',q,j,'certified_multi_clear')

    def install(self, state, option, original):
        if option['kind'] == 'original':
            return original
        self.station = None
        self.station_channels = []
        self.after_arrival_scan = None
        if option['kind'] == 'multiclear':
            self.multi = {'channel':option['channel'], 'points':list(option['points']),
                          'scan_unknown':self.pending_scan_unknown}
            return self._multi_action(state)
        self.start_station(state,tuple(option['q']),'refined_shared_scan',priority=option['channel'],
                           scan_unknown=option['scan_unknown'])
        action = self.station_action(state)
        if action is None:
            raise ValueError('candidate scan has no executable channel')
        return action

    def simulate(self, state, world, option, original):
        s = copy.deepcopy(state)
        p = copy.deepcopy(self)
        p.lookahead = False
        p.level = 1  # 所有候选使用相同F1后续策略，绝不递归调用试算。
        p.decisions = []
        env = a.ConditionalEnvironment(world,s)
        action = p.install(s,option,original)
        for step in range(3000):
            reply = env.act(action)
            s.update(action,reply)
            if s.complete:
                if len(env.cleared) != len(world.sources):
                    raise AssertionError('rollout ended without clearing sampled sources')
                return env.virtual_time_s-state.virtual_time_s
            if env.virtual_time_s-state.virtual_time_s > 10800:
                raise ValueError('rollout exceeds virtual limit')
            action = p.choose(s)
        raise ValueError('rollout exceeds action limit')

    def select_candidate(self, state, records, original):
        return min(records,key=lambda x:x['mean_s']), {}

    def choose_joint(self, state):
        previous_station = self.station
        previous_reason = self.station_reason
        previous_channels = set(self.station_channels)
        multi = self._multi_action(state)
        if multi is not None:
            return multi
        original = super().choose_joint(state)
        ongoing = (previous_station is not None and original['channel'] in previous_channels
                   and tuple(original['position']) == previous_station
                   and original['reason'] == previous_reason)
        if self.level < 2 or not self.lookahead or ongoing:
            return original
        reason = original['reason']
        relevant = reason in ('planned_transverse_scan','planned_clearance_scan','current_view','single_center_try')
        if not relevant:
            return original
        j = original['channel']
        c = state.channels[j]
        options = [{'id':'original','kind':'original'}]
        # 原候选始终保留；仅在本来要补测时加入同一几何的另一侧。
        if reason == 'planned_transverse_scan':
            for i,q in enumerate(transverse_points(state,c)):
                if q in c.measured:
                    continue
                for scan_unknown in sorted({self.pending_scan_unknown,True}):
                    if math.dist(q,original['position']) < 1e-5 and scan_unknown == self.pending_scan_unknown:
                        continue
                    options.append({'id':f'mirror{i}_unknown{int(scan_unknown)}','kind':'scan',
                                    'q':q,'channel':j,'scan_unknown':scan_unknown})
        elif reason == 'planned_clearance_scan' and not self.pending_scan_unknown:
            if any(x.status == 'unknown' and state.position not in x.measured for x in state.channels.values()):
                options.append({'id':'scan_unknown_now','kind':'scan','q':state.position,'channel':j,'scan_unknown':True})
        if self.level >= 3 and c.status == 'found' and c.circle()[1] > 20:
            options.extend(clearing_plans(state,c))
        if len(options) == 1:
            return original
        started = time.perf_counter()
        record = {'at_action':state.actions,'position':state.position,'channel':j,'original_reason':reason,
                  'original_action':original,'scan_unknown':self.pending_scan_unknown}
        try:
            worlds, info = sample_worlds(state,self.samples)
            records = []
            for option in options:
                values = [self.simulate(state,w,option,original) for w in worlds]
                records.append(dict(option,costs_s=values,mean_s=statistics.mean(values)))
            chosen, extra = self.select_candidate(state,records,original)
            record.update(posterior=info, options=records, chosen=chosen['id'],
                          predicted_saving_s=records[0]['mean_s']-chosen['mean_s'])
            record.update(extra)
            action = self.install(state,chosen,original)
        except (ValueError, RuntimeError, AssertionError) as exc:
            # 保守回退：任何采样/试算失败都不用残缺场景挑选动作。
            record.update(chosen='original',fallback=str(exc))
            action = original
        record['wall_s'] = time.perf_counter()-started
        self.decisions.append(record)
        action = dict(action, refinement_choice=record['chosen'])
        return action
