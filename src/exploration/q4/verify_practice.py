"""将实际官方终局观察与脱敏HTTP清除记录交叉核对，另生成核验结果。"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def verify(folder, ui_path):
    summary = json.loads((folder/'summary.json').read_text(encoding='utf-8-sig'))
    ui = json.loads(ui_path.read_text(encoding='utf-8-sig'))
    evidence = json.loads((folder/'ui_evidence.json').read_text(encoding='utf-8-sig'))
    rows = [json.loads(line) for line in (folder/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    channels = {r['action']['channel'] for r in rows if r['response'].get('clear_result') == 'success'}
    if ui['problem'] != 4 or ui['mode'] != 'practice' or not ui['normal_exit'] or not ui['log_saved']:
        raise ValueError('官方终局尚未正常结束并保存日志')
    if ui['case_code'] != evidence['case_code']:
        raise ValueError('官方终局与进入前案例不一致')
    count = ui['source_count']
    if type(count) is not int or not 10 <= count <= 16 or ui['omni_count']+ui['directional_count'] != count:
        raise ValueError('官方源数记录不完整')
    if (len(channels) != count or summary['cleared_count'] != count
            or not summary['complete_by_public_evidence'] or summary['source_changed']):
        raise ValueError('终局源数、成功频道或程序完整性未通过核验')
    difference = summary['virtual_time_s']-summary['independently_accounted_s']
    if abs(difference) > .01:
        raise ValueError('完整计费与官方累计数不一致')
    result = dict(summary, official_true_count=count, official_all_cleared=True,
        ui_result_check_pending=False, case_code=ui['case_code'], omni_count=ui['omni_count'],
        directional_count=ui['directional_count'], unique_successful_channels=sorted(channels),
        accounting_difference_s=difference, ui_result_source=ui_path.relative_to(folder).as_posix(),
        verified_at_utc=datetime.now(timezone.utc).isoformat(),
        conclusion_scope='单局官方演练全清与接口计费核验，不是正式成绩，也不支持不同案例间性能比较')
    target = folder/'verified_summary.json'
    if target.exists():
        raise ValueError('保留已有核验结果；不得覆盖')
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--ui-result', type=Path, required=True)
    args = parser.parse_args()
    value = verify(args.folder, args.ui_result)
    print(json.dumps({k:value[k] for k in ('official_all_cleared','cleared_count','virtual_time_s',
          'average_localization_clear_s','wall_time_s','accounting_difference_s')}, ensure_ascii=False))
