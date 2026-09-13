"""一次已核验UI的问题3演练；只使用公开HTTP接口。"""
import argparse
from dataclasses import dataclass, asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from two_stage import ROOT, CONFIGS, TwoStageConfig, TwoStagePolicy
sys.path.insert(0,str(ROOT/'experiments/b_overnight/practice'))
from adapter import PracticeClient, run_session, dump
from evidence import load_verified_practice_ui
from state import InformationState


@dataclass(frozen=True)
class HTTPConfig(TwoStageConfig):
    domain_radius_m: float = 5000.
    def to_dict(self):return asdict(self)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--ui-receipt',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    robot=os.environ.get('CUMCM_ROBOT_ID')
    if not robot:raise RuntimeError('缺少已登录队号环境变量')
    files=[Path(__file__),ROOT/'experiments/b_benchmark_scale/two_stage.py',
           ROOT/'experiments/b_overnight/task_cost.py',ROOT/'experiments/b_oracle_q3/oracle.py',
           ROOT/'experiments/b_env_probe/client.py']
    files += list((ROOT/'experiments/b_adaptive_q3').glob('*.py'))
    files += [ROOT/'experiments/b_overnight/practice'/n for n in ('adapter.py','evidence.py')]
    bundle={str(f.relative_to(ROOT)):f.read_bytes() for f in files}
    authorization=load_verified_practice_ui(args.ui_receipt,3,2026)
    policy=TwoStagePolicy(HTTPConfig(**asdict(CONFIGS['scan7_r60'])))
    state=InformationState()
    client=PracticeClient(robot,port=2026,timeout=5,retries=2)
    # 历史guard已解除；这里明确不调用guard入口或配额检查。
    result=run_session(client,policy,state,3,authorization,args.output,guard=lambda:None)
    dump(args.output/'plans.json',policy.metadata())
    hashes={}
    for rel,data in bundle.items():
        target=args.output/'source'/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
        hashes[rel]=hashlib.sha256(data).hexdigest()
    unchanged=all((ROOT/rel).read_bytes()==data for rel,data in bundle.items())
    exe=ROOT/'inputs/official/CUMCM2026B/Jammers-simulator-full-win64/Jammers-simulator-full/jammers-simulator-full.exe'
    dump(args.output/'manifest.json',dict(problem=3,mode='official_practice',strategy='scan7_r60',
        config=policy.config.to_dict(),initial_position=[0,0],initial_channel=1,
        public_endpoint='http://127.0.0.1:2026',started_ui=authorization.evidence_record,
        source_sha256=hashes,sources_unchanged=unchanged,
        official_executable_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
        source_truth_available=False,noise_seed_available=False,
        note='只保存公开反馈；不读取官方隐藏案例或解密行为日志。'))
    print(json.dumps(result,ensure_ascii=False))
    if not unchanged or result['error_type'] or not result['complete_by_evidence']:raise SystemExit(1)


if __name__=='__main__':main()
