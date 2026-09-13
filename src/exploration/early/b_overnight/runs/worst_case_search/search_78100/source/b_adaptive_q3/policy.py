"""可配置基础策略；候选批次收益/费用排序，执行一步后重新计算。"""
import math
from dataclasses import asdict, dataclass

import geometry as g


@dataclass(frozen=True)
class Config:
    discovery_weight: float = 1.0
    localization_weight: float = 1.0
    clear_weight: float = 2.0
    offset_scale: float = 0.5
    min_offset_m: float = 60.0
    max_offset_m: float = 600.0
    # 原型人为限制：超额后复用同一状态，按有限清单完成；未自动调参。
    adaptive_virtual_budget_s: float = 6000.0
    adaptive_action_limit: int = 600
    domain_radius_m: float = 5000.0

    def to_dict(self):
        return asdict(self)


class BasePolicy:
    def __init__(self, config=None, reference_only=False):
        self.config = config or Config()
        self.reference_only = reference_only
        self.fallback_started = False
        self.fallback_channel = None
        self.utility_calls = 0

    @staticmethod
    def action(kind, q, channel, reason, **extra):
        return dict(kind=kind, position=tuple(q), channel=channel, reason=reason, **extra)

    def fallback(self, state):
        self.fallback_started = True
        near = [c for c in state.channels.values() if c.status == "found" and c.near_position is not None]
        if near:
            c = min(near, key=lambda c: g.distance(state.position, c.near_position))
            return self.action("clear", c.near_position, c.channel, "fallback_near")
        needed = [(g.distance(state.position, q) / 5 + 5 + int(j != state.measuring_channel), q, j)
                  for j, c in state.channels.items() if c.status == "unknown"
                  for i, q in enumerate(g.ANCHORS) if i not in c.anchors_missed]
        if needed:
            _, q, j = min(needed)
            return self.action("measure", q, j, "fallback_discovery")
        candidates = []
        for j, c in state.channels.items():
            if c.status != "found":
                continue
            q, r = c.circle()
            if r <= 20 - 1e-5:
                candidates.append((g.distance(state.position, q), q, j, "fallback_certified_clear"))
            else:
                # 每个目标沿原矩形两行蛇形序列完成；跳过已排除格。
                # 不在多个目标之间反复跳转，保留每目标有限路程界。
                cell = min(c.possible_cells(), key=lambda x: (x["index"][0],
                           x["index"][1] if x["index"][0] == 0 else -x["index"][1]))
                q = cell["position"]
                candidates.append((g.distance(state.position, q), q, j, "fallback_cell_clear"))
        if not candidates:
            raise AssertionError("未完成但无参考动作；几何状态异常")
        continuing = [item for item in candidates if item[2] == self.fallback_channel]
        _, q, j, reason = min(continuing or candidates)
        self.fallback_channel = j
        return self.action("clear", q, j, reason)

    def candidate_positions(self, state):
        points = [state.position] + list(g.ANCHORS)
        centers = []
        for c in state.channels.values():
            if c.status != "found":
                continue
            poly = c.support()
            if not poly:
                raise AssertionError("已发现目标的可能区域为空")
            q, _ = c.circle()
            centers.append(q)
            points.append(q)
            a, b = max(((a, b) for a in poly for b in poly), key=lambda pair: g.distance(*pair))
            length = g.distance(a, b)
            if length > 0:
                n = (-(b[1] - a[1]) / length, (b[0] - a[0]) / length)
                offset = min(self.config.max_offset_m, max(self.config.min_offset_m,
                                                          length * self.config.offset_scale))
                points.extend(g.add(q, g.mul(n, offset * factor)) for factor in (-1, -0.5, 0.5, 1))
        # 两个区域中心的折中点，给多频道共享路程提供有限候选。
        points.extend(g.mul(g.add(a, b), 0.5) for i, a in enumerate(centers)
                      for b in centers[i + 1:] if g.distance(a, b) <= 1600)
        unique = {}
        for q in points:
            if g.distance(q, (0, 0)) <= self.config.domain_radius_m:
                unique.setdefault((round(q[0], 5), round(q[1], 5)), q)
        return list(unique.values())

    def utility(self, c, q, mask):
        if c.status in ("absent", "cleared") or q in c.measured:
            return 0.0
        if c.status == "unknown":
            gain = (c.sample_mask & mask).bit_count() / len(g.GRID)
            # 网格漏掉边界也不能阻止参照点检查。
            anchor_due = any(i not in c.anchors_missed and g.distance(q, a) < 1e-6
                             for i, a in enumerate(g.ANCHORS))
            return self.config.discovery_weight * (gain + (0.015 if anchor_due else 0))
        if c.circle()[1] <= 20 - 1e-5:
            # 已能可靠清除，继续缩面积不能再算成定位收益。
            return 0.0
        poly = c.support()
        original_area = g.area(poly)
        if original_area < 1e-8:
            return 0.0
        # 用兼容代表点估算一次测向能缩小多少面积。它不是概率后验，
        # 也不参与可靠清除或停止证明；外层以后用整局成绩配置该规则。
        reps = [g.center(poly)] + poly[::max(1, len(poly) // 4)]
        reps = [p for p in reps if c.compatible(p)]
        if not reps:
            return 0.0
        gain = 0.0
        for p in reps:
            d = g.distance(q, p)
            if d > 1500:
                continue
            reception = 1.0 if d <= 1000 else (1500 - d) / 500
            bearing = math.degrees(math.atan2(p[1] - q[1], p[0] - q[0]))
            after = g.wedge(poly, q, bearing)
            gain += reception * max(0, 1 - g.area(after) / original_area)
        self.utility_calls += 1
        return self.config.localization_weight * gain / len(reps)

    def choose(self, state):
        if state.complete:
            return None
        if self.reference_only or self.fallback_started or state.virtual_time_s >= self.config.adaptive_virtual_budget_s or state.actions >= self.config.adaptive_action_limit:
            return self.fallback(state)
        best_score, best = -1.0, None
        for c in state.channels.values():
            if c.status != "found":
                continue
            if c.near_position is not None:
                return self.action("clear", c.near_position, c.channel, "near_clear")
            q, r = c.circle()
            if r <= 20 - 1e-5:
                score = self.config.clear_weight / (g.distance(q, state.position) / 5 + 5)
                if score > best_score:
                    best_score = score
                    best = self.action("clear", q, c.channel, "certified_clear", enclosure_radius_m=r)
        for q in self.candidate_positions(state):
            mask = g.coverage_mask(q)
            items = [(self.utility(c, q, mask), j) for j, c in state.channels.items()]
            items = sorted((x for x in items if x[0] > 1e-7), reverse=True)
            gain = 0.0
            selected = []
            move_s = g.distance(q, state.position) / 5
            for utility, j in items:
                gain += utility
                selected.append(j)
                switches = len(selected) - int(state.measuring_channel in selected)
                cost = move_s + 5 * len(selected) + switches
                score = gain / cost
                if score > best_score:
                    order = ([state.measuring_channel] + [j for j in selected if j != state.measuring_channel]
                             if state.measuring_channel in selected else list(selected))
                    best_score = score
                    best = self.action("measure", q, order[0], "adaptive_batch",
                                       planned_channels=order, heuristic_score=score)
        if best is None:
            return self.fallback(state)
        return best
