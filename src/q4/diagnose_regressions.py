"""仅后处理完整公开轨迹，诊断同案例退步；不执行策略、不连接接口。

正式holdout完整时优先使用；尚未完成时须显式允许研究结果代替并标记。
费用按实际到达动作归类，是账本分解，不代表移除该动作的反事实收益。
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT / "outputs/q4"
COSTS = ("move_s", "measure_s", "switch_s", "success_clear_s", "failed_clear_s")
GROUP_NAMES = {
    "unknown_measure": "未发现频道检测", "known_measure": "已发现源补测",
    "cleared_measure": "已清频道检测", "clear_success": "到成功清除点的移动及清除", "clear_failed": "到失败清除点的移动及尝试"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def complete_batch(folder, policies):
    if not (folder / "results.json").exists() or not (folder / "cases.json").exists():
        return False
    rows, cases = read(folder / "results.json"), read(folder / "cases.json")
    expected = {(c["name"], p) for c in cases for p in policies}
    actual = {(r["case"], r["policy"]) for r in rows}
    return expected == actual and len(rows) == len(expected)


def empty_cost():
    return dict(count=0, move_s=0., measure_s=0., switch_s=0., success_clear_s=0., failed_clear_s=0., total_s=0.)


def add_cost(target, charges):
    target["count"] += 1
    for k in COSTS:
        target[k] += charges[k]
    target["total_s"] += sum(charges.values())


def trace_metrics(folder, result, source_hashes):
    casefolder = folder / "cases" / result["case"] / result["policy"]
    action_path, ledger_path = casefolder / "actions.jsonl", casefolder / "ledger.json"
    for path in (action_path, ledger_path):
        source_hashes[path.relative_to(PROJECT).as_posix()] = sha(path)
    actions = [json.loads(line) for line in action_path.read_text(encoding="utf-8").splitlines()]
    ledgers = read(ledger_path)
    if len(actions) != len(ledgers) or len(actions) != result["actions"]:
        raise ValueError("动作、账本与结果计数不一致")
    known, cleared, measured = set(), set(), set()
    discoveries, successes, failures, annotated = [], [], [], []
    groups, reasons, totals = defaultdict(empty_cost), defaultdict(empty_cost), empty_cost()
    channel_counts = defaultdict(Counter)
    repeated_measurements = known_no_signal = 0
    position, channel, accumulated = (0., 0.), 1, 0.
    for a, item in zip(actions, ledgers):
        if a["step"] != item["step"] or a["response"].get("accepted") is not True:
            raise ValueError("公开动作顺序或执行状态不一致")
        q, j, response = tuple(a["position"]), a["channel"], a["response"]
        charges = item["charges"]
        expected = {k: 0. for k in COSTS}
        expected["move_s"] = math.dist(position, q) / 5
        event = dict(step=a["step"], channel=j, virtual_s=response["virtual_time_s"],
                     position=q, reason=a.get("reason"), known_before=len(known))
        if a["kind"] == "measure":
            group = "cleared_measure" if j in cleared else "known_measure" if j in known else "unknown_measure"
            expected.update(measure_s=5., switch_s=float(j != channel))
            channel = j
            if (j, q) in measured:
                repeated_measurements += 1
            measured.add((j, q))
            channel_counts[j][group] += 1
            if group == "known_measure" and response["measure_result"] == "no_signal":
                known_no_signal += 1
                channel_counts[j]["known_no_signal"] += 1
            if response["measure_result"] in ("direction", "near") and j not in known:
                known.add(j)
                discoveries.append(dict(event, known_after=len(known), via=response["measure_result"]))
        elif a["kind"] == "clear":
            success = response["clear_result"] == "success"
            group = "clear_success" if success else "clear_failed"
            expected["success_clear_s" if success else "failed_clear_s"] = 5. if success else 3.
            if success:
                if j in cleared:
                    raise ValueError("同一频道重复清除成功")
                if j not in known:
                    known.add(j)
                    discoveries.append(dict(event, known_after=len(known), via="clear_success"))
                cleared.add(j)
                successes.append(dict(event, cleared_after=len(cleared)))
            else:
                failures.append(dict(event, approach_move_s=charges["move_s"]))
                channel_counts[j]["failed_clears"] += 1
        else:
            raise ValueError("未知动作")
        if any(abs(charges[k] - expected[k]) > 1e-6 for k in COSTS):
            raise ValueError("动作费用与独立逐条复算不一致")
        accumulated += sum(charges.values())
        if abs(accumulated - response["virtual_time_s"]) > 1e-5:
            raise ValueError("账本累计与公开虚拟时间不一致")
        for target in (groups[group], reasons[a.get("reason", "unspecified")], totals):
            add_cost(target, charges)
        annotated.append(dict(step=a["step"], group=group, charges=charges, channel=j,
                              position=q, virtual_s=response["virtual_time_s"]))
        position = q
    if not result["success"] or len(cleared) != result["source_count"] or len(cleared) != result["cleared"]:
        raise ValueError("诊断对象不是完整全清轨迹")
    if any(abs(totals[k] - result["ledger"][k]) > 1e-5 for k in COSTS):
        raise ValueError("逐条费用与结果总账不一致")
    last_discovery, last_clear = discoveries[-1], successes[-1]
    after_discovery, unknown_after_discovery, after_clear = empty_cost(), empty_cost(), empty_cost()
    trailing_positions = set()
    for a in annotated:
        if a["step"] > last_discovery["step"]:
            add_cost(after_discovery, a["charges"])
            if a["group"] == "unknown_measure":
                add_cost(unknown_after_discovery, a["charges"])
                trailing_positions.add(a["position"])
        if a["step"] > last_clear["step"]:
            add_cost(after_clear, a["charges"])
    metadata = result.get("policy_metadata", {})
    plans = metadata.get("plans", [])
    return dict(case=result["case"], policy=result["policy"], source_count=result["source_count"],
        layout=result.get("layout"), noise=result.get("noise"), cleared_count=len(cleared),
        virtual_s=accumulated, per_source_s=accumulated / len(cleared),
        wall_s=result["wall_time_s"], groups=dict(groups), reasons=dict(reasons), total=totals,
        first_discovery=discoveries[0], last_discovery=last_discovery, first_clear=successes[0], last_clear=last_clear,
        discoveries=discoveries, successful_clears=successes, failed_clear_events=failures,
        per_channel_counts={j:dict(v) for j,v in channel_counts.items()},
        uncleared_at_last_discovery=sorted(known - {e['channel'] for e in successes if e['step'] <= last_discovery['step']}),
        after_last_discovery=after_discovery, unknown_measure_after_last_discovery=unknown_after_discovery,
        unknown_sites_after_last_discovery=len(trailing_positions), after_last_clear=after_clear,
        known_no_signal_count=known_no_signal, repeated_same_channel_position=repeated_measurements,
        shared_plan_adoptions=sum(bool(p.get("adopted_substitution")) for p in plans),
        fallback=result.get("fallback"), independently_recomputed=True,
        actions_source=action_path.relative_to(PROJECT).as_posix())


def compare(candidate, reference, batch):
    deltas = {k: candidate["total"][k] - reference["total"][k] for k in COSTS}
    groups = {k: candidate["groups"].get(k, empty_cost())["total_s"] - reference["groups"].get(k, empty_cost())["total_s"] for k in GROUP_NAMES}
    difference=candidate["virtual_s"]-reference["virtual_s"]
    if abs(sum(deltas.values())-difference)>1e-5 or abs(sum(groups.values())-difference)>1e-5:
        raise ValueError("配对费用分解无法还原整局差")
    return dict(batch=batch, case=candidate["case"], reference=reference["policy"], selected=candidate["policy"],
        extra_s=candidate["virtual_s"] - reference["virtual_s"],
        extra_fraction=candidate["virtual_s"] / reference["virtual_s"] - 1,
        cost_delta_s=deltas, action_group_delta_s=groups,
        last_discovery_delta_s=candidate["last_discovery"]["virtual_s"] - reference["last_discovery"]["virtual_s"],
        after_last_discovery_delta_s=candidate["after_last_discovery"]["total_s"] - reference["after_last_discovery"]["total_s"],
        unknown_after_last_discovery_delta_s=candidate["unknown_measure_after_last_discovery"]["total_s"] - reference["unknown_measure_after_last_discovery"]["total_s"],
        after_last_clear_delta_s=candidate["after_last_clear"]["total_s"] - reference["after_last_clear"]["total_s"])


def run(output, allow_research_fallback=False):
    output = Path(output).resolve()
    if OUTPUT_ROOT.resolve() not in output.parents:
        raise ValueError("诊断输出必须位于outputs/q4/<批次>")
    formal = OUTPUT_ROOT / "holdout01"
    if complete_batch(formal, ("baseline", "joint25", "selected")):
        holdout, selected, source_type = formal, "selected", "src正式复算"
    elif allow_research_fallback:
        holdout, selected, source_type = PROJECT / "outputs/experiments/q4/holdout01", "shared", "研究确认暂代，formal未完整"
    else:
        raise ValueError("正式holdout尚未完整；不将部分结果作为完整确认诊断")
    batches = [("pressure", OUTPUT_ROOT / "pressure01", "selected", "src正式复算"),
               ("holdout", holdout, selected, source_type)]
    sources, traces, comparisons, batch_info = {}, {}, [], []
    for label, folder, chosen, kind in batches:
        if not complete_batch(folder, ("baseline", "joint25", chosen)):
            raise ValueError(f"批次未完整: {folder}")
        rows = read(folder / "results.json")
        for name in ("manifest.json", "results.json", "cases.json"):
            p = folder / name
            sources[p.relative_to(PROJECT).as_posix()] = sha(p)
        batch_traces = {}
        for row in rows:
            value = trace_metrics(folder, row, sources)
            batch_traces[(row["case"], row["policy"])] = value
            traces[f"{label}/{row['case']}/{row['policy']}"] = value
        for (case, policy), candidate in batch_traces.items():
            if policy == chosen:
                for reference in ("baseline", "joint25"):
                    comparisons.append(compare(candidate, batch_traces[(case, reference)], label))
        batch_info.append(dict(batch=label, path=folder.relative_to(PROJECT).as_posix(), selected=chosen,
                               source_type=kind, cases=len(rows)//3, all_complete=True))
    regressions = sorted([p for p in comparisons if p["extra_s"] > 1e-6], key=lambda p: (p["batch"], -p["extra_s"]))
    result = dict(created_at_utc=datetime.now(timezone.utc).isoformat(), batches=batch_info,
        diagnostic_source_sha256=sha(__file__), input_sha256=sources,
        definitions=dict(unknown_measure="检测前尚无公开存在证据的频道", after_last_discovery="末次首次发现之后的全部动作费用",
            unknown_after_last_discovery="末次首次发现后仍检测尚未发现频道的实际费用，包含归入到达动作的移动",
            after_last_clear="最后一次成功清除后至退出前的查漏尾段",
            movement_attribution="移动归到本次实际动作；不等于该动作可以独立省掉的距离"),
        traces=traces, comparisons=comparisons, regressions=regressions,
        interpretation_limit="完整同例费用差是观测事实；动作归类和时段差是事后账本解释，不是替换动作的因果或最优性证明")
    output.mkdir(parents=True, exist_ok=True)
    (output / "diagnostics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "source").mkdir(exist_ok=True)
    (output / "source/diagnose_regressions.py").write_bytes(Path(__file__).read_bytes())
    write_report(result, output)
    return result


def write_report(result, output):
    lines = ["# 第四问退步案例与适用边界诊断", "", "这里只分析已完成同案例轨迹，不再调参或执行策略。全部动作费用重新独立计算并与原账本、公开时间、最终清除数核对。", ""]
    for b in result["batches"]:
        lines.append(f"来源：{b['batch']}，{b['cases']}例，{b['source_type']}，`{b['path']}`。")
    worst_regression=max(result['regressions'],key=lambda p:p['extra_s'])
    worst_trace=result['traces'][f"{worst_regression['batch']}/{worst_regression['case']}/{worst_regression['selected']}"]
    worst_ref=result['traces'][f"{worst_regression['batch']}/{worst_regression['case']}/{worst_regression['reference']}"]
    lines += ["", f"最值得保留的退步边界是：{worst_regression['case']}虽全清，却比{worst_regression['reference']}慢{worst_regression['extra_s']/60:.2f}分钟；双方失败清除分别为{len(worst_trace['failed_clear_events'])}次和{len(worst_ref['failed_clear_events'])}次。该局额外时间来自移动和检测，不能用“清除失败较少”证明整局效率好。", "", "另一个边界是发现、清除和证明不存在的完成时点不同：较早发现全部实际源，仍可能留下较多定位任务或未知频道查漏。下面逐例给出实际账本与时点，所有研究holdout复算案例只计一次，共32个不同场景。"]
    lines += ["", "## 全部配对与退步范围", "", "正值表示selected/shared比参照慢；时间单位秒。", "", "| 批次 | 参照 | 全清配对 | 退步局 | 最多增加秒 |", "|---|---|---:|---:|---:|"]
    for b in result["batches"]:
        for ref in ("baseline", "joint25"):
            pairs = [p for p in result["comparisons"] if p["batch"] == b["batch"] and p["reference"] == ref]
            lines.append(f"| {b['batch']} | {ref} | {len(pairs)} | {sum(p['extra_s'] > 1e-6 for p in pairs)} | {max(0.,max(p['extra_s'] for p in pairs)):.2f} |")
    lines += ["", "| 退步案例 | 参照 | 总增加 | 移动差 | 检测差 | 切频差 | 失败清除费差 |", "|---|---|---:|---:|---:|---:|---:|"]
    for p in result["regressions"]:
        d = p["cost_delta_s"]
        lines.append(f"| {p['case']} | {p['reference']} | {p['extra_s']:.2f} | {d['move_s']:.2f} | {d['measure_s']:.2f} | {d['switch_s']:.2f} | {d['failed_clear_s']:.2f} |")
    lines += ["", "## 如何解释轨迹", "", "首次发现指频道第一次收到direction/near，或首次清除成功。末次首次发现是最后一个真实源首次得到公开存在证据的时点；它之后仍可能需要定位清除，并不等于纯查漏。本文另外单列该时点之后的未知频道检测，以及最后一次成功清除之后的纯查漏尾段。", "", "移动按实际到达动作归类，检测费为5秒、切频1秒、成功清除5秒、失败3秒。这种分类能准确加回整局费用，但无法证明取消某一动作就能省掉归到该动作的整段路程。"]
    for p in result["regressions"]:
        c = result["traces"][f"{p['batch']}/{p['case']}/{p['selected']}"]
        r = result["traces"][f"{p['batch']}/{p['case']}/{p['reference']}"]
        lines += ["", f"## {p['case']}：相对{p['reference']}增加{p['extra_s']:.2f}秒", "", f"双方均清除{c['cleared_count']}个源；selected/shared用时{c['virtual_s']:.2f}秒，参照{r['virtual_s']:.2f}秒，增加{100*p['extra_fraction']:.2f}%。", "", "| 公开轨迹指标 | selected/shared | 参照 |", "|---|---:|---:|"]
        metrics = [("首次发现时间", c['first_discovery']['virtual_s'], r['first_discovery']['virtual_s']),
            ("末次首次发现时间", c['last_discovery']['virtual_s'], r['last_discovery']['virtual_s']),
            ("末次首次发现后全部费用", c['after_last_discovery']['total_s'], r['after_last_discovery']['total_s']),
            ("其中未知频道检测及其到达移动", c['unknown_measure_after_last_discovery']['total_s'], r['unknown_measure_after_last_discovery']['total_s']),
            ("最后清除后的查漏尾段", c['after_last_clear']['total_s'], r['after_last_clear']['total_s']),
            ("末次首次发现时尚未清除源数", len(c['uncleared_at_last_discovery']), len(r['uncleared_at_last_discovery'])),
            ("已发现源补测次数", c['groups'].get('known_measure',empty_cost())['count'], r['groups'].get('known_measure',empty_cost())['count']),
            ("已发现源补测仍无信号次数", c['known_no_signal_count'], r['known_no_signal_count']),
            ("失败清除次数", len(c['failed_clear_events']), len(r['failed_clear_events'])),
            ("到失败清除点的移动费用", c['groups'].get('clear_failed',empty_cost())['move_s'], r['groups'].get('clear_failed',empty_cost())['move_s'])]
        lines.extend(f"| {name} | {a:.2f} | {b:.2f} |" for name,a,b in metrics)
        lines += ["", "整局按动作对象的费用差："]
        for group, delta in sorted(p['action_group_delta_s'].items(),key=lambda v:-abs(v[1])):
            if abs(delta) > .005:
                lines.append(f"- {GROUP_NAMES[group]}：{delta:+.2f}秒（包含归到该动作的移动）。")
        d=p['cost_delta_s']
        positive=sorted(((k,v) for k,v in d.items() if v>.005),key=lambda v:-v[1])
        names={'move_s':'移动','measure_s':'检测','switch_s':'切频','failed_clear_s':'失败清除操作','success_clear_s':'成功清除操作'}
        explanation='、'.join(f"{names[k]}增加{v:.2f}秒" for k,v in positive)
        lines += ["", f"观测结论：总退步在账本上体现为{explanation}。末次发现时间差{p['last_discovery_delta_s']:+.2f}秒，加上其后费用差{p['after_last_discovery_delta_s']:+.2f}秒，恰好组成整局差。", "", "解释边界：两条策略走过不同位置、得到不同反馈、以不同顺序发现和清除目标；这些费用差不能证明单独更换某个测点就能恢复差额，也不能仅凭末次发现更早就判断整局更快。"]
        observations=[]
        if c['known_no_signal_count'] > r['known_no_signal_count']:
            cn=c['groups'].get('known_measure',empty_cost())['count'];rn=r['groups'].get('known_measure',empty_cost())['count']
            observations.append(f"在已发现源补测中，selected/shared无信号{c['known_no_signal_count']}/{cn}次，参照{r['known_no_signal_count']}/{rn}次。无信号仍可收紧距离/朝向约束，不能等同完全无价值；仅凭反馈也不能区分背向与超距离。")
        if c['shared_plan_adoptions']==0:
            observations.append("本局规划记录中没有获准的共享替站方案；不能期待共享替站在这条轨迹上抵消其他检测和移动开销。此处是执行记录事实，不表示所有同类布局都无法替站。")
        if c['source_count']==16 and c['unknown_measure_after_last_discovery']['count']==0:
            observations.append("本局发现第16个源后不再检测未知频道，末尾不存在额外未知频道查漏；应从之前交错的发现、补测与访问路线，以及剩余定位清除费用解释差异，不能将退步归为最终查漏。")
        operation_delta=d['measure_s']+d['switch_s']+d['failed_clear_s']
        if d['move_s']>0 and operation_delta<0:
            observations.append(f"检测、切频和失败操作合计省{-operation_delta:.2f}秒，但多移动{d['move_s']:.2f}秒，操作收益被路线费用抵消。")
        if c['after_last_clear']['total_s']>0:
            observations.append(f"已把实际源全部清除后，本策略仍花{c['after_last_clear']['total_s']:.2f}秒完成未知频道查漏。运行时尚不知道真实源数，这段费用不能直接删除；它反映当时定位清除与不存在证明尚未同步闭合。")
        if p['last_discovery_delta_s']<0 and p['after_last_discovery_delta_s']>0:
            observations.append(f"本策略较早完成实际源首次发现（早{-p['last_discovery_delta_s']:.2f}秒），但之后多花{p['after_last_discovery_delta_s']:.2f}秒；更早发现的收益没有完全转成更早结束。")
        if len(c['failed_clear_events'])<len(r['failed_clear_events']):
            observations.append("失败清除更少仍然退步，说明失败次数仅是诊断指标，不能替代完整T/N目标。")
        lines += ["", "这些日志支持的具体边界："]
        lines.extend('- '+s for s in observations)
        top=sorted(c['per_channel_counts'].items(),key=lambda kv:(-kv[1].get('known_no_signal',0),int(kv[0])))[:3]
        if any(v.get('known_no_signal',0) for _,v in top):
            lines += ["", "无信号补测最集中的频道为："+'；'.join(f"频道{j}，已发现后检测{v.get('known_measure',0)}次、其中无信号{v.get('known_no_signal',0)}次" for j,v in top if v.get('known_no_signal',0))+"。"]
        lines += ["", "成功清除顺序：selected/shared为"+'→'.join(str(e['channel']) for e in c['successful_clears'])+"；参照为"+'→'.join(str(e['channel']) for e in r['successful_clears'])+"。顺序由各自反馈与行动选择形成，并非随机分组。"]
        for label,t in (("selected/shared",c),("参照",r)):
            e=t['last_discovery'];f=t['last_clear']
            lines.append(f"{label}末次首次发现为动作{e['step']}、频道{e['channel']}、位置{e['position']}；最后成功清除为动作{f['step']}、频道{f['channel']}。原始轨迹：`{t['actions_source']}`。")
    lines += ["", "## 绝对最慢案例与论文边界", ""]
    for b in result['batches']:
        selected=[t for key,t in result['traces'].items() if key.startswith(b['batch']+'/') and t['policy']==b['selected']]
        worst=max(selected,key=lambda t:t['virtual_s']);per=max(selected,key=lambda t:t['per_source_s'])
        lines.append(f"{b['batch']}整局最慢为{worst['case']}：{worst['virtual_s']/60:.4f}分钟、{worst['cleared_count']}源全清，其中移动{worst['total']['move_s']:.2f}秒，检测/切频{worst['total']['measure_s']+worst['total']['switch_s']:.2f}秒。按秒/源最慢为{per['case']}，{per['per_source_s']:.4f}秒/源；两个最差口径不能混用。")
    lines += ["", "本次结果支持样本平均改善，不能声称每例更快。共享路线费用仍是局部近似：发现顺序、已发现源的后续补测和剩余未知频道查漏共同决定总时间；认证覆盖只负责完成证据，不提供全局最短路线。完整退步列表保留，未按本次确认结果重新调参。", "", "本报告给出的具体费用与时间节点是日志事实；将其联系到边界朝向、局部估价或路线重排的机制解释仍需对照干预才能确认。固定场景名称中的布局/噪声标签不等于已验证的因果变量。所有完整配对及来源SHA256见diagnostics.json。"]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=OUTPUT_ROOT/"diagnostics01")
    parser.add_argument("--allow-research-fallback",action="store_true")
    args=parser.parse_args()
    data=run(args.output,args.allow_research_fallback)
    print(json.dumps(dict(batches=data['batches'],regressions=len(data['regressions']),traces=len(data['traces'])),ensure_ascii=False))
