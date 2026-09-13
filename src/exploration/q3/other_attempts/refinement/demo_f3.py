"""一次新随机场景，原封不动运行 F3；由日志生成逐动作回放。"""
import argparse
import hashlib
import importlib.util
import json
import secrets
import time
from pathlib import Path

from refined import RefinedPolicy
from posterior import a
from build_replay import build_variant, rounded

HERE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--visual', type=Path, required=True)
    args = p.parse_args()
    root = args.root
    root.mkdir(parents=True, exist_ok=True)
    if not (root/'cases.json').exists():
        seed = secrets.randbelow(2**31)
        case = a.base.generate(seed, 'uniform', 'hashed')
        a.base.dump(root/'cases.json', [case.to_dict()])
        paths = [p for directory in [HERE, a.HERE, HERE.parent/'probability_patrol',
                 a.HERE.parents[1]/'b_adaptive_q3'] for p in directory.glob('*.py')]
        a.base.dump(root/'manifest.json', {
            'sampling': 'one unfiltered random draw, uniform positions/radii, fixed hashed noise',
            'seed': seed, 'policy': 'RefinedPolicy level=3 samples=4; initial selection samples=16',
            'started_unix': time.time(), 'official_test': False,
            'hashes': {str(p.relative_to(a.base.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}})
    case_data = json.loads((root/'cases.json').read_text(encoding='utf-8'))[0]
    case = a.Scenario.from_dict(case_data)
    directory = root/case.name
    directory.mkdir(exist_ok=True)
    print('SCENE '+str(case.seed)+' sources='+str(len(case.sources)), flush=True)
    if not (directory/'selection.json').exists():
        state = a.first_state(case)
        start = time.perf_counter()
        selection = a.select(state, 16)
        selected = next(c for c in selection['candidates'] if c['id']==selection['position'])
        a.base.dump(directory/'selection.json', dict(selection, selected=selected,
                    history_seed=a.history_seed(state), wall_s=time.perf_counter()-start))
    selection = json.loads((directory/'selection.json').read_text(encoding='utf-8'))
    print('SECOND '+selection['selected']['id'], flush=True)
    if not (directory/'f3/result.json').exists():
        original = a.base.create_policy
        try:
            a.base.create_policy = lambda name, config: (
                RefinedPolicy(selection['selected'], level=3, samples=4), a.CoverageInformationState())
            a.base.execute_case(case_data, 'patrol', a.CONFIG, directory/'f3',
                                {'action_limit':3000,'wall_limit_s':1200,'virtual_limit_s':10800})
        finally:
            a.base.create_policy = original
    result = json.loads((directory/'f3/result.json').read_text(encoding='utf-8'))
    print('RESULT '+json.dumps(result, ensure_ascii=False), flush=True)
    assert result['success'], 'Keep failed scene; do not redraw.'
    data, receipt = build_variant(root, case_data, 'f3', selection)
    # Existing multi-version wording is changed only in this explanatory data.
    for item in data['groups']+data['single']:
        item['why'] = item['why'].replace('；四个展示版本使用相同第二站。', '。这些是预测成本，并非已知未来。')
    compact = rounded({'variants': {'f3':data}})
    pool, index = [], {}
    for frame in compact['variants']['f3']['frames']:
        ids = []
        for channel in frame['channels']:
            key = json.dumps(channel, ensure_ascii=False, separators=(',',':'))
            if key not in index:
                index[key]=len(pool)
                pool.append(channel)
            ids.append(index[key])
        frame['channels'] = ids
    compact['channelPool'] = pool
    payload = json.dumps(compact, ensure_ascii=False, separators=(',',':')).replace('</', '<\\/')
    template = (HERE/'replay-template.html').read_text(encoding='utf-8')
    template = template.replace('同一随机场景：改动前后逐步复查', 'F3：一个新随机场景的逐步清除过程')
    template = template.replace('<label class="form-label">算法 <select', '<label hidden class="form-label">算法 <select')
    template = template.replace(".slice(-3);", ";")
    template = template.replace('theta-Math.PI/180', 'theta-1.005*Math.PI/180').replace('theta+Math.PI/180', 'theta+1.005*Math.PI/180')
    template = template.replace("const histories=data.actions.slice(0,g.end).filter(a=>a.channel===chosen&&a.kind==='measure');",
        "const histories=data.actions.slice(0,g.end).map((a,i)=>({...a,step:i+1})).filter(a=>a.channel===chosen&&a.kind==='measure');")
    template = template.replace("const bearings=histories.filter", """histories.forEach(a=>{
        const x=X(a.position[0]),y=Y(a.position[1]);
        scene.append(svg('circle',{cx:x,cy:y,r:4,fill:'none',stroke:color.range,'stroke-width':1.5,
          'data-tooltip':`C${chosen} 第${a.step}步测点 · ${a.result}`}));
        if(ui.zoom.checked || histories.length<8)scene.append(svg('text',{x:x+6,y:y-6},`测${a.step}`));
      });
      const bearings=histories.filter""")
    html = template.replace('__REPLAY_DATA__', payload)
    assert len(html.encode('utf-8')) < 1_000_000
    args.visual.parent.mkdir(parents=True, exist_ok=True)
    args.visual.write_text(html, encoding='utf-8')
    a.base.dump(directory/'f3/view_data.json', data)
    receipt.update(file=str(args.visual), bytes=args.visual.stat().st_size, seed=case.seed,
                   policy_unchanged=True, actual_source_count=len(case.sources))
    a.base.dump(root/'replay_receipt.json', receipt)
    print('REPLAY '+json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__=='__main__':
    main()
