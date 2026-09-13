"""从已验证的批次统计自动生成完整对照表，失败不按成功子集汇总。"""
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent


def main():
    lines=['# 增量改动的配对实验明细','', '由 `report_results.py` 从各批次的 `analysis.json`、`summary.json` 生成；单位为分钟。负节省表示变慢。', '']
    for name in ('development_corrected','confirm','stress','random_audit','micro_confirm'):
        folder=HERE/'runs'/name
        if not (folder/'analysis.json').exists():continue
        analysis=json.loads((folder/'analysis.json').read_text())
        summary=json.loads((folder/'summary.json').read_text())
        lines += [f'## {name}：{summary["cases"]}例','',f'独立重放{analysis["independently_replayed_actions"]}条动作；失败记录{len(analysis["failures"])}条。','',
                  '| 版本 | 平均总时 | 平均每源 | 相对原版节省 | 配对95%区间 | 胜/负/平 | 最慢案例 |',
                  '|---|---:|---:|---:|---|---|---:|']
        for mode in summary['modes']:
            stats=summary['summary'][mode]
            comp=analysis['comparisons'].get(mode,{})
            if not stats['all_clear']:
                lines.append(f'| {mode} | 未全清，不汇总成功子集 | — | — | — | — | — |');continue
            ci=comp.get('ci95_min') if name in ('confirm','micro_confirm') else None
            interval=f'[{ci[0]:.3f}, {ci[1]:.3f}]' if ci else '—'
            saving=f'{comp["saving_min"]:.3f}' if 'saving_min' in comp else '—'
            wins=f'{comp["wins"]}/{comp["losses"]}/{comp["ties"]}' if 'wins' in comp else '—'
            lines.append(f'| {mode} | {stats["mean_min"]:.3f} | {stats["per_source_min"]:.3f} | {saving} | {interval} | {wins} | {stats["worst_min"]:.3f} |')
        lines += ['', '| 版本 | 移动节省 | 检测节省 | 切频节省 | 失败清除节省 | 平均失败清除次数 |','|---|---:|---:|---:|---:|---:|']
        for mode,comp in analysis['comparisons'].items():
            if not comp['all_clear']:continue
            costs=comp['cost_savings_min']
            lines.append(f'| {mode} | {costs["move_s"]:.3f} | {costs["measure_s"]:.3f} | {costs["switch_s"]:.3f} | {costs["fail_clear_s"]:.3f} | {comp["mean_fail_clears"]:.2f} |')
        lines += ['', '各版本最严重的三个退步案例：','']
        for mode,comp in analysis['comparisons'].items():
            if mode=='baseline' or not comp.get('all_clear'):continue
            worse=comp['worse_cases'][:3]
            lines.append(f'- {mode}：'+('；'.join(f'{r["case"]}多花{r["extra_min"]:.3f}分钟' for r in worse) if worse else '未出现退步')+'。')
        lines += ['', '按空间布局的平均节省：','']
        for mode,values in analysis['by_layout'].items():
            if mode!='baseline':lines.append(f'- {mode}：'+'；'.join(f'{k} {v:.3f}' for k,v in values.items())+'。')
        lines += ['', f'数据：`runs/{name}/paired.csv`；完整失败、候选与动作在对应案例目录。','']
    lines += ['## 解释边界','', '只对独立确认批次展示区间。开发批次用于诊断，固定构造的压力集及单个随机场景不展示总体不确定性区间。确认区间采用按布局分层的配对bootstrap，只反映这些自建案例的抽样变化。不同布局和误差场均为团队工作假设，不能外推为官方隐藏测试成绩。', '']
    (HERE/'BENCHMARK.md').write_text('\n'.join(lines),encoding='utf-8')


if __name__=='__main__':main()
