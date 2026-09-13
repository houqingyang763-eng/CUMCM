"""完整时间账本、逐频道测向次数及12/16配对；不挑选成功案例。"""
import json
import statistics
from pathlib import Path
from policy import a

HERE=Path(__file__).resolve().parent


def episode(folder):
    r=json.loads((folder/'result.json').read_text(encoding='utf-8'))
    actions=[json.loads(x) for x in (folder/'actions.jsonl').read_text(encoding='utf-8').splitlines()]
    state=a.CoverageInformationState();last_clear=0.;full_seen=None
    for row in actions:
        state.update(row,row['response'])
        if row['response'].get('clear_result')=='success':last_clear=state.virtual_time_s
        if len(state.ever_seen)==16 and full_seen is None:full_seen=state.virtual_time_s
    out={k:r.get(k) for k in ('success','total_s','move_s','measure_s','switch_s','success_clear_s','fail_clear_s','actions','measure_count','fail_clears','source_count','failreason')}
    out.update(last_actual_clear_s=last_clear,after_last_clear_s=r['total_s']-last_clear,
               found_16_s=full_seen,complete=state.complete,
               bearing_counts={j:sum(x['channel']==j and x['response'].get('measure_result')=='direction' for x in actions) for j in (9,10)})
    out['minutes']=r['total_s']/60
    return out


def main():
    original=HERE.parent/'refinement/runs/demo_f3_20260912/uniform_hashed_186539142/f3'
    diagnostic={'f3':episode(original)}
    for m,stage in [('s1','diagnostic'),('s2','diagnostic'),('s3','diagnostic'),('s4','fixed_demo')]:
        diagnostic[m]=episode(HERE/'runs'/stage/'uniform_hashed_186539142'/m)
    fresh={}
    for c in json.loads((HERE/'fresh_cases.json').read_text(encoding='utf-8')):
        fresh[c['name']]={m:episode(HERE/'runs'/('fixed' if m=='s4' else 'fresh_loaded')/c['name']/m) for m in ('f3','s1','s3','s4')}
    all_clear=all(r['success'] and r['complete'] for case in fresh.values() for r in case.values())
    stats={}
    if all_clear:
        for m in ('f3','s1','s3','s4'):
            rows=[x[m] for x in fresh.values()]
            stats[m]={'mean_min':statistics.mean(r['minutes'] for r in rows),
                      'saving_vs_f3_min':statistics.mean((c['f3']['total_s']-c[m]['total_s'])/60 for c in fresh.values()),
                      'wins_vs_f3':sum(c[m]['total_s']<c['f3']['total_s']-1e-6 for c in fresh.values()),
                      'mean_after_last_clear_min':statistics.mean(r['after_last_clear_s']/60 for r in rows)}
    record={'diagnostic':diagnostic,'fresh':fresh,'fresh_all_clear':all_clear,'fresh_summary':stats,
            'implementation_failure_before_fix':episode(HERE/'runs/fresh_loaded/uniform_hashed_20260925_n12/s4'),
            'scope':'两组16/12源配对，共4个新场景；S4在出现实现错误后修复并全批复跑，故不算未触碰的最终确认集。'}
    a.base.dump(HERE/'RESULTS.json',record)
    lines=['# 本轮配对结果','',record['scope'],'','## 原随机案例','',
           '|版本|分钟|移动分钟|扫描次数|失败清除|C9测向|C10测向|', '|---|---:|---:|---:|---:|---:|---:|']
    for m,r in diagnostic.items():lines.append(f"|{m}|{r['minutes']:.3f}|{r['move_s']/60:.3f}|{r['measure_count']}|{r['fail_clears']}|{r['bearing_counts'][9]}|{r['bearing_counts'][10]}|")
    lines.extend(['','## 新场景：每格为整局分钟／最后清除后查漏分钟','','|场景|F3|S1|S3|S4|','|---|---:|---:|---:|---:|'])
    for name,case in fresh.items():lines.append('|'+name+'|'+'|'.join(f"{case[m]['minutes']:.3f} / {case[m]['after_last_clear_s']/60:.3f}" for m in ('f3','s1','s3','s4'))+'|')
    lines.extend(['','## 新场景均值','','|版本|平均分钟|相对F3节省分钟|胜例数/4|','|---|---:|---:|---:|'])
    for m,s in stats.items():lines.append(f"|{m}|{s['mean_min']:.3f}|{s['saving_vs_f3_min']:.3f}|{s['wins_vs_f3']}|")
    (HERE/'RESULTS.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(stats,ensure_ascii=False))


if __name__=='__main__':main()
