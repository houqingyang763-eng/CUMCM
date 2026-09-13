"""K=15时以条件概率评估服务点顺扫，最多两次；不改变全清判据。"""
from dataclasses import dataclass
import time

from candidate import CandidateConfig, CandidatePolicy
from cap_value import CapValueEstimator


@dataclass(frozen=True)
class CapConfig(CandidateConfig):
    prune_planned_stops: bool = True
    cap_pool_size: int = 512
    cap_scan_limit: int = 2
    cap_value_salt: int = 2026091316


class CapPolicy(CandidatePolicy):
    def __init__(self, config=None):
        if isinstance(config, dict):
            config = CapConfig(**config)
        super().__init__(config or CapConfig())
        self.cap_estimator = CapValueEstimator(self.config.cap_pool_size, self.config.cap_value_salt)
        self.cap_used = 0
        self.cap_records = []
        self.cap_observed_clears = set()

    def metadata(self):
        return dict(super().metadata(), cap_scan_used=self.cap_used, cap_records=self.cap_records)

    def _opportunistic_scan(self, state):
        return False  # 只使用下面的概率价值触发，不叠加经验源数阈值。

    def _cap_accept(self, state, q, trigger):
        if self.cap_used >= self.config.cap_scan_limit or len(state.ever_seen) != 15:
            return False
        began = time.perf_counter()
        value = self.cap_estimator.evaluate(state, q)
        if value is None:
            return False
        accept = value['net'] > 0
        self.cap_records.append(dict(at_action=state.actions, trigger=trigger,
            accepted=accept, used_before=self.cap_used, wall_s=time.perf_counter()-began, **value))
        if accept:
            self.cap_used += 1
        return accept

    def _install(self, state, job):
        if job['kind'] in ('clear', 'measure') and not job.get('scan_unknown', False):
            if self._cap_accept(state, job['position'], 'planned_'+job['kind']):
                job = dict(job, scan_unknown=True)
        return super()._install(state, job)

    def choose(self, state):
        cleared = {j for j,c in state.channels.items() if c.status == 'cleared'}
        new_cleared = cleared-self.cap_observed_clears
        self.cap_observed_clears = cleared
        # 已承诺的本站未知队列可能被certain_here清除临时打断；
        # 成功后继续同一队列，不为同一次顺扫再次申请cap预算。
        pending_unknown_scan = (self.station == tuple(state.position) and any(
            state.channels[j].status == 'unknown' and self.station not in state.channels[j].measured
            for j in self.queue))
        if (not state.complete and new_cleared and self.clear_scan_commitment is None
                and not pending_unknown_scan
                and self._cap_accept(state, state.position, 'completed_clear')):
            self.clear_scan_commitment = (min(new_cleared), tuple(state.position))
        return super().choose(state)
