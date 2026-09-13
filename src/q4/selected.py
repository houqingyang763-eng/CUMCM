"""唯一正式策略入口；配置只从相邻selected_config.json读取。"""
import json

import common
from candidate import CandidateConfig, CandidatePolicy

CONFIG_PATH = common.ROOT / "selected_config.json"


def selected_parameters():
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("policy") != "shared25":
        raise ValueError("正式策略配置标识无效")
    parameters = data["parameters"]
    CandidateConfig(**parameters)
    return parameters


class SelectedPolicy(CandidatePolicy):
    """算法与CandidatePolicy相同，只固定正式参数来源。"""
    def __init__(self):
        super().__init__(CandidateConfig(**selected_parameters()))
