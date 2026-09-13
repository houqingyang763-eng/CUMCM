"""只复用已验证的公开状态与连续覆盖证明，不继承旧决策函数。"""
import importlib.util
from pathlib import Path
import sys

EXPERIMENTS = Path(__file__).resolve().parents[2]
ADAPTIVE = EXPERIMENTS / "b_adaptive_q3"
if str(ADAPTIVE) not in sys.path:
    sys.path.insert(0, str(ADAPTIVE))

_NAME = "probability_patrol_coverage_geometry"
if _NAME not in sys.modules:
    _spec = importlib.util.spec_from_file_location(_NAME, EXPERIMENTS / "b_overnight" / "coverage.py")
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_NAME] = _module
    _spec.loader.exec_module(_module)

CoverageInformationState = sys.modules[_NAME].CoverageInformationState
coverage_certificate = sys.modules[_NAME].coverage_certificate
verify_certificate = sys.modules[_NAME].verify_certificate

