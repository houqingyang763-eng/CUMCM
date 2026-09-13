"""F4：仅对拟替换原动作的赢家，用新的条件样本复查一次。"""
import statistics

from refined import RefinedPolicy
from posterior import sample_worlds


class VerifiedPolicy(RefinedPolicy):
    def __init__(self, selected=None):
        super().__init__(selected,level=3,samples=4)

    def select_candidate(self, state, records, original):
        winner=min(records,key=lambda x:x['mean_s'])
        if winner['id']=='original':
            return winner, {'recheck':{'performed':False}}
        worlds,info=sample_worlds(state,8,salt=310913)
        base=next(x for x in records if x['id']=='original')
        base_values=[self.simulate(state,w,base,original) for w in worlds]
        winner_values=[self.simulate(state,w,winner,original) for w in worlds]
        savings=[b-v for b,v in zip(base_values,winner_values)]
        accepted=statistics.mean(savings)>0
        return (winner if accepted else base), {'recheck':{
            'performed':True,'proposed':winner['id'],'accepted':accepted,
            'salt':310913,'posterior':info,'original_costs_s':base_values,
            'proposed_costs_s':winner_values,'paired_savings_s':savings,
            'mean_saving_s':statistics.mean(savings)}}

    def metadata(self):
        return dict(super().metadata(), refinement_variant='f4_independent_recheck',recheck_samples=8)
