"""在固定下一发现节点的路上插入有价值的测向和可靠清除。"""
from sweep_policy import Q3SweepPolicy
from task_cost import CompletionCostPolicy, g


def insertion_cost(a, b, q):
    return max(0.0, g.distance(a, q) + g.distance(q, b) - g.distance(a, b))


def fixed_discovery_route(first, needed):
    """仅用仍待测的公开锚点生成最近邻开放路线。"""
    route = [first]
    remaining = set(needed) - {first}
    while remaining:
        point = min(remaining, key=lambda q: (g.distance(route[-1], q), q))
        route.append(point)
        remaining.remove(point)
    return route


def later_insertion_cost(route, q):
    """同一个可靠清除点在下一节点之后插入，或在发现路线尾部追加。"""
    return min([insertion_cost(a, b, q) for a, b in zip(route, route[1:])]
               + [g.distance(route[-1], q)])


class Q3DetourSweepPolicy(Q3SweepPolicy):
    """策略与配置沿用Sweep；没有新增待调系数，不把尝试清除当作成功。"""
    def __init__(self, config=None):
        super().__init__(config)
        self._reserved_anchor = None
        self.stats.update(detour_measures=0, detour_certified_clears=0, reserved_anchor_moves=0)

    def choose(self, state):
        unknown = [c for c in state.channels.values() if c.status == "unknown"]
        needed = [q for q in self.sweep_anchors if any(q not in c.measured for c in unknown)]
        if self._reserved_anchor not in needed:
            self._reserved_anchor = None
        action = super().choose(state)
        if action is None or action.get("reason") != "sweep_next_discovery_node":
            return action
        anchor = self._reserved_anchor or tuple(action["position"])
        channels = [c.channel for c in unknown if anchor not in c.measured]
        channel = state.measuring_channel if state.measuring_channel in channels else min(channels)
        if self._reserved_anchor is not None:
            action = self.action("measure", anchor, channel, "sweep_reserved_discovery_node")
        if not any(c.status == "found" for c in state.channels.values()):
            return action
        candidate = CompletionCostPolicy.choose(self, state)
        if candidate is None or self.fallback_started:
            return candidate
        q = tuple(candidate["position"])
        detour_s = insertion_cost(state.position, anchor, q) / 5
        c = state.channels[candidate["channel"]]
        accepted, details = False, {}
        if candidate["kind"] == "measure":
            gain = self.utility(c, q, g.coverage_mask(q))
            extra_cost = detour_s + 5 + int(c.channel != state.measuring_channel)
            # 同一个动作的预计剩余清除工作减少，支付它自身的操作与额外绕路。
            accepted = gain >= self.config.current_probe_ratio * extra_cost
            details = dict(estimated_work_saved_s=gain, extra_cost_s=extra_cost)
            reason = "sweep_detour_measure"
        else:
            support = c.support()
            reliable = c.status == "found" and bool(support) and all(g.distance(q, p) <= 20 - 1e-5 for p in support)
            route = fixed_discovery_route(anchor, needed)
            later_s = later_insertion_cost(route, q) / 5
            # 只比较同一已保证成功的清除任务；两条方案均有5秒成功清除，互相抵消。
            accepted = reliable and detour_s <= later_s + 1e-9
            details = dict(later_route_insertion_s=later_s, reliable_clear=reliable)
            reason = "sweep_detour_certified_clear"
        if accepted:
            self._reserved_anchor = anchor
            self.stats["sweep_measures"] -= 1  # super仅规划了这次锚点测量，并未执行。
            self.stats["detour_measures" if candidate["kind"] == "measure" else "detour_certified_clears"] += 1
            return dict(candidate, reason=reason, reserved_anchor=anchor, detour_s=detour_s, **details)
        self.stats["reserved_anchor_moves"] += int(self._reserved_anchor is not None)
        return action
