"""单项结构修正：允许选择整站扫描，使三层覆盖多次停留。"""
import copy
import math

from planner import (BeliefTreePolicy, Node, Edge, candidates, policy_after,
                     action_key, a, draw, likelihood, dominated_negative)


def station_channels(state,q):
    ids=[j for j,c in state.channels.items()
         if c.status not in ('cleared','absent') and tuple(q) not in c.measured
         and not dominated_negative(c,tuple(q))]
    return sorted(ids,key=lambda j:(j!=state.measuring_channel,j))


def first_atomic(action):
    return dict(kind='measure',position=tuple(action['position']),channel=action['channels'][0],
                reason='selected_station_batch',phase='belief')


def macro_candidates(state,policy):
    atoms,ip=candidates(state,policy)
    if len(atoms)==1 and atoms[0]['reason']=='certain_here':
        return atoms,ip
    actions=[]
    places=set()
    for atom in atoms:
        actions.append(atom)
        if atom['kind']!='measure':
            continue
        q=tuple(atom['position'])
        if q in places:
            continue
        places.add(q)
        js=station_channels(state,q)
        if len(js)>1:
            actions.append(dict(kind='scan_station',position=q,channel=js[0],channels=js,
                                reason='choose_entire_station',phase='belief'))
    return actions,ip


def execute_station(state,env,action):
    replies=[]
    for j in action['channels']:
        if state.complete:
            break
        c=state.channels[j]
        q=tuple(action['position'])
        if c.status in ('cleared','absent') or q in c.measured or dominated_negative(c,q):
            continue
        atom=dict(kind='measure',position=q,channel=j,reason='selected_station_batch',phase='belief')
        reply=env.act(atom)
        state.update(atom,reply)
        replies.append((atom,reply))
    return replies


class MacroTreePolicy(BeliefTreePolicy):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.station_queue=[]
        self.station_position=None

    def metadata(self):
        return dict(super().metadata(),algorithm='conditional_particle_station_tree',
                    macro='chosen_station_batch_committed_until_finished')

    def log(self,record):
        action=record.get('chosen',{})
        if action.get('kind')=='scan_station':
            record['chosen_plan']=action
            record['chosen']=first_atomic(action)
        super().log(record)

    def expand(self,node,edge):
        if edge.action['kind']!='scan_station':
            return super().expand(node,edge)
        world=self.rng.choice(node.worlds)
        env=a.ConditionalEnvironment(world,node.state)
        state=copy.deepcopy(node.state)
        replies=execute_station(state,env,edge.action)
        key=tuple((x['channel'],r.get('measure_result'),r.get('svd_deg')) for x,r in replies)
        if key in edge.outcome_keys:
            index=edge.outcome_keys.index(key)
            edge.multiplicities[index]+=1
            self.counters['identical_feedback_reused']=self.counters.get('identical_feedback_reused',0)+1
            cost,child,_=edge.children[index]
            return cost,child
        # 整站的联合观测似然；先验中的不同频道相互关联由联合世界表示。
        weights=[math.prod(likelihood(w,node.state,x,r) for x,r in replies) for w in node.worlds]
        mass=sum(weights)
        if mass<=0:
            raise ValueError('station observation has zero particle likelihood')
        ess=mass*mass/sum(w*w for w in weights)
        self.counters['min_ess']=min(self.counters['min_ess'],ess)
        self.serial+=1
        worlds=[] if state.complete else draw(state,self.particles,self.serial,self.pool_size)
        policy=policy_after(state,node.policy,node.incumbent_policy,edge.action,node.actions[0])
        child=Node(state,policy,worlds)
        cost=state.virtual_time_s-node.state.virtual_time_s
        edge.children.append((cost,child,{'batch_replies':replies}))
        edge.outcome_keys.append(key)
        edge.multiplicities.append(1)
        self.counters['nodes']+=1
        self.counters['posterior_refreshes']+=int(not state.complete)
        return cost,child

    def simulate(self,node,depth):
        # 搜索分配/成本/尾部与原版一致，仅替换可选择的行动单位。
        self.counters['max_depth']=max(self.counters['max_depth'],self.depth-depth)
        if node.state.complete:
            return 0.
        if depth==0:
            return self.leaf(node)
        if node.actions is None:
            node.actions,node.incumbent_policy=macro_candidates(node.state,node.policy)
        width=min(len(node.actions),max(1,math.ceil(2*math.sqrt(node.visits+1))))
        if len(node.edges)<width:
            edge=Edge(node.actions[len(node.edges)])
            node.edges.append(edge)
        else:
            edge=min(node.edges,key=lambda e:e.mean-self.exploration*math.sqrt(math.log(node.visits+1)/e.visits))
        if len(edge.children)<max(1,math.ceil(math.sqrt(edge.visits+1))):
            cost,child=self.expand(node,edge)
        else:
            cost,child,_=self.rng.choices(edge.children,edge.multiplicities)[0]
        value=cost+self.simulate(child,depth-1)
        edge.visits+=1
        edge.total+=value
        node.visits+=1
        return value

    def queued_action(self,state):
        while self.station_queue:
            j=self.station_queue.pop(0)
            q=self.station_position
            c=state.channels[j]
            if c.status in ('cleared','absent') or q in c.measured or dominated_negative(c,q):
                continue
            return dict(kind='measure',position=q,channel=j,reason='selected_station_batch',phase='belief')
        return None

    def choose(self,state):
        action=self.queued_action(state)
        if action is not None:
            # 这是已选宏动作的继续执行，计时与反馈逐条保留；不声称又搜索了一次。
            self.log(dict(at_action=state.actions,position=state.position,chosen=action,
                          proof='continue_selected_station',wall_s=0.))
            return action
        action=super().choose(state)
        if action['kind']=='scan_station':
            self.station_position=tuple(action['position'])
            self.station_queue=list(action['channels'])
            return self.queued_action(state)
        return action
