"""保存运行前源文件字节与散列；不接触凭据、模式证据或保护状态文件。"""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NIGHT = ROOT.parent


def capture_sources():
    names = ("task_cost.py", "q4.py", "q4run.py", "q4_compare.py", "q4_anchor_design.py", "q4_coverage.py",
             "q4_joint_state.py", "q2_geometry.py", "coverage.py", "astra_guard.py")
    paths = [*ROOT.glob("*.py"), *(NIGHT / name for name in names),
             *(NIGHT.parent / "b_adaptive_q3").glob("*.py"), NIGHT.parent / "b_env_probe/client.py"]
    return {path.relative_to(NIGHT.parent).as_posix(): path.read_bytes() for path in sorted(set(paths))}


def source_hashes(bundle):
    return {name: hashlib.sha256(data).hexdigest() for name, data in bundle.items()}


def save_sources(output, bundle):
    for name, data in bundle.items():
        dest = Path(output) / "source" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


def sources_unchanged(bundle):
    return all((NIGHT.parent / name).read_bytes() == data for name, data in bundle.items())
