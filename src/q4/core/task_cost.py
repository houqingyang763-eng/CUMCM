"""Q3 任务工作量策略：仅使用公开历史，复用冻结几何与全清证明。"""
from dataclasses import dataclass
import math
import geometry as g
from policy import BasePolicy, Config


@dataclass(frozen=True)
class TaskCostConfig(Config):
    discovery_value_s: float = 120.0
    terminal_value_s: float = 75.0
    detour_weight: float = 0.5
    error_samples: tuple = (-1.0, 0.0, 1.0)
    representative_limit: int = 5
    work_gain_cap_s: float = 240.0
    min_work_gain_s: float = 0.25
    approach_offsets_m: tuple = (60.0, 120.0)


class TaskCostPolicy(BasePolicy):
    """测向收益采用剩余清除格工作量的下降，费用加入去往任务的绕路。"""

    def __init__(self, config=None, reference_only=False):
        super().__init__(config or TaskCostConfig(), reference_only)
        self.last_candidates = []
        self._features = {}
        self._utility_cache = {}
        self._channel_stamps = {}

    @staticmethod
    def _cell_span(c, poly):
        """投影包围盒保守保留已有格；仅作工作量启发，不写入状态。"""
        if not poly:
            return 0, 0.0
        if c.first is None:
            return 1, 0.0
        origin, e, n = c.strip_axes()
        u = [g.dot(g.sub(p, origin), e) for p in poly]
        v = [g.dot(g.sub(p, origin), n) for p in poly]
        lo, hi, vlo, vhi = min(u), max(u), min(v), max(v)
        width = g.STRIP_HALF_WIDTH
        retained = [cell for cell in c.possible_cells()
                    if 30 * cell["index"][1] <= hi + 1e-6
                    and 30 * (cell["index"][1] + 1) >= lo - 1e-6
                    and ((cell["index"][0] == 0 and vlo <= 1e-6)
                         or (cell["index"][0] == 1 and vhi >= -1e-6))]
        if not retained:
            return 1, 0.0
        row_counts = [sum(cell["index"][0] == row for cell in retained) for row in (0, 1)]
        # 沿原始两行扫格的路程估计，不将投影格数解释为后验概率。
        span = max(0.0, hi - lo) * sum(n > 0 for n in row_counts)
        if all(row_counts):
            span += width
        return len(retained), span

    def remaining_work(self, c, poly=None):
        """从局部区域开始的清除工作估计，单位秒；不是时间上界。"""
        poly = c.support() if poly is None else poly
        if not poly:
            return 0.0
        _, radius = g.enclosing_circle(poly)
        if radius <= 20 - 1e-5:
            return 5.0
        count, span = self._cell_span(c, poly)
        # 未知格内位置采用半程扫格代理；最后一次成功仍计 5 秒。
        return 5.0 + 0.5 * (3.0 * max(0, count - 1) + span / 5.0)

    def _representatives(self, c):
        poly = c.support()
        proposed = [g.center(poly), c.circle()[0]]
        if poly:
            a, b = max(((a, b) for a in poly for b in poly), key=lambda ab: g.distance(*ab))
            proposed.extend(g.add(a, g.mul(g.sub(b, a), t)) for t in (.15, .35, .65, .85))
        proposed.extend(g.center(cell["polygon"]) for cell in c.possible_cells()[::max(1, len(c.possible_cells()) // 4)])
        result = []
        for p in proposed:
            if c.compatible(p) and not any(g.distance(p, old) < 1e-5 for old in result):
                result.append(p)
        return result[:self.config.representative_limit]

    def candidate_positions(self, state):
        points = super().candidate_positions(state)
        for c in state.channels.values():
            if c.status != "found" or c.circle()[1] <= 20 - 1e-5:
                continue
            center, radius = c.circle()
            direction = g.sub(center, state.position)
            dist = math.hypot(*direction)
            if dist > 1e-6:
                e = g.mul(direction, 1 / dist)
                n = (-e[1], e[0])
                # 接近点可利用近距离下更窄的绝对角度条带；两侧点避免共线交会。
                for remain in (80.0, 180.0, 350.0):
                    if dist > remain:
                        q = g.sub(center, g.mul(e, remain))
                        points.append(q)
                        for offset in self.config.approach_offsets_m:
                            points.extend(g.add(q, g.mul(n, sign * offset)) for sign in (-1, 1))
            # 由现有区域的包围圆推导的可靠接收位置：距离圆心 <= 1000-r。
            # 这只生成候选；最终证据仍由状态反馈更新。
            if radius < 950 and dist > 0:
                q = g.add(center, g.mul(g.sub(state.position, center), min(1.0, (990 - radius) / dist)))
                points.append(q)
        unique = {}
        for q in points:
            if g.distance(q, (0, 0)) <= self.config.domain_radius_m:
                unique.setdefault((round(q[0], 5), round(q[1], 5)), q)
        return list(unique.values())

    def _prepare(self, state):
        self._features = {}
        for j, c in state.channels.items():
            stamp = (id(c), c.status, len(c.observations), len(c.exclusions), c.near_position)
            if self._channel_stamps.get(j) != stamp:
                self._utility_cache[j] = {}
                self._channel_stamps[j] = stamp
            if c.status == "found":
                self._features[j] = (self.remaining_work(c), self._representatives(c))

    def utility(self, c, q, mask):
        if c.status in ("absent", "cleared") or q in c.measured:
            return 0.0
        if c.status == "unknown":
            gain = (c.sample_mask & mask).bit_count() / len(g.GRID)
            due = any(i not in c.anchors_missed and g.distance(q, a) < 1e-6 for i, a in enumerate(g.ANCHORS))
            return self.config.discovery_weight * self.config.discovery_value_s * (gain + (.015 if due else 0))
        if c.circle()[1] <= 20 - 1e-5:
            return 0.0
        cache = self._utility_cache.get(c.channel)
        if cache is not None and q in cache:
            return cache[q]
        before, reps = self._features.get(c.channel, (None, None))
        if before is None:
            before, reps = self.remaining_work(c), self._representatives(c)
        if not reps:
            return 0.0
        gains = []
        for p in reps:
            # 只给 1000 米以内的可靠接收计收益；1000—1500 米不假设概率分布。
            if g.distance(q, p) > 1000:
                gains.append(0.0)
                continue
            if g.distance(q, p) <= 5:
                gains.append(max(0.0, before - 5.0))
                continue
            bearing = math.degrees(math.atan2(p[1] - q[1], p[0] - q[0]))
            after_work = []
            for error in self.config.error_samples:
                poly = g.wedge(c.support(), q, bearing + error)
                if poly:
                    after_work.append(self.remaining_work(c, poly))
            gain = max(0.0, before - sum(after_work) / len(after_work)) if after_work else 0.0
            gains.append(gain)
        self.utility_calls += 1
        value = self.config.localization_weight * min(self.config.work_gain_cap_s, sum(gains) / len(gains))
        if cache is not None:
            cache[q] = value
        return value

    def _detour(self, state, q, channels):
        found = [state.channels[j] for j in channels if state.channels[j].status == "found"]
        if not found:
            return 0.0
        move = g.distance(state.position, q)
        return min(max(0.0, move + g.distance(q, c.circle()[0]) - g.distance(state.position, c.circle()[0])) / 5
                   for c in found)

    def choose(self, state):
        if state.complete:
            return None
        if self.reference_only or self.fallback_started or state.virtual_time_s >= self.config.adaptive_virtual_budget_s or state.actions >= self.config.adaptive_action_limit:
            return self.fallback(state)
        self._prepare(state)
        best_score, best = -1.0, None
        self.last_candidates = []
        for c in state.channels.values():
            if c.status != "found":
                continue
            if c.near_position is not None:
                return self.action("clear", c.near_position, c.channel, "task_near_clear")
            q, radius = c.circle()
            if radius <= 20 - 1e-5:
                score = (self.config.terminal_value_s + 5) / (g.distance(q, state.position) / 5 + 5)
                if score > best_score:
                    best_score, best = score, self.action("clear", q, c.channel, "task_certified_clear", enclosure_radius_m=radius)
        for q in self.candidate_positions(state):
            mask = g.coverage_mask(q)
            items = sorted(((self.utility(c, q, mask), j) for j, c in state.channels.items()), reverse=True)
            gain, selected = 0.0, []
            move_s = g.distance(q, state.position) / 5
            for value, j in items:
                if value < self.config.min_work_gain_s:
                    continue
                gain += value
                selected.append(j)
                switches = len(selected) - int(state.measuring_channel in selected)
                detour = self._detour(state, q, selected)
                cost = move_s + 5 * len(selected) + switches + self.config.detour_weight * detour
                score = gain / cost
                if score > best_score:
                    order = ([state.measuring_channel] + [k for k in selected if k != state.measuring_channel]
                             if state.measuring_channel in selected else list(selected))
                    best_score = score
                    best = self.action("measure", q, order[0], "task_work_batch", planned_channels=order,
                                       heuristic_score=score, estimated_work_saved_s=gain, detour_s=detour)
        return best if best is not None else self.fallback(state)


@dataclass(frozen=True)
class CompletionCostConfig(TaskCostConfig):
    current_probe_ratio: float = 1.2


class CompletionCostPolicy(TaskCostPolicy):
    """比较先测后清与现在扫格的预计整段完成费用；小区域允许安全试清。"""

    def __init__(self, config=None, reference_only=False):
        super().__init__(config or CompletionCostConfig(), reference_only)

    def choose(self, state):
        if state.complete:
            return None
        if self.reference_only or self.fallback_started or state.virtual_time_s >= self.config.adaptive_virtual_budget_s or state.actions >= self.config.adaptive_action_limit:
            return self.fallback(state)
        self._prepare(state)
        found = [c for c in state.channels.values() if c.status == "found"]
        near = [c for c in found if c.near_position is not None]
        if near:
            c = min(near, key=lambda c: g.distance(state.position, c.near_position))
            return self.action("clear", c.near_position, c.channel, "completion_near_clear")
        # 当前点无需移动的共享检测；其信息收益至少覆盖本次检测与切换费用。
        mask = g.coverage_mask(state.position)
        immediate = []
        for j, c in state.channels.items():
            gain = self.utility(c, state.position, mask)
            cost = 5 + int(j != state.measuring_channel)
            if gain >= self.config.current_probe_ratio * cost:
                immediate.append((gain / cost, j))
        if immediate:
            _, j = max(immediate)
            return self.action("measure", state.position, j, "completion_shared_probe")
        if not found:
            # 发现阶段沿用有限扫描收益排序与原始参考完成证明。
            return super().choose(state)
        points = self.candidate_positions(state)
        plans = []
        for c in found:
            center, radius = c.circle()
            before = self._features[c.channel][0]
            if radius <= 20 - 1e-5:
                q = center
                cost = g.distance(state.position, q) / 5 + 5
                plans.append((cost, self.action("clear", q, c.channel, "completion_certified_clear", enclosure_radius_m=radius)))
                continue
            cells = c.possible_cells()
            q = min(cells, key=lambda cell: g.distance(state.position, cell["position"]))["position"]
            cost = g.distance(state.position, q) / 5 + before
            plans.append((cost, self.action("clear", q, c.channel, "completion_cell_clear", estimated_completion_s=cost)))
            for q in points:
                if q in c.measured:
                    continue
                gain = self.utility(c, q, g.coverage_mask(q))
                if gain < self.config.min_work_gain_s:
                    continue
                # 三角路程显式计入：当前位置 -> 测点 -> 当前区域中心。
                # 后测中心仍以当前中心近似，所以这里只是任务排序的启发式。
                move = g.distance(state.position, q) / 5
                approach = g.distance(q, center) / 5
                cost = move + 5 + int(c.channel != state.measuring_channel) + approach + max(5, before - gain)
                plans.append((cost, self.action("measure", q, c.channel, "completion_measure_then_clear",
                                               estimated_completion_s=cost, estimated_work_saved_s=gain)))
        if not plans:
            return self.fallback(state)
        return min(plans, key=lambda item: item[0])[1]
