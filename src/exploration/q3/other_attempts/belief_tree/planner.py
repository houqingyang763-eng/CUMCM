"""统一原子动作、公共证书终止、条件粒子再生的有限PFT反馈树。"""
import copy
import math
import random
import time
import json
from dataclasses import dataclass, field

from particle_belief import a, g, draw, likelihood
from refined import RefinedPolicy, clearing_plans, transverse_points, dominated_negative


def fallback_policy(state):
    p = RefinedPolicy(level=1)
    p.initial_index = 2
    p.initial_finish_s = 0.
    p.phase = 'service'
    p.lookahead = False
    p.tried_centers = {j for j,c in state.channels.items() if any(r == 20 for _,r in c.exclusions)}
    return p


def action_key(action):
    return action['kind'], action['channel'], tuple(action['position'])


def candidates(state, policy):
    """顺序仅引导扩展；全部行动最终以预计剩余秒数评价。"""
    incumbent_policy = copy.deepcopy(policy)
    original = incumbent_policy.choose(state)
    # 原地保证清除的费用迟早都要支付，立即做不会增加路程或测向切频。
    for c in state.channels.values():
        if c.status == 'found' and c.support() and all(math.dist(state.position,x)<=20-1e-6 for x in c.support()):
            direct = dict(kind='clear',position=state.position,channel=c.channel,reason='certain_here',phase='belief')
            return [direct], policy_after(state,policy,incumbent_policy,direct,original)
    actions = [dict(original, reason='incumbent_' + original['reason'], phase='belief')]
    seen = {action_key(actions[0])}
    groups = {'clear':[], 'here':[], 'move':[]}

    def add(kind,q,j,reason,group):
        q = tuple(q)
        c = state.channels[j]
        if c.status in ('cleared','absent'):
            return
        if kind == 'measure' and (q in c.measured or dominated_negative(c,q)):
            return
        if kind == 'clear' and any(r == 20 and math.dist(q,p) < 1e-6 for p,r in c.exclusions):
            return
        item = dict(kind=kind,position=q,channel=j,reason=reason,phase='belief')
        key = action_key(item)
        if key not in seen:
            seen.add(key)
            groups[group].append(item)

    active = [c for c in state.channels.values() if c.status not in ('cleared','absent')]
    found = [c for c in active if c.status == 'found']
    # 未知频道历史完全相同且先验可交换，只保留不多切频的代表。
    unknown_groups = {}
    for c in active:
        if c.status == 'unknown':
            key = tuple((tuple(q),r,b) for q,r,b in c.observations), tuple(c.exclusions)
            unknown_groups.setdefault(key, []).append(c.channel)
    unknown = [state.measuring_channel if state.measuring_channel in js else min(js)
               for js in unknown_groups.values()]
    for j in [c.channel for c in found]+unknown:
        add('measure', state.position, j, 'any_channel_here','here')
    for c in found:
        center,radius = c.circle()
        if radius <= 80:
            add('clear',center,c.channel,'center_attempt','clear')
        for plan in clearing_plans(state,c):
            for q in plan['points']:
                add('clear',q,c.channel,'cover_attempt','clear')
        for q in transverse_points(state,c):
            add('measure',q,c.channel,'either_transverse','move')
    points = state.discovery_points(limit=6) if unknown else []
    if not state.ever_seen:
        points += [(0.,0.),(-150.,0.),(600.,0.),(1000.,0.)]
    for q in points:
        for j in unknown:
            add('measure',q,j,'unknown_search','move')
    for items in groups.values():
        items.sort(key=lambda x:(math.dist(state.position,x['position']), x['channel']))
    # 穿插原地测、所有目标试清和异地测，不让单一类别占满展开预算。
    for i in range(max(map(len,groups.values()),default=0)):
        for group in ('clear','here','move'):
            if i < len(groups[group]):
                actions.append(groups[group][i])
    return actions, incumbent_policy


def policy_after(state, parent_policy, incumbent_policy, action, original):
    if action_key(action) == action_key(original):
        return copy.deepcopy(incumbent_policy)
    p = copy.deepcopy(parent_policy)
    p.station = None
    p.station_channels = []
    p.after_arrival_scan = None
    p.multi = None
    p.target = None
    if action['kind'] == 'clear':
        p.tried_centers.add(action['channel'])
        p.after_arrival_scan = (tuple(action['position']),True,action['channel'])
    return p


@dataclass
class Edge:
    action: dict
    visits: int = 0
    total: float = 0.
    children: list = field(default_factory=list)
    multiplicities: list = field(default_factory=list)
    outcome_keys: list = field(default_factory=list)

    @property
    def mean(self):
        return self.total/self.visits if self.visits else math.inf


@dataclass
class Node:
    state: object
    policy: object
    worlds: list
    visits: int = 0
    actions: list | None = None
    incumbent_policy: object = None
    edges: list = field(default_factory=list)
    leaf_cache: dict = field(default_factory=dict)


class BeliefTreePolicy:
    def __init__(self, depth=3, iterations=96, particles=16, pool_size=256):
        self.depth, self.iterations = depth, iterations
        self.particles,self.pool_size = particles,pool_size
        self.fallback = None
        self.decisions = []
        self.errors = []
        self.serial = 0
        self.log_path = None
        self.exploration = 180.

    def log(self,record):
        self.decisions.append(record)
        if self.log_path is not None:
            with self.log_path.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps(record,ensure_ascii=False)+'\n')

    def metadata(self):
        return {'algorithm':'conditional_particle_feedback_tree', 'depth':self.depth,
                'iterations':self.iterations,'particles':self.particles,'pool_size':self.pool_size,
                'decisions':self.decisions,'errors':self.errors}

    def leaf(self,node):
        if node.state.complete:
            return 0.
        index = self.rng.randrange(len(node.worlds))
        if index in node.leaf_cache:
            return node.leaf_cache[index]
        world = node.worlds[index]
        state = copy.deepcopy(node.state)
        policy = copy.deepcopy(node.policy)
        env = a.ConditionalEnvironment(world,state)
        for _ in range(3000):
            if state.complete:
                if len(env.cleared) != len(world.sources):
                    raise AssertionError('public stop fails sampled world')
                cost = env.virtual_time_s-node.state.virtual_time_s
                node.leaf_cache[index] = cost
                self.counters['tail_calls'] += 1
                return cost
            action = policy.choose(state)
            state.update(action,env.act(action))
            if env.virtual_time_s-node.state.virtual_time_s > 10800:
                break
        raise RuntimeError('tail did not complete; no free terminal')

    def expand(self,node,edge):
        world = self.rng.choice(node.worlds)
        env = a.ConditionalEnvironment(world,node.state)
        reply = env.act(edge.action)
        key = (reply.get('measure_result'),reply.get('svd_deg'),reply.get('clear_result'))
        if key in edge.outcome_keys:
            index = edge.outcome_keys.index(key)
            edge.multiplicities[index] += 1
            self.counters['identical_feedback_reused'] = self.counters.get('identical_feedback_reused',0)+1
            cost,child,_ = edge.children[index]
            return cost,child
        weights = [likelihood(w,node.state,edge.action,reply) for w in node.worlds]
        mass = sum(weights)
        if mass <= 0:
            raise ValueError('generated observation has zero particle likelihood')
        ess = mass*mass/sum(w*w for w in weights)
        self.counters['min_ess'] = min(self.counters['min_ess'],ess)
        state = copy.deepcopy(node.state)
        state.update(edge.action,reply)
        cost = state.virtual_time_s-node.state.virtual_time_s
        policy = policy_after(state,node.policy,node.incumbent_policy,edge.action,node.actions[0])
        self.serial += 1
        # 按完整历史重建条件分布，而非从唯一命中粒子克隆出假精度。
        worlds = [] if state.complete else draw(state,self.particles,self.serial,self.pool_size)
        child = Node(state,policy,worlds)
        edge.children.append((cost,child,reply))
        edge.outcome_keys.append(key)
        edge.multiplicities.append(1)
        self.counters['nodes'] += 1
        self.counters['posterior_refreshes'] += int(not state.complete)
        return cost,child

    def simulate(self,node,depth):
        self.counters['max_depth'] = max(self.counters['max_depth'],self.depth-depth)
        if node.state.complete:
            return 0.
        if depth == 0:
            return self.leaf(node)
        if node.actions is None:
            node.actions,node.incumbent_policy = candidates(node.state,node.policy)
        # DPW只控制搜索资源，不加入任务评分。
        width = min(len(node.actions),max(1,math.ceil(2*math.sqrt(node.visits+1))))
        if len(node.edges) < width:
            edge = Edge(node.actions[len(node.edges)])
            node.edges.append(edge)
        else:
            edge = min(node.edges,key=lambda e:e.mean-self.exploration*math.sqrt(math.log(node.visits+1)/e.visits))
        if len(edge.children) < max(1,math.ceil(math.sqrt(edge.visits+1))):
            cost,child = self.expand(node,edge)
        else:
            weights = edge.multiplicities if edge.multiplicities else None
            cost,child,_ = self.rng.choices(edge.children,weights)[0]
        value = cost + self.simulate(child,depth-1)
        edge.visits += 1
        edge.total += value
        node.visits += 1
        return value

    def choose(self,state):
        if state.complete:
            raise RuntimeError('no action after public completion')
        if self.fallback is None:
            self.fallback = fallback_policy(state)
        start = time.perf_counter()
        self.serial = 0
        self.rng = random.Random(a.history_seed(state,77123+state.actions))
        self.counters = dict(nodes=0,tail_calls=0,posterior_refreshes=0,min_ess=float(self.particles),max_depth=0)
        original_policy = copy.deepcopy(self.fallback)
        original = original_policy.choose(state)
        record = dict(at_action=state.actions,position=state.position,original=original)
        for c in state.channels.values():
            if c.status == 'found' and c.support() and all(math.dist(state.position,x)<=20-1e-6 for x in c.support()):
                action = dict(kind='clear',position=state.position,channel=c.channel,reason='certain_here',phase='belief')
                self.fallback = policy_after(state,self.fallback,original_policy,action,original)
                record.update(chosen=action,proof='certain_clear_here',wall_s=time.perf_counter()-start)
                self.log(record)
                return action
        try:
            root = Node(copy.deepcopy(state),copy.deepcopy(self.fallback),draw(state,self.particles,0,self.pool_size))
            for _ in range(self.iterations):
                self.simulate(root,self.depth)
            selected = min(root.edges,key=lambda e:e.mean)
            action = selected.action
            self.fallback = policy_after(state,self.fallback,root.incumbent_policy,action,root.actions[0])
            record.update(chosen=action,candidates=len(root.actions),evaluated=len(root.edges),
                          estimates=[dict(action=e.action,mean_s=e.mean,visits=e.visits,
                                          observations=len(e.children)) for e in root.edges])
        except (ValueError,RuntimeError,AssertionError) as exc:
            # 有效性问题保留记录并使用完整公共状态后备；不能把失败当低成本。
            action = original
            self.fallback = original_policy
            record.update(chosen=action,error=repr(exc))
            self.errors.append(dict(at_action=state.actions,error=repr(exc)))
        record.update(**self.counters,wall_s=time.perf_counter()-start)
        self.log(record)
        return dict(action,phase='belief')
