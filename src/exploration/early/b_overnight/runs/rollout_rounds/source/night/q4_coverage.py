"""Q4 阴性点的方向无关连续排除：近邻测点凸包包围整个方格。"""
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import math

from coverage import Box, CoveragePolicyMixin
import geometry as g


@dataclass(frozen=True)
class Q4CoverageLeaf:
    box: Box
    kind: str
    hull_indices: tuple = ()


@dataclass(frozen=True)
class Q4CoverageCertificate:
    domain_radius_m: float
    reception_radius_m: float
    measurements: tuple
    leaves: tuple
    boxes_visited: int
    requested_depth: int
    safety_margin_m: float
    rational_verified: bool = False

    @property
    def complete(self):
        return not any(leaf.kind == "unresolved" for leaf in self.leaves)

    @property
    def unresolved(self):
        return tuple(leaf.box for leaf in self.leaves if leaf.kind == "unresolved")

    @property
    def area_upper_m2(self):
        return min(math.pi * self.domain_radius_m ** 2, sum(b.area for b in self.unresolved))

    @property
    def statistics(self):
        return dict(boxes_visited=self.boxes_visited, leaf_count=len(self.leaves),
                    surrounded_leaves=sum(l.kind == "surrounded" for l in self.leaves),
                    outside_leaves=sum(l.kind == "outside" for l in self.leaves),
                    unresolved_leaves=len(self.unresolved),
                    max_leaf_depth=max((l.box.depth for l in self.leaves), default=0),
                    area_upper_m2=self.area_upper_m2, rational_verified=self.rational_verified)

    def witness_points(self):
        points = []
        for box in self.unresolved:
            p = box.point_in_domain(self.domain_radius_m)
            if p is not None:
                nearby = [q for q in self.measurements if g.distance(q, p) < self.reception_radius_m]
                if not _strictly_inside(g.hull(nearby), (p,), self.safety_margin_m):
                    points.append(p)
        return tuple(points)

    def to_dict(self, include_leaves=False):
        result = dict(complete=self.complete, domain_radius_m=self.domain_radius_m,
                      reception_radius_m=self.reception_radius_m, measurements=self.measurements,
                      requested_depth=self.requested_depth, safety_margin_m=self.safety_margin_m,
                      **self.statistics)
        if include_leaves:
            result["leaves"] = [dict(code=l.box.code, depth=l.box.depth,
                                      bounds=(l.box.x0, l.box.y0, l.box.x1, l.box.y1),
                                      kind=l.kind, hull_indices=l.hull_indices)
                                for l in self.leaves]
        return result


def _corners(box):
    return ((box.x0, box.y0), (box.x1, box.y0), (box.x1, box.y1), (box.x0, box.y1))


def _strictly_inside(hull, points, margin):
    if len(hull) < 3:
        return False
    return all(g.cross(g.sub(b, a), g.sub(p, a)) > margin * max(1.0, g.distance(a, b))
               for a, b in zip(hull, hull[1:] + hull[:1]) for p in points)


def _surrounding_hull(box, measurements, reception_radius, margin):
    nearby = [q for q in measurements if box.farthest_distance(q) < reception_radius - margin]
    hull = g.hull(nearby)
    return hull if _strictly_inside(hull, _corners(box), margin) else None


def verify_q4_certificate(certificate, require_complete=False):
    """Fraction 独立复核每个叶格、精确凸包、距离与完整四叉划分。"""
    F = Fraction
    domain2 = F(certificate.domain_radius_m) ** 2
    reception2 = F(certificate.reception_radius_m) ** 2
    points = [(F(q[0]), F(q[1])) for q in certificate.measurements]
    by_code = {leaf.box.code: leaf for leaf in certificate.leaves}
    if len(by_code) != len(certificate.leaves):
        raise AssertionError("Q4 证书重复叶格")
    consumed = set()

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def exact_hull(ps):
        ps = sorted(set(ps))
        def half(seq):
            out = []
            for p in seq:
                while len(out) > 1 and cross(out[-2], out[-1], p) <= 0:
                    out.pop()
                out.append(p)
            return out
        return half(ps)[:-1] + half(list(reversed(ps)))[:-1] if len(ps) > 1 else ps

    def visit(expected):
        leaf = by_code.get(expected.code)
        if leaf is None:
            if expected.depth >= certificate.requested_depth:
                raise AssertionError("Q4 证书未覆盖完整根方格")
            for child in expected.children():
                visit(child)
            return
        if leaf.box != expected:
            raise AssertionError("Q4 叶格边界与四叉树不一致")
        consumed.add(expected.code)
        corners = [(F(x), F(y)) for x, y in _corners(expected)]
        if leaf.kind == "outside":
            dx = max(F(expected.x0), 0, -F(expected.x1))
            dy = max(F(expected.y0), 0, -F(expected.y1))
            if dx ** 2 + dy ** 2 <= domain2:
                raise AssertionError("Q4 叶格未严格在源位置圆域外")
        elif leaf.kind == "surrounded":
            if any(not 0 <= i < len(points) for i in leaf.hull_indices):
                raise AssertionError("Q4 凸包索引无效")
            selected = [points[i] for i in leaf.hull_indices]
            if not all((x - q[0]) ** 2 + (y - q[1]) ** 2 < reception2
                       for q in selected for x, y in corners):
                raise AssertionError("Q4 某个包围点距方格角点过远")
            hull = exact_hull(selected)
            if len(hull) < 3 or not all(cross(a, b, p) > 0
                                       for a, b in zip(hull, hull[1:] + hull[:1]) for p in corners):
                raise AssertionError("Q4 方格未严格位于阴性测点凸包内部")
        elif leaf.kind != "unresolved" or require_complete:
            raise AssertionError("Q4 证书类型未知或尚未完成")

    r = certificate.domain_radius_m
    visit(Box(-r, -r, r, r))
    if consumed != set(by_code):
        raise AssertionError("Q4 证书包含祖先已覆盖的多余叶格")
    return True


@lru_cache(maxsize=128)
def _build_q4_coverage(measurements, domain_radius, reception_radius, depth, min_depth, margin):
    leaves, visited = [], 0
    indices = {q: i for i, q in enumerate(measurements)}
    stack = [Box(-domain_radius, -domain_radius, domain_radius, domain_radius)]
    while stack:
        box = stack.pop()
        visited += 1
        if box.nearest_distance((0, 0)) > domain_radius + margin:
            leaves.append(Q4CoverageLeaf(box, "outside"))
            continue
        hull = _surrounding_hull(box, measurements, reception_radius, margin)
        if hull is not None:
            leaves.append(Q4CoverageLeaf(box, "surrounded", tuple(indices[q] for q in hull)))
            continue
        # 连最短方格距离都过远的点不可能参与该格内任何位置的包围。
        potentially_near = sum(box.nearest_distance(q) < reception_radius + margin for q in measurements)
        if box.depth >= depth or (box.depth >= min_depth and potentially_near < 3):
            leaves.append(Q4CoverageLeaf(box, "unresolved"))
        else:
            stack.extend(reversed(box.children()))
    result = Q4CoverageCertificate(domain_radius, reception_radius, measurements,
                                   tuple(leaves), visited, depth, margin)
    if result.complete:
        verify_q4_certificate(result, require_complete=True)
        result = Q4CoverageCertificate(domain_radius, reception_radius, measurements,
                                       tuple(leaves), visited, depth, margin, True)
    return result


def q4_coverage_certificate(measurements, domain_radius=1800.0, reception_radius=1000.0,
                            max_depth=7, refinement_depth=10, min_depth=3, safety_margin_m=1e-5):
    points = tuple(sorted(set((float(q[0]), float(q[1])) for q in measurements)))
    values = [domain_radius, reception_radius, safety_margin_m] + [v for q in points for v in q]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("Q4 覆盖输入必须有限")
    if min(domain_radius, reception_radius, safety_margin_m) <= 0:
        raise ValueError("Q4 覆盖半径与余量必须为正")
    if not 0 <= min_depth <= max_depth <= refinement_depth <= 14:
        raise ValueError("Q4 四叉树深度无效")
    depth = max_depth
    cert = _build_q4_coverage(points, float(domain_radius), float(reception_radius),
                              depth, min_depth, safety_margin_m)
    while not cert.complete and not cert.witness_points() and depth < refinement_depth:
        depth = min(depth + 2, refinement_depth)
        cert = _build_q4_coverage(points, float(domain_radius), float(reception_radius),
                                  depth, min_depth, safety_margin_m)
    return cert
