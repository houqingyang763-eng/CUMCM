"""整站宏动作对照入口；案例、计费、限制及记录与run.py一致。"""
import importlib.util
import sys
from pathlib import Path
from macro_planner import MacroTreePolicy

spec=importlib.util.spec_from_file_location('belief_experiment_run',Path(__file__).with_name('run.py'))
experiment=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=experiment
spec.loader.exec_module(experiment)
experiment.BeliefTreePolicy=MacroTreePolicy

if __name__=='__main__':
    experiment.main()
