"""只读核验 Q3 搬迁、冻结指纹及 F3/F3改的既有24例；不运行策略。

历史路径通过 organization_manifest.json 映射到当前位置。旧脚本中的路径和
旧运行命令并不会因此自动兼容；本文件仅提供显式路径解析与独立归档核验。
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics
from urllib.parse import unquote


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MANIFEST = HERE / "organization_manifest.json"
RUN = ROOT / "outputs/experiments/b_q3_p1/f3_modified_micro24_20260913"
OUTPUT = ROOT / "outputs/experiments/b_q3_organization_20260913/validation.json"
COST_KEYS = ("move_s", "measure_s", "switch_s", "success_clear_s", "fail_clear_s")


class ValidationError(ValueError):
    """可向整理者直接解释的核验错误。"""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path, lf=False):
    data = Path(path).read_bytes()
    if lf:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def close(actual, expected, label):
    require(math.isfinite(actual) and math.isfinite(expected)
            and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-6),
            f"数值不一致：{label}: {actual!r} != {expected!r}")


def repository_relative(value):
    """只接受仓库内路径；Windows和POSIX分隔符均可。"""
    raw = str(value).replace("\\", "/")
    if Path(raw).is_absolute():
        try:
            raw = Path(raw).resolve().relative_to(ROOT).as_posix()
        except ValueError as exc:
            raise ValidationError(f"路径不在仓库内：{value}") from exc
    path = PurePosixPath(raw)
    require(not path.is_absolute() and ".." not in path.parts
            and not re.match(r"^[A-Za-z]:", raw), f"非法仓库相对路径：{value}")
    require(bool(path.parts), "路径不得为空")
    return path.as_posix()


def load_manifest(path=MANIFEST):
    path = Path(path)
    require(path.is_file(), f"缺少整理清单：{path}。请先完成搬迁并生成 organization_manifest.json。")
    manifest = read(path)
    require(isinstance(manifest, dict) and isinstance(manifest.get("files"), list),
            "整理清单必须包含 files 列表")
    return manifest


class OrganizationResolver:
    """按照逐文件映射读取历史路径，未搬迁的仓库外部依赖保持原位置。"""

    def __init__(self, manifest=None):
        self.manifest = load_manifest() if manifest is None else manifest
        require(isinstance(self.manifest.get("files"), list), "整理清单缺少 files 列表")
        self.mapping = {}
        self.entries = []
        targets = set()
        for entry in self.manifest["files"]:
            require(isinstance(entry, dict) and all(k in entry for k in ("old", "new", "sha256")),
                    f"不完整的搬迁记录：{entry!r}")
            old = repository_relative(entry["old"])
            new = repository_relative(entry["new"])
            require(old.casefold() not in self.mapping, f"重复旧路径：{old}")
            require(new.casefold() not in targets, f"重复目标路径：{new}")
            destination = ROOT / new
            require(destination.resolve().is_relative_to(HERE), f"目标越出 b_q3：{new}")
            require(re.fullmatch(r"[0-9a-fA-F]{64}", entry["sha256"]) is not None,
                    f"SHA256格式错误：{old}")
            self.mapping[old.casefold()] = destination
            targets.add(new.casefold())
            self.entries.append(dict(old=old, new=new, sha256=entry["sha256"].lower()))
        require(bool(self.entries), "整理清单 files 为空，不能证明搬迁完整")

    def resolve(self, old_path):
        relative = repository_relative(old_path)
        return self.mapping.get(relative.casefold(), ROOT / relative)


def resolve(old_path, manifest=None):
    """公开接口：旧仓库相对路径 -> 当前 Path；不修改或复制任何文件。

    批量查询可构造 OrganizationResolver(manifest)，重复调用其 resolve 方法。
    """
    return OrganizationResolver(manifest).resolve(old_path)


def verify_hash_map(mapping, resolver, label, lf=False):
    require(isinstance(mapping, dict) and bool(mapping), f"指纹清单为空或格式错误：{label}")
    for relative, expected in mapping.items():
        path = resolver.resolve(relative)
        require(path.is_file(), f"{label} 缺少文件：{relative} -> {path}")
        require(sha256(path, lf=lf) == expected, f"{label} 指纹不一致：{relative} -> {path}")
    return len(mapping)


def verify_organization(resolver):
    total_bytes = 0
    for entry in resolver.entries:
        path = ROOT / entry["new"]
        require(path.is_file(), f"搬迁目标不存在：{entry['new']}")
        require(sha256(path) == entry["sha256"], f"原文件字节改变：{entry['old']} -> {entry['new']}")
        total_bytes += path.stat().st_size
    external = resolver.manifest.get("external_dependencies", {})
    if isinstance(external, list):
        require(all(isinstance(e, dict) and "path" in e and "sha256" in e for e in external),
                "external_dependencies 列表必须使用 {path, sha256}")
        require(len({repository_relative(e['path']).casefold() for e in external}) == len(external),
                "external_dependencies 有重复路径")
        external = {e["path"]: e["sha256"] for e in external}
    require(isinstance(external, dict), "external_dependencies 必须为路径/指纹字典或记录列表")
    count = verify_hash_map(external, resolver, "外部依赖") if external else 0
    return dict(files=len(resolver.entries), bytes=total_bytes, external_dependencies=count,
                unique_old_paths=True, unique_new_paths=True, all_targets_inside_q3=True,
                all_original_bytes_preserved=True)


def verify_record(case, directory, resolver):
    """核验已有日志的终态、计费与全清；不调用控制器或模拟器。"""
    paths = {name: resolver.resolve(f"{directory}/{name}")
             for name in ("result.json", "actions.jsonl", "metadata.json")}
    for path in paths.values():
        require(path.is_file(), f"缺少完整轨迹文件：{path}")
    result = read(paths["result.json"])
    read(paths["metadata.json"])
    n = len(case["sources"])
    label = f"{case['name']} @ {directory}"
    require(result["case"] == case["name"] and result["success"] is True
            and result["cleared"] == n, f"结果不是对应案例全清：{label}")
    for field in ("real_n", "source_count"):
        if field in result:
            require(result[field] == n, f"源数不符：{field}, {label}")
    close(result["per_source_s"], result["total_s"] / n, f"T/N {label}")
    close(result["total_s"], sum(result[k] for k in COST_KEYS), f"费用分解 {label}")
    rows = [json.loads(line) for line in paths["actions.jsonl"].read_text(encoding="utf-8").splitlines()
            if line.strip()]
    require(rows and len(rows) == result["actions"], f"动作数不符：{label}")
    position, channel, total = (0.0, 0.0), 1, 0.0
    sums = {key: 0.0 for key in COST_KEYS}
    cleared = []
    for row in rows:
        response = row["response"]
        require(response.get("accepted") is True, f"轨迹含未接受动作：{label}")
        costs = {key: 0.0 for key in COST_KEYS}
        costs["move_s"] = math.dist(position, row["position"]) / 5.0
        if row["kind"] == "measure":
            costs["measure_s"] = 5.0
            costs["switch_s"] = float(row["channel"] != channel)
            channel = row["channel"]
        elif row["kind"] == "clear":
            if response.get("clear_result") == "success":
                costs["success_clear_s"] = 5.0
                cleared.append(row["channel"])
            else:
                costs["fail_clear_s"] = 3.0
        else:
            raise ValidationError(f"未知动作类型：{row['kind']}, {label}")
        total += sum(costs.values())
        close(total, response["virtual_time_s"], f"动作累计费用 {label}, step={row.get('step')}")
        for key in COST_KEYS:
            sums[key] += costs[key]
            if "independent_costs" in row:
                close(costs[key], row["independent_costs"][key], f"动作费用 {key}, {label}")
        position = row["position"]
    expected_channels = {source["channel"] for source in case["sources"]}
    require(len(cleared) == len(set(cleared)) == n and set(cleared) == expected_channels,
            f"成功清除频道与源不一致：{label}")
    final_counts = rows[-1]["after"]["counts"]
    require(final_counts["unknown"] == 0 and final_counts["found"] == 0
            and final_counts["cleared"] == n, f"日志终态未完成查漏及全清：{label}")
    close(total, result["total_s"], f"整局总费用 {label}")
    for key in COST_KEYS:
        close(sums[key], result[key], f"累计费用 {key}, {label}")
    return result, len(rows)


def summarize(pairs):
    count = len(pairs)
    sources = sum(pair["n"] for pair in pairs)
    metrics = {}
    for label in ("baseline", "candidate"):
        records = [pair[label] for pair in pairs]
        total = sum(record["total_s"] for record in records)
        metrics[label] = dict(sum_total_s=total, mean_total_s=total / count,
            mean_per_source_s=statistics.mean(record["total_s"] / pair["n"]
                                             for pair, record in zip(pairs, records)),
            pooled_per_source_s=total / sources,
            max_total_s=max(record["total_s"] for record in records))
    savings = [pair["baseline"]["total_s"] - pair["candidate"]["total_s"] for pair in pairs]
    return dict(cases=count, source_count=sources, all_clear=True,
        clear_counts={"baseline": count, "candidate": count}, metrics=metrics,
        mean_saving={key: statistics.mean(pair["baseline"][key] - pair["candidate"][key]
                                         for pair in pairs)
                     for key in ("total_s", "per_source_s") + COST_KEYS},
        sum_saving_s=sum(savings), median_saving_s=statistics.median(savings),
        wins=sum(value > 1e-6 for value in savings), losses=sum(value < -1e-6 for value in savings),
        ties=sum(abs(value) <= 1e-6 for value in savings))


def compare_summary(recomputed, recorded, label):
    for key in ("cases", "source_count", "all_clear", "clear_counts", "wins", "losses", "ties"):
        require(recomputed[key] == recorded[key], f"汇总字段不一致：{label}.{key}")
    for method, metrics in recomputed["metrics"].items():
        for key, value in metrics.items():
            close(value, recorded["metrics"][method][key], f"{label}.{method}.{key}")
    for key, value in recomputed["mean_saving"].items():
        close(value, recorded["mean_saving"][key], f"{label}.mean_saving.{key}")
    for key in ("sum_saving_s", "median_saving_s"):
        close(recomputed[key], recorded[key], f"{label}.{key}")


def verify_f3_comparison(resolver):
    manifest, analysis = read(RUN / "manifest.json"), read(RUN / "analysis.json")
    cases, completion = read(RUN / "cases.json"), read(RUN / "completion.json")
    counts = {}
    for key in ("code_hashes", "input_hashes", "dependency_hashes_lf"):
        counts[key] = verify_hash_map(manifest[key], resolver, key, lf=key.endswith("_lf"))
    counts["analysis_source_hashes"] = verify_hash_map(analysis["source_hashes"], resolver, "analysis.source_hashes")
    require(len(cases) == len(manifest["cases"]) == completion["finished"] == 24
            and completion["all_clear"] is True, "普通24例批次不完整")
    require(completion["reused"] == 8 and completion["new_finished"] == 16, "复用8例/新增16例计数不符")
    entries = {entry["name"]: entry for entry in manifest["cases"]}
    stored_pairs = {pair["case"]: pair for pair in analysis["pairs"]}
    require(len(entries) == len(stored_pairs) == 24 and len({c['name'] for c in cases}) == 24,
            "案例名或配对记录重复/遗漏")
    pairs, actions = [], 0
    for case in cases:
        name = case["name"]
        require(name in entries and name in stored_pairs, f"缺少配对案例：{name}")
        entry, stored = entries[name], stored_pairs[name]
        require(canonical(case) == entry["case_sha256"] and len(case["sources"]) == entry["source_count"],
                f"案例输入/源数指纹不符：{name}")
        require(stored["n"] == entry["source_count"] and stored["reused"] == entry["reused"],
                f"analysis配对源数/来源不符：{name}")
        pair = dict(case=name, n=entry["source_count"], reused=entry["reused"])
        for label, field in (("baseline", "baseline_dir"), ("candidate", "candidate_dir")):
            result, length = verify_record(case, entry[field], resolver)
            require(stored[label]["result"] == result, f"analysis结果与原日志不同：{label}, {name}")
            pair[label] = result
            actions += length
        for key in ("total_s", "per_source_s") + COST_KEYS:
            close(pair["baseline"][key] - pair["candidate"][key], stored["saving"][key], f"逐例节省 {name}.{key}")
        pairs.append(pair)
    require(sum(pair["reused"] for pair in pairs) == 8, "不是8个复用案例")
    groups = {"all24": pairs, "new16": [p for p in pairs if not p["reused"]],
              "reused8": [p for p in pairs if p["reused"]]}
    summaries = {name: summarize(group) for name, group in groups.items()}
    for name, summary in summaries.items():
        compare_summary(summary, analysis["groups"][name], name)
    require(analysis["validation"]["trajectories"] == 48
            and analysis["validation"]["actions"] == actions, "历史核验轨迹/动作计数不符")
    counts.update(cases=24, reused=8, newly_run_historical=16, trajectories=48, actions=actions)
    return dict(counts=counts, groups=summaries, frozen_hashes_preserved=True,
                all_clear_records_verified=True, independent_cost_accounting_verified=True,
                scope="仅核对历史字节、既有动作计费、全清终态及指标；没有重跑策略或几何反馈模拟")


def verify_readme_links():
    documents = [HERE / "README.md", HERE / "other_attempts/README.md"]
    final = HERE / "final_methods"
    require(final.is_dir(), "缺少 final_methods 目录")
    documents += sorted(final.rglob("README.md"))
    checked, skipped = 0, 0
    for document in documents:
        require(document.is_file(), f"缺少新入口README：{document}")
        text = re.sub(r"(?ms)^\s*```.*?^\s*```[^\n]*", "", document.read_text(encoding="utf-8"))
        for match in re.finditer(r"!?\[[^\]]*\]\((<[^>]+>|[^)\n]+)\)", text):
            href = match.group(1).strip()
            if href.startswith("<"):
                href = href[1:-1]
            else:
                href = re.split(r"\s+[\"']", href, maxsplit=1)[0]
            if href.startswith("#") or re.match(r"^(?:https?|mailto|data|app|codex):", href, re.I):
                skipped += 1
                continue
            href = unquote(href.split("#", 1)[0].split("?", 1)[0])
            href = re.sub(r":\d+(?::\d+)?$", "", href)
            target = Path(href)
            if not target.is_absolute():
                target = document.parent / target
            require(target.exists(), f"新README本地链接失效：{document.relative_to(ROOT)} -> {href}")
            checked += 1
    return dict(documents=len(documents), local_links=checked, remote_or_anchor_links_skipped=skipped,
                all_checked_local_links_exist=True, historical_markdown_not_rewritten=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check-links", action="store_true", help="额外检查新README的本地链接")
    mode.add_argument("--resolve", metavar="OLD_PATH", help="只查询旧文件路径，不核验全量结果或写入记录")
    args = parser.parse_args()
    if args.resolve is not None:
        try:
            path = resolve(args.resolve).resolve()
            require(path.is_file(), f"旧路径对应的文件不存在：{args.resolve} -> {path}")
        except (ValidationError, OSError, KeyError, TypeError, ValueError) as exc:
            parser.exit(1, f"路径查询失败：{exc}\n")
        print(path)
        return 0
    report = dict(ok=False, checked_at_utc=datetime.now(timezone.utc).isoformat(),
                  manifest=MANIFEST.relative_to(ROOT).as_posix(), no_strategy_execution=True)
    try:
        resolver = OrganizationResolver()
        report["organization"] = verify_organization(resolver)
        report["f3_comparison"] = verify_f3_comparison(resolver)
        if args.check_links:
            report["readme_links"] = verify_readme_links()
        report["ok"] = True
    except (ValidationError, OSError, KeyError, TypeError, ValueError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["ok"]:
        counts = report["f3_comparison"]["counts"]
        print(f"核验通过：{report['organization']['files']}个原文件字节保持；"
              f"24对结果、{counts['trajectories']}条历史轨迹、{counts['actions']}个动作一致。")
    else:
        print(f"核验失败：{report['error']}")
    print(f"核验记录：{OUTPUT}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
