"""仅由第一站公开反馈选择第二站；全清 rollout，不接收实际环境。"""
import copy
import hashlib
import json
import math
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'probability_patrol'))
import runner as base
from patrol import PatrolPolicy
from coverage_state import CoverageInformationState
from simulation import Source, Scenario, LocalEnvironment
from state import audit_state

CONFIG = json.loads((HERE.parent / 'probability_patrol/configs/r3_covering.json').read_text())


def history_seed(state, salt=0):
    h = [(j, c.observations) for j, c in state.channels.items()]
    return int.from_bytes(hashlib.sha256(json.dumps(h, sort_keys=True).encode()).digest()[:8], 'big') ^ salt


def negative_mass(q, radius_prior='uniform'):
    # First point lies within 150m of origin: every possible reception disk is inside D.
    assert math.hypot(*q) <= 300
    er2 = (1000**2 + 1000*1500 + 1500**2)/3 if radius_prior == 'uniform' else 1000**2
    return 1 - er2/1800**2


def count_weights(k, z):
    # Prior N uniform 10..16, uniform subset of N channels. Positive likelihood cancels.
    ns = list(range(max(10, k), 17))
    weights = [math.comb(20-k, n-k)/math.comb(20, n)*z**(n-k) for n in ns]
    total = sum(weights)
    return ns, [w/total for w in weights]


def sample_worlds(state, count=16, salt=0, radius_prior='uniform'):
    """Uniform area, uniform N/subset, bounded uniform angle likelihood approximation.

    First bearing rounded to 0.01 degree is treated as a continuous reading with
    uniform error +/-1 degree. Near readings use a 5m disk. Future error is a
    fixed hashed spatial field independent of the first reading.
    """
    rng = random.Random(history_seed(state, salt))
    q = tuple(state.position)
    found = [j for j,c in state.channels.items() if c.status == 'found']
    unknown = [j for j,c in state.channels.items() if c.status == 'unknown']
    ns, weights = count_weights(len(found), negative_mass(q, radius_prior))
    worlds = []
    for m in range(count):
        n = rng.choices(ns, weights)[0]
        active = found + rng.sample(unknown, n-len(found))
        sources = []
        for j in active:
            c = state.channels[j]
            for attempt in range(100000):
                if c.status == 'found':
                    result, bearing = c.observations[0][1:]
                    if result == 'near':
                        d, angle = 5*math.sqrt(rng.random()), rng.uniform(0, 2*math.pi)
                    else:
                        d = 1500*math.sqrt(rng.random())
                        angle = math.radians(bearing + rng.uniform(-1, 1))
                    x = (q[0]+d*math.cos(angle), q[1]+d*math.sin(angle))
                else:
                    r, angle = 1800*math.sqrt(rng.random()), rng.uniform(0,2*math.pi)
                    x = (r*math.cos(angle), r*math.sin(angle))
                    d = math.dist(x,q)
                radius = rng.uniform(1000,1500) if radius_prior == 'uniform' else 1000.
                positive = c.status == 'found'
                if math.hypot(*x) > 1800 or (d <= radius) != positive:
                    continue
                if positive and result != 'near' and d <= 5:
                    continue
                if not c.compatible(x):
                    continue
                sources.append(Source(j, x, radius))
                break
            else:
                raise RuntimeError('posterior rejection sampler exhausted; not an absence proof')
        worlds.append(Scenario(f'posterior_{m}', rng.randrange(2**31), 'posterior', 'hashed', tuple(sources)))
    return worlds, {'n_values':ns, 'n_probabilities':weights, 'mean_n':sum(n*w for n,w in zip(ns,weights)),
                    'radius_prior':radius_prior, 'seed':history_seed(state,salt)}


class ConditionalEnvironment(LocalEnvironment):
    """Preserve real first-station readings at the same coordinate; never re-draw noise."""
    def __init__(self, world, state):
        super().__init__(world)
        self.position, self.channel, self.virtual_time_s = state.position, state.measuring_channel, state.virtual_time_s
        self.history = {(tuple(q),j):(r,b) for j,c in state.channels.items() for q,r,b in c.observations}

    def act(self, action):
        response = super().act(action)
        key = (tuple(action['position']),action['channel'])
        if action['kind']=='measure' and action['channel'] not in self.cleared and key in self.history:
            r,b = self.history[key]
            response['measure_result'] = r
            response.pop('svd_deg',None)
            if b is not None:
                response['svd_deg'] = b
        return response


def continuation(state, candidate):
    p = PatrolPolicy(CONFIG)
    p.initial_index = 2
    p.start_station(state, tuple(candidate['q']), 'adaptive_second', initial=True)
    p.station_channels = [j for j in p.station_channels if j in candidate['channels']]
    return p


def rollout(state, world, candidate, audit=False):
    s = copy.deepcopy(state)
    env = ConditionalEnvironment(world,s)
    p = continuation(s,candidate)
    if audit:
        audit_state(s,env)
    for step in range(3000):
        if s.complete:
            assert len(env.cleared)==len(world.sources)
            return env.virtual_time_s-state.virtual_time_s
        a = p.choose(s)
        feedback = env.act(a)
        s.update(a,feedback)
        if audit:
            audit_state(s,env)
        if env.virtual_time_s-state.virtual_time_s > 180*60:
            raise RuntimeError('rollout exceeds 180 minutes')
    raise RuntimeError('rollout exceeds action limit')


def candidates(state):
    p = PatrolPolicy(CONFIG)
    found = [c for c in state.channels.values() if c.status=='found']
    # Six positions: old, current, two observed local jobs, two opposite perpendiculars.
    found.sort(key=lambda c: (math.dist(state.position,c.circle()[0]),c.channel))
    points = [tuple(CONFIG['initial_points'][1]), tuple(state.position)]
    for c in found[:2]:
        points.append(p.local_point(state,c))
    angle = math.atan2(found[0].circle()[0][1]-state.position[1],found[0].circle()[0][0]-state.position[0]) if found else 0.
    for sign in (-1,1):
        points.append((state.position[0]+sign*600*(-math.sin(angle)),state.position[1]+sign*600*math.cos(angle)))
    points = list(dict.fromkeys(points))
    all_channels = [j for j,c in state.channels.items() if c.status not in ('cleared','absent')]
    sets = [('all',all_channels),('found',[c.channel for c in found]),
            ('unknown',[j for j in all_channels if state.channels[j].status=='unknown'])]
    output=[]
    for i,q in enumerate(points):
        seen=set()
        for kind, channels in sets:
            channels=sorted(j for j in channels if q not in state.channels[j].measured)
            if tuple(channels) in seen:
                continue
            seen.add(tuple(channels))
            output.append({'id':f'p{i}_{kind}','q':q,'channels':channels,'set':kind})
    return output


def select(state, samples=16, salt=0, radius_prior='uniform'):
    worlds, posterior = sample_worlds(state,samples,salt,radius_prior)
    options=candidates(state)
    records=[]
    for a in options:
        values=[]
        errors=[]
        for world in worlds:
            try:
                values.append(rollout(state,world,a))
            except Exception as exc:
                values.append(100*3600.)
                errors.append(str(exc))
        records.append(dict(a, costs_s=values, mean_s=statistics.mean(values), errors=errors))
    if any(r['errors'] for r in records):
        raise RuntimeError('incomplete rollout; selection aborted: '+str([r['errors'] for r in records if r['errors']][:1]))
    position = min((r for r in records if r['set']=='all'), key=lambda r:r['mean_s'])
    joint = min(records,key=lambda r:r['mean_s'])
    fixed = next(r for r in records if r['id']=='p0_all')
    return {'posterior':posterior,'samples':samples,'candidates':records,
            'position':position['id'],'joint':joint['id'],'fixed':fixed['id']}


class AdaptivePolicy(PatrolPolicy):
    def __init__(self, selected):
        super().__init__(CONFIG)
        self.selected = selected
        self.adapted = False

    def start_station(self, state, q, reason, priority=None, initial=False, scan_unknown=True):
        if initial and self.initial_index==1:
            q = tuple(self.selected['q'])
            self.adapted=True
        super().start_station(state,q,reason,priority,initial,scan_unknown)
        if initial and self.initial_index==1:
            self.station_channels=[j for j in self.station_channels if j in self.selected['channels']]

    def metadata(self):
        return dict(super().metadata(), selected_second=self.selected)


def first_state(case):
    """Evaluation harness only. Selection receives returned state, never case/env."""
    env=LocalEnvironment(case)
    state=CoverageInformationState()
    p=PatrolPolicy(CONFIG)
    p.start_station(state,tuple(CONFIG['initial_points'][0]),'initial_1',initial=True)
    while p.station_channels:
        action=p.station_action(state)
        if action is None:
            break
        state.update(action,env.act(action))
        audit_state(state,env)
    return state
