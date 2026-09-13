"""用临时旧目录形状加载归档原件，保持 F3 与 F3改的原算法和历史字节。

用法::

    with runtime("F3_modified", selected=None) as session:
        policy, state = session
        action = policy.choose(state)
        # state.update(action, 公开反馈)；实际输出请写到项目 outputs/。

selected=None 沿用原 F3 的公开首站反馈选择；不会预置新开局。
deadline 是 time.perf_counter() 的绝对截止值，仅传给原 F3改 RunContext。
--check 仅校验文件、导入和构造策略，不执行动作或启动任何模拟器。
临时源码只服务本次上下文，退出即删除，不是另存一个版本。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import shutil
import sys
import tempfile
import threading
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Iterator


CORE_INPUTS = (
    "experiments/b_adaptive_q3/geometry.py",
    "experiments/b_adaptive_q3/simulation.py",
    "experiments/b_adaptive_q3/state.py",
    "experiments/b_overnight/coverage.py",
    "experiments/b_q3/probability_patrol/runner.py",
    "experiments/b_q3/probability_patrol/patrol.py",
    "experiments/b_q3/probability_patrol/coverage_state.py",
    "experiments/b_q3/probability_patrol/covering_route.py",
    "experiments/b_q3/probability_patrol/configs/r3_covering.json",
    "experiments/b_q3/adaptive_second/adaptive.py",
    "experiments/b_q3/refinement/posterior.py",
    "experiments/b_q3/refinement/refined.py",
)
MODIFIED_INPUTS = (
    "experiments/b_q3/cross_method/p1/light_route.py",
    "experiments/b_q3/cross_method/p1/relocate.py",
)
MODULE_NAMES = (
    "geometry", "simulation", "state", "probability_patrol_coverage_geometry",
    "coverage_state", "runner", "patrol", "covering_route", "adaptive",
    "posterior", "refined", "light_route", "relocate",
)
_LOCK = threading.Lock()
_UNSET = object()


def project_root() -> Path:
    """通过仓库标记定位，不依赖个人绝对路径或目录层数。"""
    for parent in Path(__file__).resolve().parents:
        if (parent / "AGENTS.md").is_file() and (parent / "experiments").is_dir():
            return parent
    raise RuntimeError("找不到同时包含 AGENTS.md 和 experiments/ 的项目根目录")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(value: str) -> Path:
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path.drive:
        raise ValueError(f"清单必须使用安全的项目相对路径：{value}")
    return path


def _mapping(root: Path) -> dict:
    path = root / "src/q3/source_manifest.json"
    if not path.is_file():
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    result = {}
    for row in document.get("files", []):
        old = _relative(row["old"]).as_posix()
        if old in result:
            raise ValueError(f"搬迁清单重复记录：{old}")
        result[old] = row
    external = document.get("external_dependencies", {})
    if isinstance(external, dict):
        external = [dict(old=old, new=old, sha256=value) if isinstance(value, str)
                    else dict(value, old=old, new=value.get("new", old))
                    for old, value in external.items()]
    for row in external:
        old = _relative(row["old"]).as_posix()
        entry = dict(row, new=row.get("new", old))
        if old in result and result[old]["sha256"] != entry["sha256"]:
            raise ValueError(f"搬迁与外部依赖清单不一致：{old}")
        result.setdefault(old, entry)
    return result


def source_file(relative: str, root: Path | None = None, mapping: dict | None = None) -> tuple[Path, dict]:
    """解析搬迁后的原件；清单尚未生成时仅允许从旧位置读取。"""
    root = project_root() if root is None else root
    mapping = _mapping(root) if mapping is None else mapping
    old = _relative(relative).as_posix()
    record = mapping.get(old)
    new = _relative(record["new"]) if record is not None else Path(old)
    path = root / new
    if not path.is_file():
        raise FileNotFoundError(f"运行依赖缺失：{old} -> {new.as_posix()}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"运行依赖越出项目目录：{new.as_posix()}")
    actual = sha256(path)
    if record is not None and actual != record["sha256"]:
        raise ValueError(f"归档原件 SHA256 不符：{new.as_posix()}")
    return path, {"old": old, "new": new.as_posix(), "sha256": actual,
                  "manifest_verified": record is not None}


@dataclass
class Session:
    """仅在 runtime 上下文内有效；支持 policy, state = session。"""

    method: str
    temp_root: Path
    modules: dict[str, ModuleType]
    copied_files: list[dict]
    selected: object = None
    context: object = None
    policy: object = None
    state: object = None
    _active: bool = field(default=True, repr=False)

    def __iter__(self):
        yield self.policy
        yield self.state

    @property
    def workspace(self):
        return self.temp_root

    @property
    def snapshot_root(self):
        return self.temp_root

    def create_policy(self, selected=_UNSET):
        """按本上下文的同一冻结方法创建策略和空公开状态。"""
        if not self._active:
            raise RuntimeError("临时运行上下文已经关闭")
        choice = self.selected if selected is _UNSET else selected
        choice = copy.deepcopy(choice)
        if self.method == "F3":
            policy = self.modules["refined"].RefinedPolicy(choice, level=3, samples=4)
        else:
            policy = self.modules["relocate"].RelocationPolicy(choice)
        state = self.modules["coverage_state"].CoverageInformationState()
        return policy, state


@contextmanager
def runtime(method: str = "F3", selected=None, deadline: float = math.inf,
            *, extra_files=()) -> Iterator[Session]:
    """加载原策略，隔离裸模块名并在退出时恢复解释器状态。

    extra_files 仅供复核历史单测补入旧相对路径的测试文件和只读数据。
    同一进程不支持嵌套或并发 runtime；多进程可各自独立使用。
    运行期间不要在其他线程导入同名归档模块。
    """
    if method not in ("F3", "F3_modified", "F3改"):
        raise ValueError("method 只接受 F3、F3_modified 或 F3改")
    method = "F3_modified" if method == "F3改" else method
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError("同一进程不能嵌套或并发使用 F3 临时运行上下文")
    saved_path = list(sys.path)
    saved_modules = {name: sys.modules[name] for name in MODULE_NAMES if name in sys.modules}
    names_before = set(sys.modules)
    session = None
    temporary_root = None
    try:
        root = project_root()
        mapping = _mapping(root)
        required = list(CORE_INPUTS)
        if method == "F3_modified":
            required.extend(MODIFIED_INPUTS)
        required.extend(extra_files)
        required = list(dict.fromkeys(required))
        # 在更改模块表之前核对所有来源，归档缺失或损坏时直接失败。
        resolved = [source_file(rel, root, mapping) for rel in required]
        with tempfile.TemporaryDirectory(prefix="cumcm_q3_") as directory:
            temporary_root = Path(directory)
            records = []
            for source, record in resolved:
                destination = temporary_root / record["old"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                if sha256(destination) != record["sha256"]:
                    raise IOError(f"临时复制校验失败：{record['old']}")
                records.append(record)
            for name in MODULE_NAMES:
                sys.modules.pop(name, None)
            q3 = temporary_root / "experiments/b_q3"
            sys.path[:0] = [str(q3 / "cross_method/p1"), str(q3 / "refinement")]
            importlib.invalidate_caches()
            importlib.import_module("refined")
            # 原 F3 在首次规划时才导入；此处提前核查，无策略动作。
            importlib.import_module("covering_route")
            with ExitStack() as stack:
                context = None
                if method == "F3_modified":
                    lr = importlib.import_module("light_route")
                    relocate = importlib.import_module("relocate")
                    context = lr.RunContext("A", deadline)
                    stack.enter_context(relocate.relocation_context(context))
                modules = {name: sys.modules[name] for name in MODULE_NAMES if name in sys.modules}
                for name, module in modules.items():
                    if not Path(module.__file__).resolve().is_relative_to(temporary_root):
                        raise RuntimeError(f"模块未从临时冻结源码加载：{name}")
                session = Session(method, temporary_root, modules, records, selected, context)
                session.policy, session.state = session.create_policy()
                try:
                    yield session
                finally:
                    session._active = False
    finally:
        if session is not None:
            session._active = False
        # 删除本次加载的所有临时模块（包括 extra_files 引入的测试模块）。
        for name, module in list(sys.modules.items()):
            file = getattr(module, "__file__", None)
            from_temporary = False
            if file is not None and temporary_root is not None:
                try:
                    from_temporary = Path(file).resolve().is_relative_to(temporary_root)
                except (OSError, ValueError, TypeError):
                    pass
            if name in MODULE_NAMES or (name not in names_before and from_temporary):
                sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        sys.path[:] = saved_path
        if temporary_root is not None:
            for key in list(sys.path_importer_cache):
                try:
                    if Path(key).is_relative_to(temporary_root):
                        sys.path_importer_cache.pop(key, None)
                except (TypeError, ValueError):
                    pass
        importlib.invalidate_caches()
        _LOCK.release()


def check() -> dict:
    """不调用 choose；验证两方案均可构造且退出后完成清理。"""
    checks = []
    original_path = list(sys.path)
    for method in ("F3", "F3_modified"):
        with runtime(method) as session:
            policy, state = session
            assert policy.level == 3 and policy.samples == 4
            assert policy.selected is None and state.actions == 0
            if session.context is not None:
                assert session.context.mode == "A"
            checks.append({"method": method, "policy": type(policy).__name__,
                           "actions": state.actions, "modules": sorted(session.modules),
                           "files": session.copied_files})
            temporary = session.temp_root
        assert not temporary.exists()
        assert sys.path == original_path
    return {"ok": True, "scope": "imports and construction only; no experiment", "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="仅检查依赖、导入和策略构造")
    args = parser.parse_args()
    if not args.check:
        parser.error("请使用 --check；实际策略通过 runtime() 上下文调用")
    print(json.dumps(check(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
