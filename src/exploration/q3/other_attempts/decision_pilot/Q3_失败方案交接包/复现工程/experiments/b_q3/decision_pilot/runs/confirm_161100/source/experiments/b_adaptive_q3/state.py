"""策略可见状态：只由公开动作反馈更新，不持有模拟器真值。"""
import math
from dataclasses import dataclass, field

import geometry as g


@dataclass
class ChannelState:
    channel: int
    status: str = "unknown"
    polygon: list = field(default_factory=lambda: g.outer_disk((0, 0), 1800))
    exclusions: list = field(default_factory=list)
    observations: list = field(default_factory=list)
    measured: set = field(default_factory=set)
    anchors_missed: set = field(default_factory=set)
    sample_mask: int = (1 << len(g.GRID)) - 1
    first: tuple | None = None
    near_position: tuple | None = None
    cached_support: list | None = None
    cached_cells: list | None = None
    cached_circle: tuple | None = None

    def invalidate(self):
        self.cached_support = self.cached_cells = self.cached_circle = None

    def strip_axes(self):
        q, bearing = self.first
        e = g.unit(bearing)
        return q, e, (-e[1], e[0])

    def possible_cells(self):
        if self.cached_cells is not None:
            return self.cached_cells
        if self.first is None:
            return []
        origin, e, n = self.strip_axes()
        cells = []
        width = g.STRIP_HALF_WIDTH
        for row, (v0, v1) in enumerate(((-width, 0), (0, width))):
            for k in range(50):
                poly = g.rectangle(self.polygon, origin, e, n, 30 * k, 30 * (k + 1), v0, v1)
                # 只在整个多边形都严格进入一个已排除圆时删除。
                # 圆是凸集，检查所有顶点足够；部分相交、联合覆盖均保留。
                if not poly or any(all(g.distance(p, q) < radius - 1e-5 for p in poly)
                                   for q, radius in self.exclusions):
                    continue
                q = g.add(origin, g.add(g.mul(e, 15 + 30 * k), g.mul(n, (v0 + v1) / 2)))
                cells.append({"index": (row, k), "position": q, "polygon": poly})
        self.cached_cells = cells
        return cells

    def support(self):
        if self.cached_support is None:
            if self.first is None:
                self.cached_support = self.polygon
            else:
                self.cached_support = g.hull([p for c in self.possible_cells() for p in c["polygon"]])
        return self.cached_support

    def circle(self):
        if self.cached_circle is None:
            self.cached_circle = g.enclosing_circle(self.support())
        return self.cached_circle

    def compatible(self, p):
        return g.contains(self.polygon, p) and all(g.distance(p, q) >= r - 1e-5 for q, r in self.exclusions)


class InformationState:
    def __init__(self):
        self.channels = {j: ChannelState(j) for j in range(1, 21)}
        self.position = (0.0, 0.0)
        self.measuring_channel = 1
        self.virtual_time_s = 0.0
        self.ever_seen = set()
        self.actions = 0

    @property
    def complete(self):
        return all(c.status in ("cleared", "absent") for c in self.channels.values())

    def update(self, action, response):
        if not response.get("accepted"):
            raise ValueError("原型只接收已执行动作")
        q, j = tuple(action["position"]), action["channel"]
        c = self.channels[j]
        c.invalidate()
        self.position = q
        self.virtual_time_s = response["virtual_time_s"]
        self.actions += 1
        if action["kind"] == "measure":
            self.measuring_channel = j
            c.measured.add(q)
            result = response["measure_result"]
            c.observations.append((q, result, response.get("svd_deg")))
            if result == "no_signal":
                c.exclusions.append((q, 1000.0))
                c.sample_mask &= ~g.coverage_mask(q)
                for i, anchor in enumerate(g.ANCHORS):
                    if g.distance(q, anchor) < 1e-6:
                        c.anchors_missed.add(i)
                if c.status == "unknown" and len(c.anchors_missed) == len(g.ANCHORS):
                    c.status = "absent"
            elif result in ("direction", "near"):
                if c.status in ("absent", "cleared"):
                    raise AssertionError("终止状态后又发现目标")
                c.status = "found"
                self.ever_seen.add(j)
                if result == "near":
                    c.near_position = q
                    c.polygon = g.intersect_disk_outer(c.polygon, q, 5)
                else:
                    bearing = response["svd_deg"]
                    if c.first is None:
                        c.first = (q, bearing)
                        origin, e, n = c.strip_axes()
                        c.polygon = g.rectangle(c.polygon, origin, e, n, 0, 1500,
                                                -g.STRIP_HALF_WIDTH, g.STRIP_HALF_WIDTH)
                    c.polygon = g.wedge(c.polygon, q, bearing)
                    c.polygon = g.intersect_disk_outer(c.polygon, q, 1500)
            else:
                raise ValueError(result)
        elif action["kind"] == "clear":
            if response["clear_result"] == "success":
                c.status = "cleared"
                self.ever_seen.add(j)
            elif response["clear_result"] == "no_target_in_range":
                c.exclusions.append((q, 20.0))
            else:
                raise ValueError(response["clear_result"])
        else:
            raise ValueError(action["kind"])
        if len(self.ever_seen) > 16:
            raise AssertionError("违反题面最多 16 个源")
        if len(self.ever_seen) == 16:
            for c in self.channels.values():
                if c.status == "unknown":
                    c.status = "absent"


def audit_state(state, environment):
    """仅测试驱动调用：真值不进入 InformationState 或 Policy。"""
    for j, source in environment.sources.items():
        c = state.channels[j]
        if j in environment.cleared:
            assert c.status == "cleared", (j, "漏记清除")
            continue
        assert c.status not in ("absent", "cleared"), (j, "错误宣称结束")
        assert c.compatible(source.position), (j, "误排除真实位置", source.position)
        if c.first is not None:
            assert any(g.contains(cell["polygon"], source.position) for cell in c.possible_cells()), (j, "清除格漏掉真值")
        if c.status == "found":
            center, radius = c.circle()
            assert g.distance(center, source.position) <= radius + 1e-5, (j, "包围圆漏掉真值")
    if state.complete:
        assert len(environment.cleared) == len(environment.sources), "提前结束"
    assert abs(state.virtual_time_s - environment.virtual_time_s) < 1e-6

