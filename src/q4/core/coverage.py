"""Q3 阴性检测圆并集的连续覆盖证据；不访问环境或隐藏真值。

快速阶段使用保守方格界；宣称覆盖前用 Fraction 对全部证明叶格独立复核。
未覆盖格只是未知区域的外包，候选点与收益不参与不存在证明。
"""
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import math
import geometry as g
from state import InformationState


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    code: int = 1
    depth: int = 0

    @property
    def center(self):
        return ((self.x0 + self.x1) / 2, (self.y0 + self.y1) / 2)

    @property
    def area(self):
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    def children(self):
        x, y = self.center
        return tuple(Box(*bounds, 4 * self.code + i, self.depth + 1)
                     for i, bounds in enumerate(((self.x0, self.y0, x, y),
                                                  (x, self.y0, self.x1, y),
                                                  (self.x0, y, x, self.y1),
                                                  (x, y, self.x1, self.y1))))

    def farthest_distance(self, q):
        return math.hypot(max(abs(self.x0 - q[0]), abs(self.x1 - q[0])),
                          max(abs(self.y0 - q[1]), abs(self.y1 - q[1])))

    def nearest_distance(self, q):
        return math.hypot(max(self.x0 - q[0], 0, q[0] - self.x1),
                          max(self.y0 - q[1], 0, q[1] - self.y1))

    def point_in_domain(self, radius):
        """返回格内且在目标圆内的点；没有明显内点时返回 None。"""
        p = self.center
        if math.hypot(*p) <= radius:
            return p
        p = (min(self.x1, max(self.x0, 0.0)),
             min(self.y1, max(self.y0, 0.0)))
        return p if math.hypot(*p) <= radius else None


@dataclass(frozen=True)
class CoverageLeaf:
    box: Box
    kind: str
    circle_index: int = -1


@dataclass(frozen=True)
class CoverageCertificate:
    domain_radius_m: float
    exclusions: tuple
    leaves: tuple
    boxes_visited: int
    requested_depth: int
    safety_margin_m: float
    rational_verified: bool = False

    @property
    def unresolved(self):
        return tuple(leaf.box for leaf in self.leaves if leaf.kind == "unresolved")

    @property
    def complete(self):
        return not any(leaf.kind == "unresolved" for leaf in self.leaves)

    @property
    def area_upper_m2(self):
        return min(math.pi * self.domain_radius_m ** 2,
                   sum(box.area for box in self.unresolved))

    @property
    def statistics(self):
        return {"boxes_visited": self.boxes_visited,
                "leaf_count": len(self.leaves),
                "covered_leaves": sum(l.kind == "covered" for l in self.leaves),
                "outside_leaves": sum(l.kind == "outside" for l in self.leaves),
                "unresolved_leaves": len(self.unresolved),
                "max_leaf_depth": max((l.box.depth for l in self.leaves), default=0),
                "area_upper_m2": self.area_upper_m2,
                "rational_verified": self.rational_verified}

    def witness_points(self):
        """候选中心中确实尚未被排除的点；空列表不构成覆盖证明。"""
        points = []
        for box in self.unresolved:
            p = box.point_in_domain(self.domain_radius_m)
            if p is not None and all(g.distance(p, q) >= r for q, r in self.exclusions):
                points.append(p)
        return tuple(points)

    def to_dict(self, include_leaves=False):
        result = {"complete": self.complete, "domain_radius_m": self.domain_radius_m,
                  "exclusions": self.exclusions, "requested_depth": self.requested_depth,
                  "safety_margin_m": self.safety_margin_m, **self.statistics}
        if include_leaves:
            result["leaves"] = [dict(code=l.box.code, depth=l.box.depth,
                                      bounds=(l.box.x0, l.box.y0, l.box.x1, l.box.y1),
                                      kind=l.kind, circle_index=l.circle_index)
                                for l in self.leaves]
        return result


def verify_certificate(certificate, require_complete=False):
    """独立证明检查：四叉树完备分割 + 有理数严格圆内/圆外判据。

    Fraction 将输入浮点值当作精确二进制有理数，不复用快速距离判据。
    只验证已给证书，不检查题设是否允许这些阴性排除圆（由状态更新保证）。
    """
    F = Fraction
    radius2 = F(certificate.domain_radius_m) ** 2
    circles = [(F(q[0]), F(q[1]), F(r) ** 2) for q, r in certificate.exclusions]
    by_code = {leaf.box.code: leaf for leaf in certificate.leaves}
    if len(by_code) != len(certificate.leaves):
        raise AssertionError("证书存在重复叶格")
    consumed = set()

    def visit(expected):
        leaf = by_code.get(expected.code)
        if leaf is None:
            if expected.depth >= certificate.requested_depth:
                raise AssertionError("证书未完整覆盖根方格")
            for child in expected.children():
                visit(child)
            return
        if leaf.box != expected:
            raise AssertionError("叶格边界与其四叉树位置不一致")
        consumed.add(expected.code)
        x0, x1, y0, y1 = map(F, (expected.x0, expected.x1, expected.y0, expected.y1))
        if leaf.kind == "covered":
            if not 0 <= leaf.circle_index < len(circles):
                raise AssertionError("排除圆索引无效")
            x, y, r2 = circles[leaf.circle_index]
            if not all((a - x) ** 2 + (b - y) ** 2 < r2
                       for a in (x0, x1) for b in (y0, y1)):
                raise AssertionError("叶格并未严格全在排除圆内")
        elif leaf.kind == "outside":
            dx, dy = max(x0, 0, -x1), max(y0, 0, -y1)
            if dx ** 2 + dy ** 2 <= radius2:
                raise AssertionError("叶格并未严格全在目标圆外")
        elif leaf.kind != "unresolved" or require_complete:
            raise AssertionError("未知叶格或证书尚未覆盖完整区域")

    radius = certificate.domain_radius_m
    visit(Box(-radius, -radius, radius, radius))
    if consumed != set(by_code):
        raise AssertionError("证书存在被祖先覆盖的冗余叶格")
    return True


@lru_cache(maxsize=256)
def _build_coverage(exclusions, domain_radius, max_depth, min_depth, margin):
    leaves, visited = [], 0
    stack = [Box(-domain_radius, -domain_radius, domain_radius, domain_radius)]
    while stack:
        box = stack.pop()
        visited += 1
        if box.nearest_distance((0, 0)) > domain_radius + margin:
            leaves.append(CoverageLeaf(box, "outside"))
            continue
        covering = next((i for i, (q, r) in enumerate(exclusions)
                         if box.farthest_distance(q) < r - margin), None)
        if covering is not None:
            leaves.append(CoverageLeaf(box, "covered", covering))
            continue
        disjoint = all(box.nearest_distance(q) > r + margin for q, r in exclusions)
        if box.depth >= max_depth or (box.depth >= min_depth and disjoint):
            leaves.append(CoverageLeaf(box, "unresolved"))
        else:
            stack.extend(reversed(box.children()))
    result = CoverageCertificate(domain_radius, exclusions, tuple(leaves), visited,
                                 max_depth, margin)
    if result.complete:
        # 每个新的结束证据均真正执行独立验证；缓存复用已验证证书。
        verify_certificate(result, require_complete=True)
        result = CoverageCertificate(domain_radius, exclusions, tuple(leaves), visited,
                                     max_depth, margin, rational_verified=True)
    return result


def coverage_certificate(exclusions, domain_radius=1800.0, max_depth=8,
                         refinement_depth=12, min_depth=4, safety_margin_m=1e-5):
    """圆并集覆盖证书。未知时宁可保留；不能分辨的窄缝不会被判为空。

    exclusions 为 ((x,y), radius) 序列。默认先切到 14.06m 方格；仅当
    尚无明确未覆盖中心时继续细化，最多到 0.88m。深度上限只影响检出能力。
    """
    circles = tuple(sorted(set(((float(q[0]), float(q[1])), float(r)) for q, r in exclusions)))
    values = [domain_radius, safety_margin_m] + [v for q, r in circles for v in (*q, r)]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("覆盖输入必须有限")
    if domain_radius <= 0 or safety_margin_m <= 0 or any(r <= 0 for q, r in circles):
        raise ValueError("覆盖半径与安全余量必须为正")
    if not 0 <= min_depth <= max_depth <= refinement_depth <= 16:
        raise ValueError("四叉树深度范围无效")
    depth = max_depth
    result = _build_coverage(circles, float(domain_radius), depth, min_depth, safety_margin_m)
    while not result.complete and not result.witness_points() and depth < refinement_depth:
        depth = min(depth + 2, refinement_depth)
        result = _build_coverage(circles, float(domain_radius), depth, min_depth, safety_margin_m)
    return result


class CoverageInformationState(InformationState):
    """完整兼容冻结状态接口，只增强 Q3 未知频道的无信号排除证明。"""
    def __init__(self, coverage_depth=8, coverage_refinement_depth=12):
        super().__init__()
        self.coverage_depth = coverage_depth
        self.coverage_refinement_depth = coverage_refinement_depth
        self._coverage_by_channel = {}
        self.absence_reasons = {}

    def coverage(self, channel):
        if channel not in self._coverage_by_channel:
            c = self.channels[channel]
            circles = [(q, 1000.0) for q, result, _ in c.observations if result == "no_signal"]
            self._coverage_by_channel[channel] = coverage_certificate(
                circles, max_depth=self.coverage_depth,
                refinement_depth=self.coverage_refinement_depth)
        return self._coverage_by_channel[channel]

    def update(self, action, response):
        super().update(action, response)
        j = action["channel"]
        self._coverage_by_channel.pop(j, None)
        c = self.channels[j]
        if action["kind"] == "measure" and response.get("measure_result") == "no_signal":
            if c.status in ("unknown", "absent") and len(self.ever_seen) < 16:
                cert = self.coverage(j)
                if cert.complete:
                    assert cert.rational_verified
                    c.status = "absent"
                    self.absence_reasons[j] = "negative_disk_union"
                elif c.status == "absent":
                    # 冻结底座仍可依据已证明的七参照点定理结束。
                    self.absence_reasons[j] = "seven_anchors"
        if len(self.ever_seen) == 16:
            for j, c in self.channels.items():
                if c.status == "absent":
                    self.absence_reasons.setdefault(j, "maximum_source_count")

    def discovery_points(self, limit=24):
        """把剩余未知区域转为分散候选。输出不意味着这些点必有目标。"""
        if limit <= 0:
            return []
        certificates = []
        seen = set()
        for j, c in self.channels.items():
            if c.status != "unknown":
                continue
            cert = self.coverage(j)
            if cert.exclusions not in seen:
                seen.add(cert.exclusions)
                certificates.append(cert)
        candidates = {}
        for cert in certificates:
            for box in cert.unresolved:
                p = box.point_in_domain(cert.domain_radius_m)
                if p is not None and all(g.distance(p, q) >= r for q, r in cert.exclusions):
                    candidates[p] = max(candidates.get(p, 0), box.area)
            # 极窄未决区域可能没有未覆盖格中心；留近似候选供进一步检测。
            if not cert.witness_points():
                for box in cert.unresolved:
                    p = box.point_in_domain(cert.domain_radius_m)
                    if p is not None:
                        candidates[p] = max(candidates.get(p, 0), box.area)
        if not candidates:
            return []
        # 大格优先表示主要缺口；再用最远点覆盖保留多个空间方向。
        # 保留离当前位置最近点，避免小缺口被面积筛选完全淹没。
        pool = sorted(candidates, key=lambda p: (-candidates[p], p))[:max(128, limit * 8)]
        nearest = min(candidates, key=lambda p: g.distance(p, self.position))
        selected = [nearest]
        while len(selected) < limit and pool:
            p = max(pool, key=lambda p: min(g.distance(p, q) for q in selected))
            pool.remove(p)
            if p not in selected:
                selected.append(p)
        return selected

    def discovery_gain(self, channel, q):
        """下一次阴性检测可删除的外包格面积比例，仅供启发式排序。"""
        c = self.channels[channel]
        if c.status != "unknown" or q in c.measured:
            return 0.0
        cert = self.coverage(channel)
        # 全格覆盖面积可直接计入；方格跨越新圆边缘时不给部分面积奖励。
        removed = sum(box.area for box in cert.unresolved
                      if box.farthest_distance(q) < 1000.0 - cert.safety_margin_m)
        return min(1.0, removed / (math.pi * cert.domain_radius_m ** 2))


class CoveragePolicyMixin:
    """与 BasePolicy 或 TaskCostPolicy 组合；不改定位/清除规则。

    余留覆盖格会产生原 300m 收益网格未命中的小缺口，故仅在原未知收益
    已为零时补一个正收益。固定参照点仍保留，维持有限回退闭环。
    """
    coverage_candidate_limit = 12

    def choose(self, state):
        self._coverage_state = state
        return super().choose(state)

    def candidate_positions(self, state):
        points = list(super().candidate_positions(state))
        if hasattr(state, "discovery_points"):
            points.extend(state.discovery_points(limit=self.coverage_candidate_limit))
        unique = {}
        for q in points:
            if g.distance(q, (0, 0)) <= self.config.domain_radius_m:
                unique.setdefault((round(q[0], 5), round(q[1], 5)), q)
        return list(unique.values())

    def utility(self, c, q, mask):
        original = super().utility(c, q, mask)
        state = getattr(self, "_coverage_state", None)
        if original <= 1e-7 and c.status == "unknown" and state is not None:
            if hasattr(state, "discovery_gain"):
                return self.config.discovery_weight * state.discovery_gain(c.channel, q)
        return original
