"""预先固定的自建混合源案例；全部真值仅供本地环境与事后审计。

这里的布局、源类型比例、朝向及空间误差场均为团队假设，不能代表
官方隐藏案例分布。四组使用互不重叠的种子，不能把开发最优当泛化。
"""
import math
import random

import common
from simulation import Scenario, Source

SEEDS = {"smoke": 941000, "develop": 942000, "holdout": 943000, "pressure": 944000}
COUNTS = {"smoke": 4, "develop": 12, "holdout": 24, "pressure": 8}


def validate_scene(scene):
    if not 10 <= len(scene.sources) <= 16:
        raise ValueError("整局场景必须有10至16个源")
    channels = [s.channel for s in scene.sources]
    if len(channels) != len(set(channels)) or any(type(j) is not int or not 1 <= j <= 20 for j in channels):
        raise ValueError("源频道必须为1至20内互异整数")
    directions = [s.orientation for s in scene.sources]
    if not any(a is None for a in directions) or not any(a is not None for a in directions):
        raise ValueError("第四问必须同时含有全向和定向源")
    for s in scene.sources:
        if len(s.position) != 2 or not all(math.isfinite(v) for v in s.position):
            raise ValueError("非法源坐标")
        if math.hypot(*s.position) > 1800 + 1e-8 or not 1000 <= s.radius <= 1500:
            raise ValueError("源位置或接收半径超出题面")
        if s.orientation is not None and not math.isfinite(s.orientation):
            raise ValueError("非法发射方向")
    return scene


def generate_case(seed, layout="uniform", noise="smooth", direction="random",
                  directional_fraction=0.5, radius_mode="mixed", source_count=None,
                  split="custom", rotation_deg=0.0):
    rng = random.Random(seed)
    n = source_count or 10 + seed % 7
    channels = rng.sample(range(1, 21), n)
    nd = max(1, min(n - 1, round(n * directional_fraction)))
    directional = set(rng.sample(channels, nd))
    positions = []
    for i in range(n):
        angle = rng.uniform(0, 2 * math.pi)
        if layout == "uniform":
            radius = 1800 * math.sqrt(rng.random())
            q = (radius * math.cos(angle), radius * math.sin(angle))
        elif layout in ("edge", "boundary"):
            angle = 2 * math.pi * (i + .25) / n + math.radians(rotation_deg)
            radius = 1800.0 if layout == "boundary" else 1790 + 10 * rng.random()
            q = (radius * math.cos(angle), radius * math.sin(angle))
        elif layout == "cluster":
            center = ((i % 3 - 1) * 1050, (i % 2 - .5) * 350)
            q = (center[0] + rng.uniform(-90, 90), center[1] + rng.uniform(-90, 90))
        elif layout == "line":
            x, y = rng.uniform(-1790, 1790), rng.uniform(-2, 2)
            a = math.radians(rotation_deg)
            q = (x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a))
        elif layout == "central":
            radius = 300 * math.sqrt(rng.random())
            q = (radius * math.cos(angle), radius * math.sin(angle))
        else:
            raise ValueError(layout)
        positions.append(q)
    sources = []
    for i, (channel, q) in enumerate(zip(channels, positions)):
        radial = math.degrees(math.atan2(q[1], q[0]))
        orientation = None
        if channel in directional:
            if direction == "random":
                orientation = rng.uniform(0, 360)
            elif direction == "outward":
                orientation = radial % 360
            elif direction == "inward":
                orientation = (radial + 180) % 360
            elif direction == "tangent":
                orientation = (radial + (90 if i % 2 else -90)) % 360
            elif direction == "aligned":
                orientation = (rotation_deg + (0 if i % 2 else 180)) % 360
            else:
                raise ValueError(direction)
        if radius_mode == "minimum":
            reception = 1000.0
        elif radius_mode == "maximum":
            reception = 1500.0
        elif radius_mode == "mixed":
            reception = (1000.0, 1500.0, rng.uniform(1000, 1500))[i % 3]
        else:
            raise ValueError(radius_mode)
        sources.append(Source(channel, q, reception, orientation))
    name = f"{split}_{seed}_{layout}_{direction}_{noise}"
    return validate_scene(Scenario(name, seed, f"{layout}_{direction}_{radius_mode}_d{nd}of{n}", noise, tuple(sources)))


def build_cases(split="smoke", limit=None, seed_offset=0):
    if split not in SEEDS:
        raise ValueError(f"未知数据划分: {split}")
    result = []
    for i in range(COUNTS[split]):
        kwargs = dict(seed=SEEDS[split] + seed_offset + i, split=split)
        if split == "pressure":
            layouts = ("boundary", "edge", "boundary", "line", "line", "central", "cluster", "boundary")
            directions = ("outward", "tangent", "aligned", "aligned", "random", "outward", "tangent", "outward")
            kwargs.update(layout=layouts[i], direction=directions[i], noise=("biased", "hashed")[i % 2],
                          directional_fraction=(.9, .5, .25, .9)[i % 4], radius_mode="minimum",
                          source_count=10 if i % 2 == 0 else 16, rotation_deg=17 + i * 13)
        else:
            kwargs.update(layout=("uniform", "edge", "cluster", "line")[i % 4],
                          direction=("random", "outward", "tangent", "aligned")[(i + i // 4) % 4],
                          noise=("smooth", "biased", "hashed")[(i + i // 4) % 3],
                          directional_fraction=(.25, .5, .75, .9)[(i + i // 3) % 4],
                          radius_mode=("mixed", "minimum", "maximum")[(i // 4) % 3],
                          rotation_deg=11 * i)
        result.append(generate_case(**kwargs))
    return result[:limit] if limit is not None else result
