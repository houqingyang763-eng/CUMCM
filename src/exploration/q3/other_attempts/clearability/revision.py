"""一次有据修正：优先跨过效用门槛，避免低效用被低扫描秒数放大。"""
from policy import UtilityPolicy,utility


class BreakthroughPolicy(UtilityPolicy):
    def __init__(self,selected):
        super().__init__(selected,level=3)
        self.revision_cache={}

    def best_view(self,state,c):
        key=(state.actions,c.channel)
        if key in self.revision_cache:return self.revision_cache[key]
        old,records=super().best_view(state,c)
        # A high existing utility is not an information gain. In particular,
        # a provably negative view must never win just by preserving U(r).
        eligible=[x for x in records if not x.get('certain_redundant') and x.get('gain',0)>0]
        usable=[x for x in eligible if x['mean_u']>=.8]
        if usable:best=min(usable,key=lambda x:(x['seconds'],-x['mean_u']))
        else:best=max(eligible,key=lambda x:(x['mean_u'],-x['seconds'])) if eligible else old
        self.revision_cache[key]=(best,records)
        return best,records

    def worthwhile(self,state,c,q,force=False):
        keep,why,pred=super().worthwhile(state,c,q,force)
        if force or pred.get('gain') is None or not keep:return keep,why,pred
        best,_=self.best_view(state,c)
        if pred['mean_u']<utility(40) and best.get('mean_u',0)>=.8:
            return False,'low_terminal_utility_better_breakthrough_available',pred
        return keep,why,pred
