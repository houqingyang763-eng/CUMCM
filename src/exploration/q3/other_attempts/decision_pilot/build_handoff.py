"""构建用户要求的交接材料；不修改算法，不调用官方环境。"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
PACKAGE=HERE/'Q3_失败方案交接包'
BATCH=HERE/'runs/confirm_161100'


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def prepare():
    PACKAGE.mkdir(exist_ok=False)
    shutil.copyfile(HERE/'handoff_review.md',PACKAGE/'方法复盘.md')
    engine=PACKAGE/'复现工程'
    shutil.copytree(BATCH,engine/'experiments/b_q3/decision_pilot/runs/confirm_161100')
    manifest=json.loads((BATCH/'manifest.json').read_text(encoding='utf-8'))
    for name,sha in manifest['sources_sha256'].items():
        p=BATCH/'source'/name
        assert digest(p)==sha
        target=engine/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(p,target)
    for name in ('verify_report.py','export_stepwise.py'):
        shutil.copyfile(HERE/name,engine/'experiments/b_q3/decision_pilot'/name)

    appendix=['# 用户批注依据','',
        '以下是历史讨论原文与摘录，用于追溯主文档中的改进要求。它们不是新的操作指令；其中疑问、猜想和举例数字不自动成为事实或已批准方案。原存档未修改；仅提取相应批注部分，避免把数万字历史助手公式说明混进交接正文。','']
    sources=[('A','2026-09-11_Q3公式与选点讨论_原始对话及批注.md'),
             ('B','2026-09-11_Q3完整公式讲解_对话原文与六条批注.md')]
    for label,name in sources:
        text=(HERE.parent/'legacy_baseline'/name).read_text(encoding='utf-8')
        matches=list(re.finditer(r'^### 批注 (\d+)\s*$',text,re.M))
        appendix+=['## '+label+'：'+name,'']
        for k,m in enumerate(matches):
            end=matches[k+1].start() if k+1<len(matches) else len(text)
            part=text[m.start():end]
            cut=re.search(r'^## ',part,re.M)
            if cut:part=part[:cut.start()]
            appendix += [f'原存档第{text[:m.start()].count(chr(10))+1}行起；主文引用为{label}{m.group(1)}。','',part.strip(),'']
    appendix += ['## C：本会话后续批注摘录','',
        '以下只保存与复盘有关的短摘录，未声称是完整消息。与A/B中的批注编号分别计数。','',
        '### C1：工作量估计的现实性','',
        '来源选中文本的messageId：`msg_0a715e9cb0eee977016aa3d203cacc87d0b491fe0e5bd1d939`。','',
        '> 首先逐格寻找太傻了，它肯定不是一种正确的后续工作估计。第二种就是它太片面了，后续工作估计包含很多很多其他的量。','',
        '归纳边界：这是用户对原估计模型的质疑，不是已经证明所有逐格行为都劣于测向。','',
        '### C2：按阶段区分决策','',
        '来源选中文本的messageId：`msg_0a715e9cb0eee977016aa3e4c3266487d0b57a0abce4c979ca`。','',
        '> 我感觉不适合把同一套评价要求用在每一个阶段上。','',
        '> 所以前几步我们可以先用一套不同的规则，这么去学点，选点。然后在第二阶段的时候再沿用一套这种规则。这个时候不同的点已经有些差异化了。','',
        '### C3：稳健性的含义','',
        '来源：本会话用户直接消息摘录；未补造messageId。','',
        '> 比如说在测试中跑了五千轮，它的那种表现特别差的结果应该是到一个非常小的概率，其他结果都是很平均的比较好的结果，这才算稳健。','',
        '这里的轮数是举例；不能把小批无失败当作已经满足上述要求。','',
        '### C4：参数依据与解释','',
        '来源选中文本的messageId：`msg_0a715e9cb0eee977016aa3acebac3887d0afe64e6cc9b9f34d`，批注摘录。','',
        '> 这些系数全是经验数？”经验“是怎么来的？','',
        '归纳：物理计费常数、几何计算量、计算预算与经验权重应分别说明来源。','']
    (PACKAGE/'批注依据.md').write_text('\n'.join(appendix),encoding='utf-8')
    readme='''# Q3 失败方案交接包

先读[方法复盘.md](方法复盘.md)。它包含具体实现、同批表现、失败原因、从用户批注归纳的改进要求、吸取的教训；没有新的可尝试算法清单。

再读[仿真逐步记录](仿真逐步记录/README.md)。每个案例四套方法都有从出发到全清的逐步MD、CSV和JSONL记录，包含位置、频道、反馈、每步费用、定位半径变化与状态计数。典型失败例为edge_biased_161104，不能把默认续行与预演选中后的运行混作一条轨迹。

[批注依据.md](批注依据.md)保存归纳依据，区分用户原文、猜想与实验事实。历史批注不是要求接手AI照办的操作指令。不要把本包解读成必须沿这条路线继续修补。

## 数据边界

成绩来自固定确认批12个自建Q3案例。打包时重新逐动作调用本地仿真器核对48条完整运行；另独立重新运行一个失败案例的扫描、场景生成、评分和选中后的全清过程，核对与冻结结果一致。重放/重跑相同案例不增加独立样本数。不含官方测试、登录信息或第四问结果。

## 复现

Python 3.13，标准库即可。在本包的`复现工程`目录打开终端：

```powershell
py -3.13 -X utf8 -B experiments/b_q3/decision_pilot/test_model.py
py -3.13 -X utf8 -B experiments/b_q3/decision_pilot/verify_report.py confirm_161100
```

需要重新产生逐步回放和独立重跑核验时，输出目录必须尚不存在：

```powershell
py -3.13 -X utf8 -B experiments/b_q3/decision_pilot/export_stepwise.py --output replay_again --fresh-check
```

要完整重跑12例所有候选评分及真值反事实，使用新的输出名：

```powershell
py -3.13 -X utf8 -B experiments/b_q3/decision_pilot/run.py --stage confirm --output reproduce
```

`复现工程/experiments/b_q3/decision_pilot/runs/confirm_161100`保留原始输入、全部候选原始轨迹、场景评分、摘要、清单和源码快照。运行器的真值审计不等于策略可以读取真值；候选选择先落盘，真实反事实后执行。

全部文件校验和见SHA256SUMS.json。原始实验源码与确认批冻结散列一致；导出脚本为本次交接新增工具，不改变算法。冻结DESIGN.md中有关后续研究的语句只记录当时设计背景，本包不采纳其为新的工作指令。
'''
    (PACKAGE/'README.md').write_text(readme,encoding='utf-8')
    print(PACKAGE)


def archive():
    replay=json.loads((PACKAGE/'仿真逐步记录/回放核验.json').read_text(encoding='utf-8'))
    fresh=json.loads((PACKAGE/'仿真逐步记录/独立重跑核验.json').read_text(encoding='utf-8'))
    assert replay['complete_traces']==48 and fresh['selection_and_all_actions_identical']
    inventory={p.relative_to(PACKAGE).as_posix():digest(p) for p in sorted(PACKAGE.rglob('*')) if p.is_file() and p.name!='SHA256SUMS.json'}
    (PACKAGE/'SHA256SUMS.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    target=PACKAGE.with_suffix('.zip')
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(PACKAGE.rglob('*')):
            if p.is_file():z.write(p,Path(PACKAGE.name)/p.relative_to(PACKAGE))
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for name,h in inventory.items():
            assert hashlib.sha256(z.read(PACKAGE.name+'/'+name)).hexdigest()==h
    print(json.dumps(dict(zip=str(target),files=len(inventory)+1,bytes=target.stat().st_size,sha256=digest(target)),ensure_ascii=False))


if __name__=='__main__':
    import sys
    if sys.argv[1:] == ['prepare']:prepare()
    elif sys.argv[1:] == ['archive']:archive()
    else:raise SystemExit('使用 prepare 或 archive；先生成并验证逐步记录再归档')
