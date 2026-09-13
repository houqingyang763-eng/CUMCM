"""单次修正的独立运行入口；保存此前S1/S2/S3代码和结果。"""
import importlib.util
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from revision import BreakthroughPolicy

spec=importlib.util.spec_from_file_location('clearability_runner',Path(__file__).with_name('run.py'))
runner=importlib.util.module_from_spec(spec);sys.modules[spec.name]=runner;spec.loader.exec_module(runner)
original=runner.UtilityPolicy
runner.UtilityPolicy=lambda selected,level:BreakthroughPolicy(selected) if level==4 else original(selected,level)
if __name__=='__main__':runner.main()
