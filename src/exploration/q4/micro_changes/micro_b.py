"""候选B：仅对已发现频道的非主目标补测设置一步净价值门槛。

冻结定义：复用正式策略的32点位置条件模型，检测/切频成本为5/1秒；
剩余工作代理与正式候选相同 W(r)=5+(2r-40)_+/5+3(ceil(r/20)-1)_+。
阴性和阳性都更新Q4单频道联合几何；阳性以样本位置的无偏示向代表
连续示向结果（不积分示向误差），近距离结果仍按题面5米判定。
因此是一步工作代理下降，不是完整未来任务价值或理论性能保证。
概率只筛掉额外补测，不删除几何、频道、未知扫描或主目标行动。
"""
import copy
import math
from pathlib import Path
import random
import sys
import time

PROJECT = Path(__file__).resolve().parents[3]
FORMAL = PROJECT / "src" / "q4"
if str(FORMAL) not in sys.path:
    sys.path.insert(0, str(FORMAL))

import common
from belief import history_seed, make_pool, reception_mass
from selected import SelectedPolicy


def remaining_work(radius):
    """秒；复用已有主策略的局部剩余定位/清除工作代理。"""
    return 5.0 + max(0.0, 2 * radius - 40) / 5 + 3 * max(0, math.ceil(radius / 20) - 1)


def clone_channel(channel):
    """只复制将被公开反馈更新的频道；缓存几何和历史证书元素只读共享。"""
    result = copy.copy(channel)
    for name in ("polygon", "exclusions", "observations", "joint_last_details", "clear_history"):
        if hasattr(channel, name):
            setattr(result, name, list(getattr(channel, name)))
    for name in ("measured", "anchors_missed"):
        setattr(result, name, set(getattr(channel, name)))
    result.joint_excluded = dict(channel.joint_excluded)
    return result


def hypothetical_channel(state, channel, q, result, bearing=None):
    """用正式Q4公开反馈接口更新一个频道，其他频道与原状态均不修改。"""
    local = copy.copy(state)
    local.channels = {channel.channel: clone_channel(channel)}
    local.ever_seen = set(state.ever_seen)
    local.q4_anchors_missed = {channel.channel: set(state.q4_anchors_missed[channel.channel])}
    local.absence_proofs = dict(state.absence_proofs)
    local._q4_coverage_by_channel = {}
    response = dict(accepted=True, virtual_time_s=state.virtual_time_s,
                    measure_result=result)
    if bearing is not None:
        response["svd_deg"] = bearing
    local.update(dict(kind="measure", channel=channel.channel, position=tuple(q)), response)
    return local.channels[channel.channel]


class MicroBPolicy(SelectedPolicy):
    """正式SelectedPolicy之外的独立实验候选，不改变正式配置。"""
    def __init__(self):
        super().__init__()
        self.b_priority = None
        self.b_pools = {}
        self.b_pool_stamps = {}
        self.b_evaluations = []
        self.b_wall_s = 0.0

    def _auxiliary_pool(self, state, channel):
        stamp = (len(channel.observations), len(channel.exclusions), channel.status)
        if self.b_pool_stamps.get(channel.channel) != stamp:
            # 与主策略同一工作先验/确定性种子公式，但独立cache与局部RNG。
            rng = random.Random(history_seed(state, 2026091331 + channel.channel))
            local = clone_channel(channel)
            pool = make_pool(state, local, rng, self.config.pool_size, self.config.omni_prior)
            self.b_pools[channel.channel] = pool
            self.b_pool_stamps[channel.channel] = stamp
        return self.b_pools[channel.channel]

    def _auxiliary_value(self, state, channel, q):
        pool = self._auxiliary_pool(state, channel)
        total = sum(pool["weights"])
        if total <= 0:
            raise ValueError("辅助估价有限池耗尽，保留原补测")
        before = remaining_work(channel.circle()[1])
        weighted_hit = [(x, w, reception_mass(x, slices, q))
                        for x, slices, w in zip(pool["points"], pool["slices"], pool["weights"])
                        if w > 0]
        probability = sum(w * hit for _, w, hit in weighted_hit) / total
        # 只有一个no_signal结果；其联合朝向/位置证书可提供非零信息价值。
        negative_work = before
        if probability < 1 - 1e-12:
            negative = hypothetical_channel(state, channel, q, "no_signal")
            negative_work = remaining_work(negative.circle()[1])
        positive_sum = 0.0
        for x, weight, hit in weighted_hit:
            if hit <= 0:
                continue
            if math.dist(x, q) <= 5:
                positive = hypothetical_channel(state, channel, q, "near")
            else:
                bearing = math.degrees(math.atan2(x[1] - q[1], x[0] - q[0])) % 360
                positive = hypothetical_channel(state, channel, q, "direction", bearing)
            positive_sum += weight * hit * remaining_work(positive.circle()[1]) / total
        after = (1 - probability) * negative_work + positive_sum
        cost = 5 + int(channel.channel != state.measuring_channel)
        return dict(expected_gain_s=before - after, measure_switch_cost_s=cost,
                    expected_remaining_work_s=after, before_work_s=before,
                    negative_work_s=negative_work, reception_probability=probability,
                    pool_ess=pool["ess"], pool_size=self.config.pool_size)

    def _keep_auxiliary(self, state, channel, q):
        began = time.perf_counter()
        record = dict(at_action=state.actions, channel=channel.channel, position=tuple(q),
                      reason=self.station_reason)
        try:
            record.update(self._auxiliary_value(state, channel, q))
            keep = record["expected_gain_s"] > record["measure_switch_cost_s"]
            record["keep"] = keep
        except (ValueError, RuntimeError, AssertionError) as exc:
            # 条件池/代理分支异常不触发整局fallback，也不丢弃原本可执行补测。
            keep = True
            record.update(keep=True, estimation_fallback=str(exc))
        elapsed = time.perf_counter() - began
        self.b_wall_s += elapsed
        record["wall_s"] = elapsed
        self.b_evaluations.append(record)
        return keep

    def _station(self, state, q, reason, priority=None, scan_unknown=True):
        self.b_priority = priority
        return super()._station(state, q, reason, priority, scan_unknown)

    def _station_action(self, state):
        while self.queue:
            j = self.queue.pop(0)
            channel = state.channels[j]
            if channel.status in ("absent", "cleared") or self.station in channel.measured:
                continue
            if channel.status == "found":
                if channel.circle()[1] <= 20 - 1e-5:
                    continue
                if j != self.b_priority and not self._keep_auxiliary(state, channel, self.station):
                    continue
            return self.action("measure", self.station, j, self.station_reason)
        # clearance_shared_scan/初始扫描为空时原choose会继续规划；主任务和
        # 未知扫描未被筛掉，所以不会因本门槛使_install失去必执行动作。
        self.station = None
        self.b_priority = None
        return None

    def metadata(self):
        result = super().metadata()
        result["micro_b"] = dict(evaluations=self.b_evaluations, wall_s=self.b_wall_s,
                                 kept=sum(r["keep"] for r in self.b_evaluations),
                                 skipped=sum(not r["keep"] for r in self.b_evaluations),
                                 estimation_fallbacks=sum("estimation_fallback" in r for r in self.b_evaluations))
        return result
