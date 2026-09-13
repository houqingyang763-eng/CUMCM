"""只从可见历史抽取相容 Q3 剩余环境，不接收真实 Scenario。"""
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "b_adaptive_q3"))
import geometry as g
from simulation import LocalEnvironment, Scenario, Source


class ConditionalEnvironment(LocalEnvironment):
    def __init__(self, scenario, state):
        super().__init__(scenario)
        self.position = state.position
        self.channel = state.measuring_channel
        self.virtual_time_s = state.virtual_time_s
        self.historical_measurements = {(j, tuple(q)): (result, bearing)
            for j, c in state.channels.items() for q, result, bearing in c.observations}

    def act(self, action):
        response = super().act(action)
        # 误差场在已访问位置条件化；不能重新随机化同一地点的读数。
        if action["kind"] == "measure" and action["channel"] not in self.cleared:
            old = self.historical_measurements.get((action["channel"], tuple(action["position"])))
            if old:
                result, bearing = old
                assert response["measure_result"] == result, "抽样源与历史接收/near 不符"
                if result == "direction":
                    response["svd_deg"] = bearing
        return response


def radial_interval(c, point):
    if math.hypot(*point) > 1800 or not c.compatible(point):
        return None
    lower, upper = 1000.0, 1500.0
    for q, result, bearing in c.observations:
        d = g.distance(point, q)
        if result == "no_signal":
            upper = min(upper, d-1e-6)
        else:
            lower = max(lower, d)
            if result == "near" and d > 5:
                return None
            if result == "direction":
                if d <= 5:
                    return None
                true = math.degrees(math.atan2(point[1]-q[1], point[0]-q[0]))
                if abs(g.angle_delta(true, bearing)) > 1.005 + 1e-9:
                    return None
    return (lower, upper) if lower <= upper else None


def polygon_draw(poly, rng):
    if len(poly) < 3:
        return g.center(poly)
    a = poly[0]
    triangles = [(a, poly[i], poly[i+1]) for i in range(1, len(poly)-1)]
    weights = [abs(g.cross(g.sub(b, a), g.sub(c, a))) for a, b, c in triangles]
    if sum(weights) <= 1e-12:
        return g.center(poly)
    a, b, c = rng.choices(triangles, weights=weights)[0]
    u, v = rng.random(), rng.random()
    if u+v > 1:
        u, v = 1-u, 1-v
    return g.add(a, g.add(g.mul(g.sub(b, a), u), g.mul(g.sub(c, a), v)))


def sample_source(c, rng, attempts=240):
    # 从当前外包集合抽取后，再用真实圆域、全部观测和半径相容性拒绝。
    cells = c.possible_cells() if c.first is not None else []
    polys = [cell["polygon"] for cell in cells] or [c.polygon]
    weights = [max(1e-12, g.area(p)) for p in polys]
    for _ in range(attempts):
        p = polygon_draw(rng.choices(polys, weights=weights)[0], rng)
        interval = radial_interval(c, p)
        if interval:
            lo, hi = interval
            return Source(c.channel, p, rng.uniform(lo, hi))
    return None


def sample_environment(state, seed, count_mode="random"):
    rng = random.Random(seed)
    active = []
    possible_unknown = []
    for c in state.channels.values():
        if c.status == "found":
            source = sample_source(c, rng, 600)
            if source is None:
                return None
            active.append(source)
        elif c.status == "unknown":
            source = sample_source(c, rng)
            if source:
                possible_unknown.append(source)
    seen = len(state.ever_seen)
    minimum, maximum = max(0, 10-seen), min(16-seen, len(possible_unknown))
    if minimum > maximum:
        return None
    # 源数量与位置先验是团队假设，不能从实际测试案例读取数量或种子。
    if count_mode == "minimum":
        count = minimum
    elif count_mode == "maximum":
        count = maximum
    elif count_mode == "random":
        count = rng.randint(minimum, maximum)
    else:
        raise ValueError(count_mode)
    selected = rng.sample(possible_unknown, count)
    scenario = Scenario(f"conditional_{seed}", seed, "conditional", "hashed", tuple(active+selected))
    return ConditionalEnvironment(scenario, state)
