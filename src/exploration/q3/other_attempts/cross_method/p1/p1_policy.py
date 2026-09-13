"""P1 单候选组合：公共任务提案、四场景完整预演与非递归续行。"""
import copy
import math
import statistics
import time

from p1_tasks import (RefinedPolicy, a, task, service_pool, plan_route,
                      clearing_plans, dominated_negative)
from refined import transverse_points
from posterior import sample_worlds


class P1Policy(RefinedPolicy):
    def __init__(self, selected=None, enabled=True, deadline=math.inf):
        super().__init__(selected, level=3, samples=4)
        self.enabled = enabled
        self.deadline = deadline
        self.active_task = None
        self.task_events = []
        self.inside_rollout = False
        self.nominal_fallbacks = 0

    def check_time(self):
        if time.perf_counter() >= self.deadline:
            raise TimeoutError('P1 complete-decision wall deadline')

    def fork(self):
        obj = copy.copy(self)
        obj.__dict__ = {k: copy.deepcopy(v) for k, v in self.__dict__.items()
                        if k not in ('decisions', 'task_events', 'decision_data')}
        obj.decisions, obj.task_events, obj.decision_data = [], [], {}
        return obj

    def adopt(self, obj):
        decisions, events = self.decisions, self.task_events
        self.__dict__.update(obj.__dict__)
        self.decisions = decisions
        self.task_events = events + obj.task_events

    def start_assigned_scan(self, state, q, priority, channels, reason):
        # 与F3相同的候选资格及F1证明；允许空队列，不为推进而伪造反馈。
        a.PatrolPolicy.start_station(self, state, q, reason, priority=priority,
                                     scan_unknown=bool(channels))
        keep = []
        for j in self.station_channels:
            c = state.channels[j]
            if c.status == 'unknown' and j not in channels:
                continue
            proof = dominated_negative(c, self.station)
            if proof is not None:
                self.skipped.append(dict(channel=j, position=self.station,
                                         at_action=state.actions, **proof))
            else:
                keep.append(j)
        self.station_channels = keep
        self.pending_scan_unknown = bool(channels)

    def active_action(self, state):
        item = self.active_task
        if item is None:
            return None
        job, index = item['job'], item['index']
        j = job['channel']
        succeeded = state.channels[j].status == 'cleared'
        if succeeded or index == len(job['points']):
            if job['certified'] and not succeeded:
                raise AssertionError('certified P1 task exhausted without clearance')
            self.task_events.append(dict(event='task_finished', at_action=state.actions,
                task_id=item['id'], channel=j, actual_exit=state.position,
                attempted=index, cancelled=len(job['points'])-index, success=succeeded,
                scan_channels=job['scan_channels']))
            self.active_task = None
            self.start_assigned_scan(state, state.position, j, job['scan_channels'], 'p1_exit_scan')
            return self.station_action(state)
        q = job['points'][index]
        item['index'] += 1
        return self.action('clear', q, j, 'p1_certified_clear' if job['certified'] else job.get('reason', 'p1_try'),
                           p1_task_id=item['id'], p1_attempt=index+1)

    def install_task(self, state, job):
        self.station, self.station_channels, self.after_arrival_scan, self.multi = None, [], None, None
        self.target = job['channel']
        self.phase = 'service' if any(c.status == 'found' for c in state.channels.values()) else 'completion'
        self.pending_scan_unknown = bool(job['scan_channels'])
        identity = f'{state.actions}:{job["channel"]}:{job["kind"]}'
        self.task_events.append(dict(event='task_installed', task_id=identity,
                                     at_action=state.actions, task=copy.deepcopy(job)))
        if job['kind'] != 'scan':
            if job.get('reason') == 'single_center_try':
                self.tried_centers.add(job['channel'])
            self.active_task = dict(job=copy.deepcopy(job), index=0, id=identity)
            return self.active_action(state)
        if job['channel'] is not None:
            j = job['channel']
            self.local_counts[j] = self.local_counts.get(j, 0)+1
        self.start_assigned_scan(state, job['entry'], job['channel'], job['scan_channels'], 'p1_joint_scan')
        action = self.station_action(state)
        if action is None:
            raise ValueError('P1 first task has no executable scan')
        return action

    def projection(self, state, action):
        j, q = action['channel'], tuple(action['position'])
        if action['kind'] == 'measure':
            sequence = [j]+(list(self.station_channels) if self.station == q else [])
            # 纯查漏不替换其中一个未知频道的已知源服务槽。
            owner = j if state.channels[j].status == 'found' else None
            job = task('scan', [q], owner, fixed_scan=sequence)
            job['scan_channels'] = [k for k in sequence if state.channels[k].status == 'unknown']
            return job
        cert = action['reason'] in ('certain_here', 'certain_center')
        job = task('clear' if cert else 'attempt', [q], j, cert)
        scan_unknown = bool(self.after_arrival_scan and self.after_arrival_scan[1])
        job['scan_channels'] = [k for k, c in state.channels.items() if c.status == 'unknown'] if scan_unknown else []
        return job

    def candidates(self, state, original_policy, original):
        options = [dict(id='original', action=original, policy=original_policy,
                        task=original_policy.projection(state, original))]
        reason, j = original['reason'], original['channel']
        c = state.channels[j]
        relevant = reason in ('planned_transverse_scan', 'planned_clearance_scan', 'current_view', 'single_center_try')
        alternatives = []
        if reason == 'planned_transverse_scan':
            for i, q in enumerate(transverse_points(state, c)):
                if q in c.measured:
                    continue
                for scan_unknown in sorted({original_policy.pending_scan_unknown, True}):
                    if math.dist(q, original['position']) < 1e-5 and scan_unknown == original_policy.pending_scan_unknown:
                        continue
                    alternatives.append(dict(id=f'mirror{i}_unknown{int(scan_unknown)}', kind='scan',
                                             q=q, channel=j, scan_unknown=scan_unknown))
        elif reason == 'planned_clearance_scan' and not original_policy.pending_scan_unknown:
            if any(x.status == 'unknown' and state.position not in x.measured for x in state.channels.values()):
                alternatives.append(dict(id='scan_unknown_now', kind='scan', q=state.position,
                                         channel=j, scan_unknown=True))
        if relevant and c.status == 'found' and c.circle()[1] > 20:
            alternatives.extend(clearing_plans(state, c))
        for option in alternatives:
            p = original_policy.fork()
            if option['kind'] == 'multiclear':
                job = task('clear', option['points'], j, True, geometry_radii=option['radii'])
                job['scan_channels'] = [k for k, ch in state.channels.items() if ch.status == 'unknown'] if p.pending_scan_unknown else []
                action = p.install_task(state, job)
            else:
                action = RefinedPolicy.install(p, state, option, original)
                job = p.projection(state, action)
            options.append(dict(id=option['id'], action=action, policy=p, task=job))
        pool = service_pool(state, self)
        route, info = plan_route(state, pool, check=self.check_time)
        if not route:
            raise ValueError('P1 noncomplete state has no route')
        p = self.fork()
        action = p.install_task(state, route[0])
        options.append(dict(id='channel_joint', action=action, policy=p, task=route[0],
                            nominal=info, route=route))
        return options, pool

    def rollout(self, state, world, option):
        s = copy.deepcopy(state)
        p = option['policy'].fork()
        p.lookahead = False
        p.inside_rollout = True
        env = a.ConditionalEnvironment(world, s)
        action = option['action']
        for step in range(3000):
            self.check_time()
            reply = env.act(action); s.update(action, reply)
            if s.complete:
                if len(env.cleared) != len(world.sources):
                    raise AssertionError('sampled completion without all clear')
                return env.virtual_time_s-state.virtual_time_s, step+1, p.nominal_fallbacks
            if env.virtual_time_s-state.virtual_time_s > 10800:
                raise ValueError('conditional rollout virtual limit')
            action = p.choose(s)
        raise ValueError('conditional rollout action limit')

    def choose_joint(self, state):
        self.check_time()
        if not self.enabled:
            return RefinedPolicy.choose_joint(self, state)
        if self.active_task is not None:
            action = self.active_action(state)
            if action is not None:
                return action
        previous_station, previous_channels = self.station, set(self.station_channels)
        old = self.fork()
        original = a.PatrolPolicy.choose_joint(old, state)
        ongoing = (previous_station is not None and original['channel'] in previous_channels
                   and tuple(original['position']) == previous_station)
        # 同站队列及原地确定清除不重复进行四场景预演。
        if ongoing or original['reason'] == 'certain_here':
            self.adopt(old)
            return original
        started = time.perf_counter()
        record = dict(at_action=state.actions, position=state.position, original_action=original,
                      history_seed=a.history_seed(state), options=[], rollout_calls=0, simulated_actions=0,
                      continuation_fallbacks=0)
        chosen = dict(id='original', policy=old, action=original)
        try:
            options, pool = self.candidates(state, old, original)
            if self.lookahead:
                if self.inside_rollout:
                    raise AssertionError('nested lookahead forbidden')
                worlds, info = sample_worlds(state, 4)
                self.check_time()
                record['posterior'] = info
                for option in options:
                    values = []
                    for world in worlds:
                        record['rollout_calls'] += 1
                        value, steps, fallbacks = self.rollout(state, world, option)
                        record['simulated_actions'] += steps
                        record['continuation_fallbacks'] += fallbacks
                        values.append(value)
                    option['score'] = statistics.mean(values)
                    record['options'].append(dict(id=option['id'], costs_s=values, mean_s=option['score'],
                                                  task=option['task']))
            else:
                for option in options:
                    if option['id'] == 'channel_joint':
                        info = option['nominal']
                    else:
                        _, info = plan_route(state, pool, prefix=option['task'], check=self.check_time)
                    option['score'] = info['total_s']
            chosen = min(options, key=lambda x: (x['score'], x['id'] != 'original', x['id']))
            if self.lookahead:
                joint = options[-1]
                record['joint_route'] = joint['route']
                record['joint_nominal'] = joint['nominal']
                record['predicted_saving_s'] = options[0]['score']-chosen['score']
        except TimeoutError:
            # 现实截止不能靠原动作继续执行来掩盖。
            record.update(chosen='timeout', wall_s=time.perf_counter()-started)
            self.decisions.append(record)
            raise
        except (ValueError, RuntimeError, AssertionError) as exc:
            record['fallback'] = str(exc)
        self.adopt(chosen['policy'])
        if not self.lookahead and 'fallback' in record:
            self.nominal_fallbacks += 1
        if self.lookahead:
            record.update(chosen=chosen['id'], wall_s=time.perf_counter()-started)
            self.decisions.append(record)
        return dict(chosen['action'], p1_choice=chosen['id'])

    def metadata(self):
        result = super().metadata()
        result.update(p1_enabled=self.enabled, p1_task_events=self.task_events,
                      p1_active_task=self.active_task, p1_nested_rollout=False)
        return result
