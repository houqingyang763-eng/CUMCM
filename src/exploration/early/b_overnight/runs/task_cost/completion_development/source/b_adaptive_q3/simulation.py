"""自建局部模拟器，不读取官方程序、案例或隐藏数据。"""
import hashlib
import math
import random
from dataclasses import asdict, dataclass

from geometry import angle_delta, distance


@dataclass(frozen=True)
class Source:
    channel: int
    position: tuple
    radius: float
    orientation: float | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    seed: int
    layout: str
    noise: str
    sources: tuple

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        data = dict(data)
        data["sources"] = tuple(Source(s["channel"], tuple(s["position"]),
                                       s["radius"], s.get("orientation"))
                                for s in data["sources"])
        return cls(**data)


def noise_deg(seed, kind, q, channel):
    # 都是团队假设的外生误差场；不声称复刻官方未知的误差生成器。
    if kind == "zero":
        return 0.0
    if kind == "biased":
        return 1.0 if (seed + channel) % 2 else -1.0
    phase = ((seed * 31 + channel * 97) % 360) * math.pi / 180
    if kind == "smooth":
        return (0.6 * math.sin(q[0] / 170 + phase)
                + 0.4 * math.cos(q[1] / 230 - phase))
    if kind == "hashed":
        key = f"{seed}:{channel}:{q[0]:.9f}:{q[1]:.9f}".encode()
        v = int.from_bytes(hashlib.blake2b(key, digest_size=8).digest(), "big")
        return 2 * v / (2 ** 64 - 1) - 1
    raise ValueError(f"未知误差场 {kind}")


class LocalEnvironment:
    def __init__(self, scenario):
        self.scenario = scenario
        channels = [s.channel for s in scenario.sources]
        if len(channels) != len(set(channels)):
            raise ValueError("频道重复")
        self.sources = {s.channel: s for s in scenario.sources}
        self.cleared = set()
        self.position = (0.0, 0.0)
        self.channel = 1
        self.virtual_time_s = 0.0

    def act(self, action):
        kind, q, channel = action["kind"], tuple(action["position"]), action["channel"]
        if kind not in ("measure", "clear") or not isinstance(channel, int) or not 1 <= channel <= 20:
            raise ValueError("非法动作或频道")
        if len(q) != 2 or not all(math.isfinite(v) for v in q):
            raise ValueError("非法坐标")
        move = distance(self.position, q) / 5
        switch = int(kind == "measure" and channel != self.channel)
        source = self.sources.get(channel) if channel not in self.cleared else None
        d = distance(q, source.position) if source else math.inf
        response = {"accepted": True}
        if kind == "measure":
            self.channel = channel
            covered = source is not None and d <= source.radius
            if covered and source.orientation is not None:
                view = math.degrees(math.atan2(q[1] - source.position[1], q[0] - source.position[0]))
                covered = abs(angle_delta(view, source.orientation)) <= 90 + 1e-10
            if not covered:
                response["measure_result"] = "no_signal"
            elif d <= 5:
                response["measure_result"] = "near"
            else:
                bearing = math.degrees(math.atan2(source.position[1] - q[1], source.position[0] - q[0]))
                error = noise_deg(self.scenario.seed, self.scenario.noise, q, channel)
                response.update(measure_result="direction", svd_deg=round((bearing + error) % 360, 2) % 360)
            operation = 5
        else:
            success = d <= 20
            response["clear_result"] = "success" if success else "no_target_in_range"
            operation = 5 if success else 3
            if success:
                self.cleared.add(channel)
        self.position = q
        self.virtual_time_s += move + switch + operation
        response.update(virtual_time_s=self.virtual_time_s,
                        costs={"move_s": move, "switch_s": switch, "operation_s": operation})
        return response


def generate(seed, layout, noise):
    rng = random.Random(seed)
    n = 10 + seed % 7
    channels = rng.sample(range(1, 21), n)
    sources = []
    for i, channel in enumerate(channels):
        a = rng.uniform(0, 2 * math.pi)
        if layout == "uniform":
            r = 1800 * math.sqrt(rng.random())
            q = (r * math.cos(a), r * math.sin(a))
        elif layout == "edge":
            a = 2 * math.pi * (i / n + (0.5 / n if seed % 2 else 0))
            r = 1800 - rng.random() * 10
            q = (r * math.cos(a), r * math.sin(a))
        elif layout == "cluster":
            cluster = (i % 3 - 1) * 1100
            q = (cluster + rng.uniform(-80, 80), rng.uniform(-80, 80))
        elif layout == "line":
            q = (rng.uniform(-1790, 1790), rng.uniform(-3, 3))
        else:
            raise ValueError(layout)
        radius = 1000 if layout in ("edge", "line") else rng.uniform(1000, 1500)
        sources.append(Source(channel, q, radius))
    return Scenario(f"{layout}_{noise}_{seed}", seed, layout, noise, tuple(sources))
