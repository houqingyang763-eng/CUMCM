"""第三问的保守几何。长度为米；方向为东起逆时针角度。"""
import math
import random

EPS = 1e-7
# 接口保留两位小数；在题面 ±1° 之外再容纳最后一次舍入。
ANGLE_ERROR = 1.00500001
STRIP_HALF_WIDTH = 26.4


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, t):
    return (a[0] * t, a[1] * t)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(deg):
    rad = math.radians(deg)
    return (math.cos(rad), math.sin(rad))


def angle_delta(a, b):
    return (a - b + 180) % 360 - 180


def outer_disk(center, radius, sides=64):
    # 顶点半径 r/cos(pi/n)：各条边在真圆外，不用内接多边形删真值。
    rr = (radius + EPS) / math.cos(math.pi / sides)
    return [add(center, mul(unit((i + 0.5) * 360 / sides), rr))
            for i in range(sides)]


def clip(poly, normal, bound):
    """与 n·x <= b 相交；单位法向量与向外数值余量。"""
    if not poly:
        return []
    scale = math.hypot(*normal)
    if not scale:
        raise ValueError("零法向量")
    normal, bound = mul(normal, 1 / scale), bound / scale + EPS
    result = []
    a = poly[-1]
    da = dot(normal, a) - bound
    for b in poly:
        db = dot(normal, b) - bound
        if (da <= 0) != (db <= 0):
            result.append(add(a, mul(sub(b, a), da / (da - db))))
        if db <= 0:
            result.append(b)
        a, da = b, db
    return result


def intersect_disk_outer(poly, center, radius, sides=64):
    for i in range(sides):
        n = unit(i * 360 / sides)
        poly = clip(poly, n, dot(n, center) + radius)
        if not poly:
            break
    return poly


def wedge(poly, position, bearing):
    lo, hi = unit(bearing - ANGLE_ERROR), unit(bearing + ANGLE_ERROR)
    nlo, nhi = (lo[1], -lo[0]), (-hi[1], hi[0])
    return clip(clip(poly, nlo, dot(nlo, position)), nhi, dot(nhi, position))


def rectangle(poly, origin, e, n, u0, u1, v0, v1):
    for axis, lower, upper in ((e, u0, u1), (n, v0, v1)):
        poly = clip(poly, axis, dot(axis, origin) + upper)
        poly = clip(poly, mul(axis, -1), -dot(axis, origin) - lower)
    return poly


def hull(points):
    ps = sorted(set(points))
    if len(ps) <= 2:
        return ps
    def half(seq):
        out = []
        for p in seq:
            while len(out) > 1 and cross(sub(out[-1], out[-2]), sub(p, out[-1])) <= 0:
                out.pop()
            out.append(p)
        return out
    return half(ps)[:-1] + half(reversed(ps))[:-1]


def contains(poly, p, tolerance=1e-5):
    if not poly:
        return False
    if len(poly) == 1:
        return distance(poly[0], p) <= tolerance
    if len(poly) == 2:
        a, b = poly
        d = sub(b, a)
        t = max(0, min(1, dot(sub(p, a), d) / max(dot(d, d), EPS)))
        return distance(p, add(a, mul(d, t))) <= tolerance
    return all(cross(sub(b, a), sub(p, a)) >= -tolerance * max(1, distance(a, b))
               for a, b in zip(poly, poly[1:] + poly[:1]))


def area(poly):
    return abs(sum(cross(a, b) for a, b in zip(poly, poly[1:] + poly[:1]))) / 2


def center(poly):
    if not poly:
        raise ValueError("空区域")
    return (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))


def enclosing_circle(points):
    """小规模最小包围圆；最终重新计算到所有顶点距离，保证圆不偏小。"""
    ps = list(points)
    if not ps:
        raise ValueError("空区域没有包围圆")
    random.Random(0).shuffle(ps)
    c, r = ps[0], 0.0
    for i, p in enumerate(ps):
        if distance(c, p) <= r + EPS:
            continue
        c, r = p, 0.0
        for j, q in enumerate(ps[:i]):
            if distance(c, q) <= r + EPS:
                continue
            c, r = mul(add(p, q), 0.5), distance(p, q) / 2
            for s in ps[:j]:
                if distance(c, s) <= r + EPS:
                    continue
                a, b = sub(q, p), sub(s, p)
                d = 2 * cross(a, b)
                if abs(d) < 1e-12:
                    pairs = [(p, q), (p, s), (q, s)]
                    u, v = max(pairs, key=lambda pair: distance(*pair))
                    c = mul(add(u, v), 0.5)
                else:
                    aa, bb = dot(a, a), dot(b, b)
                    c = add(p, ((aa * b[1] - bb * a[1]) / d,
                                (a[0] * bb - b[0] * aa) / d))
                r = max(distance(c, t) for t in (p, q, s))
    return c, max(distance(c, p) for p in ps) + EPS


ANCHORS = [(0.0, 0.0)] + [mul(unit(60 * k), 1200) for k in range(6)]
GRID = [(float(x), float(y)) for x in range(-1800, 1801, 300)
        for y in range(-1800, 1801, 300) if x * x + y * y <= 1800 ** 2]


def coverage_mask(q):
    # 仅用于收益排序，绝不用于证明没有目标。
    return sum(1 << i for i, p in enumerate(GRID) if distance(q, p) <= 1000)
