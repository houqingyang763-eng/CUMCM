"""从已审计analysis.json生成F3改配对图，无手工录入数值。"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

FONT = FontProperties(fname='C:/Windows/Fonts/msyh.ttc')


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('run', type=Path); args = parser.parse_args()
    run = args.run.resolve(); data = json.loads((run/'analysis.json').read_text(encoding='utf-8'))
    assert data['groups']['all24']['all_clear']
    fig = plt.figure(figsize=(15, 11), facecolor='white')
    ax = plt.subplot2grid((2, 2), (0, 0), colspan=2)
    pairs = data['pairs']; x = list(range(24)); savings = [p['saving']['total_s']/60 for p in pairs]
    colors = ['#4b8a74' if v >= 0 else '#bd655e' for v in savings]
    bars = ax.bar(x, savings, color=colors, width=.72)
    for bar, p in zip(bars, pairs):
        if p['reused']:
            bar.set_hatch('//'); bar.set_edgecolor('#2c3640')
    ax.axhline(0, color='#23313f', linewidth=.8)
    ax.set_xticks(x); ax.set_xticklabels([str(100+i) for i in x], fontsize=9)
    ax.set_ylabel('F3 − F3改（分钟）\n正值表示F3改更快', fontproperties=FONT, fontsize=11)
    ax.set_xlabel('案例种子后三位（均以320开头）；斜线为原8例，实色为新增16例', fontproperties=FONT, fontsize=11)
    ax.set_title('24局逐例比较：每一局都保留', fontproperties=FONT, fontsize=14, pad=22)
    for at in (5.5, 11.5, 17.5):
        ax.axvline(at, color='#c4cbd2', linestyle=':', linewidth=1)
    for at, label in zip((2.5, 8.5, 14.5, 20.5), ('均匀', '边缘', '聚集', '直线')):
        ax.text(at, 1.02, label, transform=ax.get_xaxis_transform(), ha='center', fontproperties=FONT, fontsize=11)
    ax.grid(axis='y', alpha=.18); ax.set_axisbelow(True)
    groups = ('all24', 'new16', 'reused8'); labels = ('全部24例', '新增16例', '原开发8例')
    for column, key, scale, title, unit in ((0, 'total_s', 60, '单局平均节省', '分钟'),
                                           (1, 'per_source_s', 1, '每源平均节省', '秒/源')):
        bx = plt.subplot2grid((2, 2), (1, column))
        for index, group in enumerate(groups):
            s = data['groups'][group]; mean = s['mean_saving'][key]/scale
            lo, hi = [v/scale for v in s['bootstrap_ci95_s'][key]]
            bx.plot([lo, hi], [2-index, 2-index], color='#286f90', linewidth=2)
            bx.scatter([mean], [2-index], s=70, color='#286f90', zorder=3)
            bx.text(mean, 2-index+.13, '{:.2f} [{:.2f}, {:.2f}]'.format(mean, lo, hi),
                    ha='center', fontsize=10, color='#23313f')
        bx.axvline(0, color='#bd655e', linestyle='--', linewidth=1)
        bx.set_yticks([2, 1, 0]); bx.set_yticklabels(labels, fontproperties=FONT, fontsize=11)
        bx.set_ylim(-.5, 2.5); bx.set_title(title, fontproperties=FONT, fontsize=14)
        bx.set_xlabel('F3 − F3改（{}）；线段为95%区间'.format(unit), fontproperties=FONT, fontsize=11)
        bx.grid(axis='x', alpha=.2); bx.margins(x=.2)
    fig.suptitle('F3改 vs F3 · 原普通24例 · 两者全部清除', fontproperties=FONT, fontsize=18, y=.98)
    fig.text(.5, .024, '同案配对、按布局分层的bootstrap，20000次。24例含开发样本；本图不代表官方隐藏测试。',
             ha='center', fontproperties=FONT, fontsize=10, color='#556575')
    fig.subplots_adjust(left=.09, right=.97, top=.89, bottom=.09, hspace=.43, wspace=.28)
    path = run/'comparison.png'; fig.savefig(str(path), dpi=160); plt.close(fig)
    receipt = dict(figure='comparison.png', plot_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   analysis_sha256=hashlib.sha256((run/'analysis.json').read_bytes()).hexdigest(),
                   figure_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (run/'figure_provenance.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(str(path))


if __name__ == '__main__':
    main()
