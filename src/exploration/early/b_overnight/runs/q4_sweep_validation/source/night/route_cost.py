"""已发现多目标的剩余开放路线：独立继承冻结 CompletionCost。"""
import copy
from dataclasses import dataclass
import math

from task_cost import CompletionCostConfig, CompletionCostPolicy, g


def nearest_neighbor_routes(points):
    """每个目标各作一次首站，生成实际访问全部点的开放路线。"""
    points = tuple(points)
    routes = []
    for first in range(len(points)):
        remaining = set(range(len(points))) - {first}
        order, length = [first], 0.0
        while remaining:
            previous = order[-1]
            nxt = min(remaining, key=lambda j: (g.distance(points[previous], points[j]), j))
            length += g.distance(points[previous], points[nxt])
            order.append(nxt)
            remaining.remove(nxt)
        routes.append((tuple(order), length))
    return routes


def open_route_length(start, points, routes=None):
    """返回可行中心访问路线的长度，不宣称 TSP 最优。"""
    points = tuple(points)
    if not points:
        return 0.0, ()
    routes = nearest_neighbor_routes(points) if routes is None else routes
    return min(((g.distance(start, points[order[0]]) + tail, order) for order, tail in routes), key=lambda item: item[0])


@dataclass(frozen=True)
class RouteCostConfig(CompletionCostConfig):
    nearest_candidate_limit: int = 36
    information_candidates_per_target: int = 2


class RouteCostPolicy(CompletionCostPolicy):
    """动作后总剩余路程 + 剩余清除工作，非当前收益/代价比。"""
    def __init__(self, config=None, reference_only=False):
        super().__init__(config or RouteCostConfig(), reference_only)
        self.stats = {"route_decisions": 0, "route_changes": 0, "route_candidates": 0}
        self.last_plan_scores = []
        self._route_cache = {}

    def _route(self, start, points):
        key = tuple(points)
        if key not in self._route_cache:
            self._route_cache[key] = nearest_neighbor_routes(key)
        return open_route_length(start, key, self._route_cache[key])

    def remaining_after_failed_clear(self, c, q):
        """独立复制公开状态，只预测失败分支；不写回真实信息。"""
        after = copy.deepcopy(c)
        after.exclusions.append((q, 20.0))
        after.invalidate()
        return after

    def estimated_total(self, state, action):
        q, j = tuple(action["position"]), action["channel"]
        target = state.channels[j]
        centers, work = [], 0.0
        removed, changed = False, None
        movement = g.distance(state.position, q) / 5.0
        if action["kind"] == "clear":
            # 只有覆盖全部保守支持点才能删去目标。否则显式保留失败后的工作。
            removed = all(g.distance(q, p) <= 20 - 1e-5 for p in target.support())
            operation = 5.0 if removed else 3.0
            if not removed:
                changed = self.remaining_after_failed_clear(target, q)
                if not changed.support():
                    return math.inf, {"reason": "noncertified_empty_failure_support"}
        else:
            operation = 5.0 + int(j != state.measuring_channel)
        for k, c in state.channels.items():
            if c.status != "found" or (k == j and removed):
                continue
            selected = changed if k == j and changed is not None else c
            centers.append(selected.circle()[0])
            remaining = self.remaining_work(selected)
            if k == j and action["kind"] == "measure":
                remaining = max(5.0, remaining - self.utility(c, q, g.coverage_mask(q)))
            work += remaining
        route_m, order = self._route(q, centers)
        total = movement + operation + route_m / 5.0 + work
        return total, {"current_move_s": movement, "operation_s": operation,
                       "remaining_route_m": route_m, "remaining_work_s": work,
                       "remaining_target_count": len(centers), "route_order": order,
                       "clear_assumption": "certified_success" if removed else ("failure" if action["kind"] == "clear" else None)}

    def choose(self, state):
        baseline = super().choose(state)
        if baseline is None or self.fallback_started:
            return baseline
        found = [c for c in state.channels.values() if c.status == "found"]
        # 未知发现和当前位置的共享检测保持原有进展规则；仅重排真正的多目标移动。
        if len(found) < 2 or g.distance(state.position, baseline["position"]) < 1e-6 or state.channels[baseline["channel"]].status != "found":
            return baseline
        self.stats["route_decisions"] += 1
        self._route_cache = {}
        all_points = self.candidate_positions(state)
        masks = {q: g.coverage_mask(q) for q in all_points}
        points = sorted(all_points, key=lambda q: g.distance(state.position, q))[:self.config.nearest_candidate_limit]
        points.append(tuple(baseline["position"]))
        points.extend(c.circle()[0] for c in found)
        for c in found:
            scored = sorted(all_points, key=lambda q: self.utility(c, q, masks[q]) / (g.distance(state.position, q) / 5 + 6), reverse=True)
            points.extend(scored[:self.config.information_candidates_per_target])
        points = list(dict.fromkeys(points))
        candidates = [baseline]
        for c in found:
            center, radius = c.circle()
            if radius <= 20 - 1e-5:
                candidates.append(self.action("clear", center, c.channel, "route_certified_clear", enclosure_radius_m=radius))
                continue
            if c.near_position is not None:
                candidates.append(self.action("clear", c.near_position, c.channel, "route_near_clear"))
                continue
            nearest_cell = min(c.possible_cells(), key=lambda cell: g.distance(state.position, cell["position"]))
            candidates.append(self.action("clear", nearest_cell["position"], c.channel, "route_trial_clear"))
            for q in points:
                if q not in c.measured and self.utility(c, q, masks.get(q, g.coverage_mask(q))) >= self.config.min_work_gain_s:
                    candidates.append(self.action("measure", q, c.channel, "route_measure"))
        scored = [(self.estimated_total(state, a), a) for a in candidates]
        self.stats["route_candidates"] += len(scored)
        (cost, detail), chosen = min(scored, key=lambda item: item[0][0])
        changed = chosen["kind"] != baseline["kind"] or chosen["channel"] != baseline["channel"] or g.distance(chosen["position"], baseline["position"]) > 1e-6
        self.stats["route_changes"] += int(changed)
        self.last_plan_scores = [{"kind": a["kind"], "position": a["position"], "channel": a["channel"],
                                  "estimated_total_s": result[0], **result[1]} for result, a in scored]
        return dict(chosen, route_total_s=cost, route_detail=detail, route_changed=changed,
                    completion_reason=baseline["reason"])
