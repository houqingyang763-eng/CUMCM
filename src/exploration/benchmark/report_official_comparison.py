"""将一次官方演练与受限重放对照整理为可复核记录，不解密隐藏案例。"""
import csv
import hashlib
import json
import shutil
from pathlib import Path

BASE=Path(__file__).resolve().parent
PRIVATE=BASE/'local_official'


def load(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def main():
    official=PRIVATE/'official_77UA';replay=PRIVATE/'replay_77UA'
    out=BASE/'runs/official_practice_77UA'
    out.mkdir(parents=True,exist_ok=False)
    summary=load(official/'summary.json');manifest=load(official/'manifest.json')
    comparison=load(replay/'comparison.json');plans=load(official/'plans.json')
    ui=load(PRIVATE/'after_ui.json')
    assert '问题3 演练 测试' in ui and '测试已结束' in ui and '77UA-6YR4-HZ3S-APKM' in ui
    i=ui.index('共');count=int(ui[i+1]);omni=int(ui[i+3]);directional=int(ui[i+5])
    assert count==omni+directional==summary['cleared_count']==11 and directional==0
    rows=[json.loads(s) for s in (official/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    success=[r for r in rows if r['response'].get('clear_result')=='success']
    assert len({r['action']['channel'] for r in success})==count
    for name in ('actions.jsonl','config.json','plans.json','enter.json','http_records.json','state_evidence.json'):
        shutil.copyfile(official/name,out/name)
    for name in ('comparison.json','actions_comparison.csv','local_plans.json'):
        shutil.copyfile(replay/name,out/name)
    log=next((PRIVATE/'exported_logs').glob('*77UA-6YR4-HZ3S-APKM.jlog'))
    verification=dict(mode='问题3演练测试',case_code='77UA-6YR4-HZ3S-APKM',simulator_version='1.1',
        official_source_count=count,omnidirectional_sources=omni,directional_sources=directional,
        success_clear_channels=sorted(r['action']['channel'] for r in success),all_cleared=True,
        started_ui=manifest['started_ui'],before_ui_sha256=sha(PRIVATE/'before_ui.json'),
        after_ui_sha256=sha(PRIVATE/'after_ui.json'),after_screenshot_sha256=sha(PRIVATE/'after.png'),
        exported_encrypted_log_sha256=sha(log),exported_encrypted_log_bytes=log.stat().st_size,
        official_executable_sha256=manifest['official_executable_sha256'],
        algorithm_sources_sha256=manifest['source_sha256'],
        actual_source_coordinates_available=False,actual_reception_radii_available=False,
        actual_noise_field_available=False,hidden_environment_reconstruction_performed=False,
        official_summary=summary)
    dump(out/'verification.json',verification)
    scan=plans['phase_change']['time_s'];total=summary['virtual_time_s']
    measures=[r for r in rows if r['action']['kind']=='measure']
    scan_n=sum(r['action']['phase']=='scan' for r in rows)
    conditions=dict(problem=3,mode='practice',case_code=verification['case_code'],config=load(official/'config.json'),
        initial_position=[0.,0.],initial_channel=1,source_count=count,
        fixed_scan_points=plans['fixed_points'],scan_action_count=scan_n,
        later_measurements=len(measures)-scan_n,cleared_count=count,failed_clears=len(rows)-len(measures)-count,
        scan_s=scan,service_s=total-scan,total_s=total,per_source_s=total/count,
        requests=summary['requests'],actions=len(rows),retries=summary['retry_count'],
        client_wall_s=summary['wall_time_s'],remaining_time_at_enter=load(official/'enter.json'),
        field_status={'robot_positions':'所有117动作的精确请求坐标已记录',
            'source_positions':'未知；成功清除坐标不是源坐标，只证明源在20米内',
            'source_reception_radius':'未知','measurement_error_field':'未知',
            'official_measurements_and_clear_results':'逐动作完整记录公开字段'},
        validity='本地运行是官方反馈驱动的算法重放，独立重新计算费用；不是LocalEnvironment独立生成反馈的同场景测试')
    dump(out/'conditions.json',conditions)
    lines=['# 问题3官方演练与本地重放对照','',
        '**完成了一次真实官方演练及本地算法重放，未完成同一隐藏环境的独立仿真对比。** 官方不公开源的真实坐标、接收半径和误差场，不能完整重建这一场景。','',
        f'案例 `{verification["case_code"]}`，模拟器v1.1，问题3演练；官方结束界面显示全向源{count}个，成功清除互异频道{count}个，确认全清。没有启动正式测试。',
        f'官方虚拟总时间 **{total:.6f}秒（{total/60:.2f}分钟）**，平均每源{total/count:.2f}秒。',
        f'第一阶段{scan/60:.2f}分钟，后续{(total-scan)/60:.2f}分钟。{len(rows)}个动作、{summary["requests"]}次请求、0次重试；失败清除{conditions["failed_clears"]}次。客户端会话墙钟{summary["wall_time_s"]:.3f}秒，不是虚拟任务用时。','',
        '## 对比究竟检验了什么','',
        '| 对比项 | 结果 | 解释 |','|---|---|---|',
        '| 本地算法重新选择的动作 | 117/117一致 | 相同官方反馈输入；动作种类、频道和位置逐步一致 |',
        f'| 位置差异 | {comparison["max_position_difference_m"]}米 | 是机器狗选点，非源真实坐标 |',
        f'| 每动作计费最大差异 | {comparison["max_step_cost_difference_s"]:.12g}秒 | 独立按距离/5、检测、切频、成功/失败规则计算 |',
        f'| 累计计费最大差异 | {comparison["max_cumulative_cost_difference_s"]:.12g}秒 | 约{comparison["max_cumulative_cost_difference_s"]*1e6:.2f}微秒，小于预先采用的1毫秒容差 |',
        f'| 最终总时间 | 官方{total:.9f}秒；本地账本{comparison["local_ledger_total_s"]:.9f}秒 | 存在微小数值差异，并非逐位完全相同 |',
        '| Python自建环境能否独立返回相同测向与清除结果 | 未验证 | 官方隐藏条件未公开；重放使用官方反馈，不能拿它证明环境等价 |','',
        '这些差异量级与浮点计算/输出精度相容，但未通过检查官方内部实现确定具体来源。成功只能支持这一次官方演练的执行与费用核对，不能证明两环境几乎一致。','',
        '## 已记录条件与位置','',
        '配置：7个预定义扫描点，60米停止继续扫描阈值、30米小区域中心试清阈值、单目标24动作后备门槛。起点(0,0)、初始频道1；第二阶段从实际扫描结束位置规划当前估计中心的开放路径。','',
        '| 固定测点顺序 | x/米 | y/米 |','|---|---:|---:|']
    for i,p in enumerate(plans['fixed_points'],1):lines.append(f'| {i} | {p[0]:.9f} | {p[1]:.9f} |')
    lines+=['','各次测量/清除的完整位置、频道、官方返回角度、成败、时间及与本地差异，见 [117动作对照表](actions_comparison.csv)。JSON记录保留完整数值精度，表格展示的固定点坐标只作阅读。',
        '路径、阶段结束时的估计区域和各轮访问顺序见 [plans.json](plans.json)。成功清除点只说明真实源在其20米范围内，不作为真实源坐标输入自建环境。',
        '完整可获取条件见 [conditions.json](conditions.json)，核验与源码散列见 [verification.json](verification.json)。','',
        '## 仍缺的同环境对照条件','',
        '官方演练界面只公开源总数/类型数量，没有提供全部源精确位置、接收半径或误差场。导出的.jlog为加密行为日志，已原名保存并计算散列，未尝试解密或读取隐藏案例。',
        '未用清除位置冒充源位置，也未拟合一套误差后声称复刻成功。因此不能满足“把官方这一局隐藏场景完整搬到LocalEnvironment独立再跑一遍”的部分要求；需要官方提供可导出的案例/误差条件，或可导入同一自定义案例的公开接口才能真正完成。','',
        '## 记录与复现','',
        '实际官方调用使用 official_probe.py，经当次问题3演练UI核验收据后只进入一次；退出正常。源代码、官方UI原图及原名加密日志保存在本实验local_official私有目录，避免账号截图进入可提交材料。',
        'replay_official.py 重放算法并独立复算费用，report_official_comparison.py 生成本报告。重放输出目录必须不存在；重放无网络请求，不再占用演练或正式次数。',
        'AI执行与核验，不替代团队人工审阅。','']
    (out/'RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(conditions,ensure_ascii=False))


if __name__=='__main__':main()
