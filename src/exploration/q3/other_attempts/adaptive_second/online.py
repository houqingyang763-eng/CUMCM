"""流式公开状态接口：第一次扫描后现场调用优化器，保持旧动作协议。"""
import adaptive as a


class OnlineAdaptivePolicy(a.PatrolPolicy):
    def __init__(self, mode='joint', samples=16, salt=0, radius_prior='uniform'):
        super().__init__(a.CONFIG)
        if mode not in ('position','joint'):
            raise ValueError(mode)
        self.mode=mode
        self.samples=samples
        self.salt=salt
        self.radius_prior=radius_prior
        self.selection=None

    def start_station(self, state, q, reason, priority=None, initial=False, scan_unknown=True):
        candidate=None
        if initial and self.initial_index==1:
            self.selection=a.select(state,self.samples,self.salt,self.radius_prior)
            id=self.selection[self.mode]
            candidate=next(c for c in self.selection['candidates'] if c['id']==id)
            q=tuple(candidate['q'])
        super().start_station(state,q,reason,priority,initial,scan_unknown)
        if candidate is not None:
            self.station_channels=[j for j in self.station_channels if j in candidate['channels']]

    def metadata(self):
        return dict(super().metadata(),second_decision=self.selection)
