"""第四问共用入口；只加载算法核心，不导入旧运行器或资源保护程序。

25点策略定义与实验阶段一致，来源和等价性见MIGRATION.md。
全部算法依赖来自本目录core，不配置研究目录路径。
"""
from dataclasses import dataclass
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]


def bootstrap():
    core = ROOT / "core"
    if str(core) not in sys.path:
        sys.path.insert(0, str(core))


def require_local_dependencies():
    """拒绝从本仓库其他代码目录混入模块，防止同名模块污染迁移。"""
    outside = []
    for module in tuple(sys.modules.values()):
        raw = getattr(module, "__file__", None)
        if raw:
            path = Path(raw).resolve()
            if path.suffix == ".py" and PROJECT in path.parents and ROOT not in path.parents:
                outside.append(path.relative_to(PROJECT).as_posix())
    if outside:
        raise RuntimeError(f"正式Q4加载了目录外的仓库代码: {sorted(set(outside))}")


bootstrap()
from q4 import Q4_ANCHORS, Q4Config, Q4DirectionalPolicy
from q4_coverage import q4_coverage_certificate
import geometry as g

Q4_REDUCED_ANCHORS = tuple(q for q in Q4_ANCHORS if abs(math.hypot(*q) - 2700) > 1e-5)
Q4_SYMMETRIC25_SPACING_M = 944.0
Q4_SYMMETRIC25_ANCHORS = tuple(
    (Q4_SYMMETRIC25_SPACING_M * (i + j / 2), Q4_SYMMETRIC25_SPACING_M * math.sqrt(3) * j / 2)
    for j in range(-2, 3) for i in range(-2, 3) if i * i + i * j + j * j <= 4
) + tuple(g.mul(g.unit(30 + 60 * k), 2 * Q4_SYMMETRIC25_SPACING_M) for k in range(6))


@dataclass(frozen=True)
class Q4ScaledAnchorConfig(Q4Config):
    anchor_spacing_m: float = 875.0


class Q4ScaledAnchorPolicy(Q4DirectionalPolicy):
    """对31点形整体缩放；构造时必须先取得完整覆盖证书。"""
    def __init__(self, config=None, reference_only=False):
        super().__init__(config or Q4ScaledAnchorConfig(), reference_only)
        spacing = self.config.anchor_spacing_m
        if not math.isfinite(spacing) or spacing <= 0:
            raise ValueError("三角格距必须为正且有限")
        self.search_anchors = tuple((x * spacing / 900, y * spacing / 900)
                                    for x, y in Q4_REDUCED_ANCHORS)
        self.anchor_certificate = q4_coverage_certificate(self.search_anchors)
        if not self.anchor_certificate.complete or not self.anchor_certificate.rational_verified:
            raise ValueError("所选格距未取得完整连续覆盖证书")

    def candidate_positions(self, state):
        points = [q for q in super().candidate_positions(state) if q not in Q4_ANCHORS]
        return list(dict.fromkeys(points + list(self.search_anchors)))

    def utility(self, c, q, mask):
        if c.status != "unknown":
            return super().utility(c, q, mask)
        return self.config.q4_anchor_value_s if q in self.search_anchors and q not in c.measured else 0.0

    def fallback(self, state):
        self.fallback_started = True
        near = [c for c in state.channels.values() if c.status == "found" and c.near_position is not None]
        if near:
            c = min(near, key=lambda c: g.distance(state.position, c.near_position))
            return self.action("clear", c.near_position, c.channel, "q4_scaled_fallback_near")
        needed = [(g.distance(state.position, q) / 5 + 5 + int(j != state.measuring_channel), q, j)
                  for j, c in state.channels.items() if c.status == "unknown"
                  for q in self.search_anchors if q not in c.measured]
        if needed:
            _, q, j = min(needed)
            return self.action("measure", q, j, "q4_scaled_fallback_discovery")
        return super().fallback(state)


class Q4Symmetric25Policy(Q4ScaledAnchorPolicy):
    """944m内三角网格加1888m外正十二边形的25点可靠发现策略。"""
    def __init__(self, config=None, reference_only=False):
        Q4DirectionalPolicy.__init__(self, config or Q4Config(), reference_only)
        self.search_anchors = Q4_SYMMETRIC25_ANCHORS
        self.anchor_certificate = q4_coverage_certificate(self.search_anchors)
        if not self.anchor_certificate.complete or not self.anchor_certificate.rational_verified:
            raise ValueError("对称25点未取得完整连续覆盖证书")

    def fallback(self, state):
        action = super().fallback(state)
        if action and action["reason"].startswith("q4_scaled_"):
            action = dict(action, reason=action["reason"].replace("q4_scaled_", "q4_symmetric25_", 1))
        return action


Joint25Policy = Q4Symmetric25Policy


from q4_joint_state import Q4JointCoverageInformationState


class Q4State(Q4JointCoverageInformationState):
    """在原始保守状态上记录公开清除反馈，不增加任何真值信息。"""
    def update(self, action, response):
        super().update(action, response)
        if action["kind"] == "clear":
            channel = self.channels[action["channel"]]
            if not hasattr(channel, "clear_history"):
                channel.clear_history = []
            channel.clear_history.append((tuple(action["position"]), response["clear_result"]))
