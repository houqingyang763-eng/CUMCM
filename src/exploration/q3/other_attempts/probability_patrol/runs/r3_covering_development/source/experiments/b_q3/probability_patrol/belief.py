"""未知频道的条件发现概率：位置积分，解析消去固定接收半径。

工作假设：该频道确有一个源；X 按面积均匀分布于半径 1800 m 圆域，
R 独立且均匀分布于 [1000, 1500] m，同一源的 R 不随测量改变。
这里只条件于 channel_state.observations 中全部 no_signal 反馈，不拟合角误差。
输出不是频道存在概率，不是官方生成规律，也不是全清/连续覆盖证书。

一个位置 x 的历史相容 R 区间是 [1000, U(x))，其中
U(x)=min(1500, min_历史阴性点 ||x-p||)。新区间再要求 R>=||x-q||。
比值积分用固定随机位置近似；重用同一云可稳定候选点比较。
依赖 numpy，不导入 LocalEnvironment、Source 或策略。
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np


DOMAIN_RADIUS_M = 1800.0
MIN_RADIUS_M = 1000.0
MAX_RADIUS_M = 1500.0
DEFAULT_SEED = 260912053


class InsufficientPosteriorMass(ValueError):
    """位置样本未捕获相容质量；不能据此宣布该频道不存在。"""


@dataclass(frozen=True)
class DiscoveryEstimate:
    probability: float
    standard_error: float
    history_likelihood: float
    joint_discovery_mass: float
    effective_samples: float
    positive_location_samples: int
    samples: int

    @property
    def low_effective_sample_size(self) -> bool:
        """仅为采样诊断提示，不是接受/拒绝策略的阈值。"""
        return self.effective_samples < 32


def _point(value):
    if len(value) != 2:
        raise ValueError("坐标必须含两个分量")
    q = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in q):
        raise ValueError("坐标必须有限")
    return q


def _negative_positions(channel_state):
    if getattr(channel_state, "status", "unknown") != "unknown":
        raise ValueError("此模块仅用于 status=unknown 的频道")
    points = set()
    for observation in channel_state.observations:
        position, result, _ = observation
        if result != "no_signal":
            raise ValueError("未知源模块不能忽略正检测或测向反馈")
        points.add(_point(position))
    # 重复测同一位置不会贡献独立的半径条件；次序也不改变条件事件。
    return tuple(sorted(points))


class UnknownDiscoveryBelief:
    """固定位置样本和有限历史缓存，适合比较一批候选停测点。

estimate 返回比值积分及诊断量；estimate_many 使用同一位置样本。
history_likelihood 返回 P(历史全无信号 | 该频道存在)，绝非 P(频道存在)。
历史似然接近零时，条件估计可能不稳定；零采样质量时 estimate 明确抛错。
"""

    def __init__(self, samples=4096, seed=DEFAULT_SEED, cache_size=64):
        if isinstance(samples, bool) or not isinstance(samples, (int, np.integer)) or samples < 2:
            raise ValueError("samples 必须为至少 2 的整数")
        if not isinstance(cache_size, int) or cache_size < 1:
            raise ValueError("cache_size 必须为正整数")
        self.samples = int(samples)
        self.seed = int(seed)
        self.cache_size = cache_size
        rng = np.random.default_rng(self.seed)
        radius = DOMAIN_RADIUS_M * np.sqrt(rng.random(self.samples))
        angle = rng.uniform(0.0, 2 * math.pi, self.samples)
        self._xy = np.column_stack((radius * np.cos(angle), radius * np.sin(angle)))
        self._cache = OrderedDict()

    def _context(self, channel_state):
        key = _negative_positions(channel_state)
        if key in self._cache:
            self._cache.move_to_end(key)
            return key, self._cache[key]
        upper = np.full(self.samples, MAX_RADIUS_M)
        for px, py in key:
            distance = np.hypot(self._xy[:, 0] - px, self._xy[:, 1] - py)
            upper = np.minimum(upper, distance)
        widths = np.maximum(upper - MIN_RADIUS_M, 0.0)
        total = float(widths.sum())
        squares = float(widths @ widths)
        effective = total * total / squares if squares > 0.0 else 0.0
        context = upper, widths, total, effective
        self._cache[key] = context
        while len(self._cache) > self.cache_size:
            self._cache.popitem(last=False)
        return key, context

    def history_likelihood(self, channel_state):
        _, (_, _, total, _) = self._context(channel_state)
        return total / (self.samples * (MAX_RADIUS_M - MIN_RADIUS_M))

    def estimate(self, channel_state, q):
        q = _point(q)
        key, (upper, widths, total, effective) = self._context(channel_state)
        if total <= 0.0:
            raise InsufficientPosteriorMass(
                "没有采样到与全部无信号反馈相容的质量；增大样本或使用几何核验，不能据此判 absent"
            )
        if q in key:
            # 固定源和固定半径下，同位置此前无信号，重测发现的概率严格为零。
            numerator = np.zeros(self.samples)
        else:
            distance = np.hypot(self._xy[:, 0] - q[0], self._xy[:, 1] - q[1])
            numerator = np.maximum(upper - np.maximum(MIN_RADIUS_M, distance), 0.0)
        numerator_total = float(numerator.sum())
        probability = min(1.0, max(0.0, numerator_total / total))
        # iid 位置 Monte Carlo 比值估计的 delta-method 标准误，不是有限样本保证。
        residual = numerator - probability * widths
        mean_width = total / self.samples
        variance = float(residual @ residual) / (self.samples - 1)
        standard_error = math.sqrt(variance / self.samples) / mean_width
        scale = self.samples * (MAX_RADIUS_M - MIN_RADIUS_M)
        return DiscoveryEstimate(
            probability=probability,
            standard_error=standard_error,
            history_likelihood=total / scale,
            joint_discovery_mass=numerator_total / scale,
            effective_samples=effective,
            positive_location_samples=int(np.count_nonzero(widths)),
            samples=self.samples,
        )

    def estimate_many(self, channel_state, points):
        return [self.estimate(channel_state, q) for q in points]


@lru_cache(maxsize=8)
def _default_belief(samples, seed):
    return UnknownDiscoveryBelief(samples=samples, seed=seed)


def unknown_discovery_probability(channel_state, q, samples=4096, seed=DEFAULT_SEED):
    """标量便捷接口；低后验质量诊断请使用 UnknownDiscoveryBelief.estimate。"""
    return _default_belief(samples, seed).estimate(channel_state, q).probability
