"""从阳性接收距离推导可靠半径，继承整段完成成本的 Q3 选点。"""
from dataclasses import dataclass
import math

from task_cost import CompletionCostConfig, CompletionCostPolicy
from q2_geometry import guaranteed_reception
import geometry as g


@dataclass(frozen=True)
class ReceptionConfig(CompletionCostConfig):
    representative_limit: int = 7
    history_offsets: tuple = ((300., 800.), (500., 800.), (750., 600.), (1000., 350.))


class ReceptionPolicy(CompletionCostPolicy):
    def __init__(self, config=None):
        super().__init__(config or ReceptionConfig())
        self.stats = dict(expanded_candidates=0, beyond_1000_representatives=0)

    @staticmethod
    def positive_positions(c):
        return [q for q, result, _ in c.observations if result in ("direction", "near")]

    @staticmethod
    def radius_lower(c, source_position):
        return max([1000.] + [g.distance(source_position, q)
                   for q in ReceptionPolicy.positive_positions(c)])

    def candidate_positions(self, state):
        points = super().candidate_positions(state)
        for c in state.channels.values():
            if c.status != "found" or c.first is None or c.circle()[1] <= 20 - 1e-5:
                continue
            origin, e, n = c.strip_axes()
            history = self.positive_positions(c)
            # 只在初次定位阶段补充侧向候选；后期复用已有近距离交会点。
            if len(history) != 1:
                continue
            for along, side in self.config.history_offsets:
                for sign in (-1, 1):
                    q = g.add(origin, g.add(g.mul(e, along), g.mul(n, side * sign)))
                    if g.distance(q, (0, 0)) > self.config.domain_radius_m:
                        continue
                    if guaranteed_reception(c.support(), q, history):
                        points.append(q)
                        self.stats["expanded_candidates"] += 1
        return list(dict.fromkeys(tuple(q) for q in points))

    def utility(self, c, q, mask):
        if c.status != "found" or c.circle()[1] <= 20 - 1e-5 or q in c.measured:
            return super().utility(c, q, mask)
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
            distance = g.distance(q, p)
            if distance > self.radius_lower(c, p) - 1e-6:
                gains.append(0.)
                continue
            if distance > 1000:
                self.stats["beyond_1000_representatives"] += 1
            if distance <= 5:
                gains.append(max(0., before - 5.))
                continue
            bearing = math.degrees(math.atan2(p[1] - q[1], p[0] - q[0]))
            after = []
            for error in self.config.error_samples:
                poly = g.wedge(c.support(), q, bearing + error)
                if poly:
                    after.append(self.remaining_work(c, poly))
            gains.append(max(0., before - sum(after) / len(after)) if after else 0.)
        self.utility_calls += 1
        value = self.config.localization_weight * min(self.config.work_gain_cap_s, sum(gains) / len(gains))
        if cache is not None:
            cache[q] = value
        return value
