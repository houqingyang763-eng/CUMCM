"""候选①：只为新认证清除目标比较扫描取消风险，不改变真实任务。"""
import math
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / 'src/q4'))
from selected import SelectedPolicy


def travel(start, jobs):
    return sum(math.dist(a, b) for a, b in zip(
        [start] + [j['position'] for j in jobs], [j['position'] for j in jobs])) / 5


def compare_prefixes(start, route, candidate_indices):
    """服务位置与扫描顺序固定；扫描前缀是敏感性场景，不是概率预测。"""
    candidates = [list(route)]
    for index in candidate_indices:
        if index:
            candidates.append([route[index]] + route[:index] + route[index+1:])
    scan_order = [tuple(j['position']) for j in route if j['kind'] == 'scan']
    costs = []
    for candidate in candidates:
        costs.append([travel(start, [j for j in candidate if j['kind'] != 'scan'
                      or tuple(j['position']) in scan_order[:k]])
                      for k in range(len(scan_order)+1)])
    optimum = [min(row[k] for row in costs) for k in range(len(scan_order)+1)]
    regrets = [max(v-best for v, best in zip(row, optimum)) for row in costs]
    best = min(range(len(candidates)), key=lambda i: (regrets[i], costs[i][-1], i))
    # 容差内保留原路线，防止纯浮点误差引起决策改变。
    if regrets[0] <= regrets[best] + 1e-7:
        best = 0
    return candidates[best], dict(costs_s=costs, worst_regret_s=regrets, chosen_index=best,
                                  candidate_channels=[None]+[route[i].get('channel') for i in candidate_indices if i],
                                  retained_scan_prefixes=list(range(len(scan_order)+1)))


class MicroAPolicy(SelectedPolicy):
    def __init__(self):
        super().__init__()
        self.a_certified_seen = set()
        self.a_decisions = []

    def _plan(self, state):
        route = super()._plan(state)
        certified = {j['channel'] for j in route if j['kind'] == 'clear' and
                     state.channels[j['channel']].support() and
                     all(math.dist(j['position'], p) <= 20-1e-6
                         for p in state.channels[j['channel']].support())}
        fresh = certified - self.a_certified_seen
        self.a_certified_seen |= certified
        indices = [i for i, job in enumerate(route) if job.get('channel') in fresh and job['kind']=='clear']
        if not indices or not any(j['kind']=='scan' for j in route):
            return route
        chosen, record = compare_prefixes(state.position, route, indices)
        delta = travel(state.position, chosen) - travel(state.position, route)
        self.a_decisions.append(dict(at_action=state.actions, fresh_certified=sorted(fresh),
                                     full_plan_delta_s=delta, **record))
        if record['chosen_index']:
            # 仅调整顺序，保留原任务、坐标、覆盖承诺以及全部认证信息。
            plan = self.plans[-1]
            plan['jobs'] = chosen
            plan['route_m'] = travel(state.position, chosen)*5
            plan['estimated_cost_s'] += delta
            plan['micro_a_reordered'] = True
        return chosen

    def metadata(self):
        return dict(super().metadata(), micro_a=dict(definition='new_certified_prefix_minimax_regret',
                    decisions=self.a_decisions))
