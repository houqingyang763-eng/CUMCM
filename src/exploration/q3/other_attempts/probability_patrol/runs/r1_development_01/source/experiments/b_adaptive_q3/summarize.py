"""读取已完成的独立案例实验，生成对照报告；不挑选或改变策略参数。"""
import argparse
import json
import math
import statistics
from pathlib import Path

from run_local import ROOT, digest, percentile, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=ROOT / "runs" / "holdout")
    args = parser.parse_args()
    run = args.run.resolve()
    results = json.loads((run / "results.json").read_text(encoding="utf-8"))
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert digest(run / "cases.json") == manifest["case_sha256"]
    assert digest(run / "config.json") == manifest["config_sha256"]
    for name, value in manifest["code_sha256"].items():
        assert digest(run / "source" / name) == value, (name, "运行源代码快照不符")
        assert digest(ROOT / name) == value, (name, "当前代码在独立测试后改变，应重新标记结果范围")
    dev = json.loads((ROOT / "runs" / "development" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config_sha256"] == dev["config_sha256"], "独立测试参数发生改变"
    for name in ("geometry.py", "state.py", "policy.py", "simulation.py"):
        assert manifest["code_sha256"][name] == dev["code_sha256"][name], "开发后核心改变"
    a = [r for r in results if r["policy"] == "adaptive"]
    b = [r for r in results if r["policy"] == "reference"]
    by_case = {r["case"]: r for r in b}
    assert len(a) == len(b) == 24
    assert all(r["success"] and r["cleared"] == r["source_count"] for r in results)
    cases = json.loads((run / "cases.json").read_text(encoding="utf-8"))
    dev_cases = json.loads((ROOT / "runs" / "development" / "cases.json").read_text(encoding="utf-8"))
    assert not {s["seed"] for s in cases} & {s["seed"] for s in dev_cases}
    total = sum(r["virtual_time_s"] for r in a)
    fractions = {k: sum(r[k] for r in a) / total for k in ("move_s", "measure_s", "switch_s", "clear_s")}
    mean_a, mean_b = (statistics.mean(r["virtual_time_s"] for r in x) for x in (a, b))
    slower = [r for r in a if r["virtual_time_s"] > by_case[r["case"]]["virtual_time_s"]]
    worst = max(a, key=lambda r: r["virtual_time_s"])
    # 已落盘流水重新核对，独立于模拟器内部成本字段。
    audited_actions = 0
    for result in results:
        trace = run / "actions" / f"{result['case']}_{result['policy']}.jsonl"
        rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == result["actions"]
        q0, j0, time_s = (0, 0), 1, 0.0
        for r in rows:
            q, j = r["position"], r["channel"]
            time_s += math.hypot(q[0] - q0[0], q[1] - q0[1]) / 5
            if r["kind"] == "measure":
                time_s += 5 + int(j != j0)
                j0 = j
            else:
                time_s += 5 if r["response"]["clear_result"] == "success" else 3
            q0 = q
            assert abs(time_s - r["response"]["virtual_time_s"]) < 1e-5
        audited_actions += len(rows)
        assert abs(time_s - result["virtual_time_s"]) < 1e-5
    write_json(run / "analysis.json", dict(
        case_count=len(a), source_count=sum(r["source_count"] for r in a),
        improvement_of_mean=1 - mean_a / mean_b, paired_wins=len(a) - len(slower),
        costs_fraction=fractions, slower_cases=[r["case"] for r in slower],
        audit_actions=audited_actions, current_code_matches=True, parameters_frozen=True))
    lines = ["# 第三问基础策略：首轮实施结果", "", "日期：2026-09-11。状态：本地候选原型，可继续优化；尚未连接官方模拟器。", "",
        f"**独立案例中的 {len(a)} 局全部完成，清除 {sum(r['cleared'] for r in a)} 个源；逐动作真值检查未发现误删真实位置、错误提前结束或计时不一致。**", "",
        f"相同案例下，动态基础策略的整局平均虚拟时间比朴素参考完成程序低 {(1-mean_a/mean_b)*100:.1f}%。{len(a)-len(slower)} 局更快，{len(slower)} 局更慢。参照只是一遍发现后按清除格收尾的正确性参照，不能代表优秀算法的速度。", "",
        "## 已实际执行什么", "", "先完成 4 个冒烟案例并修复规则，再用 12 个开发案例检查。随后冻结参数及四个核心模块，使用不同种子的 24 个独立案例；每个案例分别跑动态策略与同一程序内的参考完成模式。", "",
        "独立案例包含圆域内分散、圆周边界、三团聚集、近共线四类布局，每类配平滑空间误差、固定 ±1° 偏差、按位置固定的散列误差，每组合两个种子。源数覆盖 10—16；边界和近共线案例接收半径固定 1000 米，其余在 1000—1500 米内生成。误差场及布局均为团队自建测试条件，不是官方分布。", "",
        "## 速度与尾部", "", "下表时间均为模拟中的虚拟秒；统计口径为整局。", "",
        "| 指标 | 动态基础策略 | 朴素参考完成 |", "|---|---:|---:|"]
    for label, fn in [("均值", statistics.mean), ("中位数", statistics.median),
                      ("样本 P95", lambda v: percentile(v, .95)),
                      ("最慢 10% 均值（向上取整 3 局）", lambda v: statistics.mean(sorted(v)[-math.ceil(len(v)*.1):])),
                      ("最慢一局", max)]:
        values = [fn([r["virtual_time_s"] for r in x]) for x in (a, b)]
        lines.append(f"| {label} | {values[0]:.2f} | {values[1]:.2f} |")
    lines += ["", f"动态策略 {len(a)} 局现实计算合计 {sum(r['wall_time_s'] for r in a):.2f} 秒，单局最慢 {max(r['wall_time_s'] for r in a):.2f} 秒，包含真值审计；不包含 HTTP、官方程序延迟和倒计时。当前没有据此声称前瞻计算一定满足官方 20 分钟限制。", "",
        "| 布局 | 动态均值/秒 | 参照均值/秒 |", "|---|---:|---:|"]
    for layout, label in [("uniform", "分散"), ("edge", "边界"), ("cluster", "聚集"), ("line", "近共线")]:
        vals = [statistics.mean(r["virtual_time_s"] for r in x if r["layout"] == layout) for x in (a, b)]
        lines.append(f"| {label} | {vals[0]:.2f} | {vals[1]:.2f} |")
    lines += ["", "两局反例全部保留：", "", "| 案例 | 动态/秒 | 参照/秒 | 动态慢多少 |", "|---|---:|---:|---:|"]
    for r in slower:
        ref = by_case[r["case"]]["virtual_time_s"]
        lines.append(f"| {r['case']} | {r['virtual_time_s']:.2f} | {ref:.2f} | {(r['virtual_time_s']/ref-1)*100:.1f}% |")
    lines += ["", "## 这轮最重要的发现", "",
        f"1. 时间主要花在移动：按独立案例总虚拟时间加权，移动占 {fractions['move_s']*100:.1f}%，检测占 {fractions['measure_s']*100:.1f}%，切换占 {fractions['switch_s']*100:.1f}%，清除占 {fractions['clear_s']*100:.1f}%。这说明后续评价应关注后面整段路程，局部缩面积并不充分。", "",
        f"2. 探测位置数未被硬性固定：动态策略范围 {min(r['scan_position_count'] for r in a)}—{max(r['scan_position_count'] for r in a)}，中位数 {statistics.median(r['scan_position_count'] for r in a):g}。这些位置包括搜索和局部定位；7 个参照点只服务发现完整性，不能与动态全部探测点直接比较成效率结论。", "",
        f"3. {sum(r['fallback'] for r in a)} 局触发参考完成流程，仍复用已有区域、已清除状态和扫描证据，未从头重做。动态策略清除失败总数 {sum(r['failed_clears'] for r in a)}。", "",
        f"最慢案例为 `{worst['case']}`，总虚拟时间 {worst['virtual_time_s']:.2f} 秒，其中移动 {worst['move_s']:.2f} 秒，检测 {worst['measure_s']:.2f} 秒。下轮应以边界反例和多余停靠为开发案例；它们已被查看，以后不能继续冒充未见测试。", "",
        "## 正确性证据及其边界", "", f"- 15 项单元检查覆盖附件的 199 秒计费例子、同点固定误差、临界距离、舍入与方向环绕、清除格覆盖、包围圆反例和数量上界。独立案例两种模式合计 {audited_actions} 个动作的落盘计时流水再次重算一致。", "",
        "- 策略只接收动作反馈。源真值仅在环境和测试检查器持有；每步检查尚存真实源仍在区域及保留的清除格中。检查器部分几何函数与策略共用，因此还结合了手算边界和解析构造测试，不能称独立实现的全面证明。", "",
        "- 接口角度保留两位小数，因此程序用 ±1.00500001° 容纳题面误差和舍入；局部矩形半宽由原设计 26.2 米增至 26.4 米，两行清除中心偏移 ±13.2 米。每格最大清除距离 19.98099097 米，仍小于 20 米。", "",
        "- 24 个分层自建案例不足以断言灾难性失败概率很小，也不能证明官方分布上的表现。当前只实现第三问；第四问、rollout 和 irace 尚未接入。", "",
        "## 下一步沿什么改", "", "保留状态、几何、模拟器、完成流程与审计。首先对需要移动的少量候选试用“走这一步以后，用本基础策略完成余下任务”的成本评价，观察能否减少往返；同点连续扫描不必每次重新进行昂贵前瞻。先测候选模拟的现实费用，再决定每次比较多少个，之后才做外层配置。", "",
        "## 文件与复现", "", "- [方法与运行命令](README.md)", "- [独立案例逐局表](runs/holdout/RESULTS.md)",
        "- [机器可读结果](runs/holdout/results.json)", "- [案例真值，仅供模拟器与审计](runs/holdout/cases.json)",
        "- [参数](runs/holdout/config.json) · [版本及哈希](runs/holdout/manifest.json) · [汇总核对](runs/holdout/analysis.json)", "",
        "运行目录保留源代码快照和逐动作 JSONL。结果仍属 experiments；未晋升正式论文代码，未完成人工独立复核。", ""]
    (ROOT / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(dict(paired_cases=len(a), actions_reconciled=audited_actions,
                         improvement_of_mean=1-mean_a/mean_b, report=str(ROOT / "RESULTS.md")), ensure_ascii=False))


if __name__ == "__main__":
    main()
