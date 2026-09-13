"""从已有自建实验日志绘制讨论图；不调用策略、模拟器或重新生成反馈。"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle
from matplotlib.font_manager import FontProperties
from matplotlib.text import Text
import os
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parent
BLUE = '#247ba0'
ORANGE = '#d76a32'
INK = '#25344a'
GREY = '#b1bac5'
plt.rcParams.update({'font.sans-serif': ['Microsoft YaHei'],
                     'axes.unicode_minus': False, 'font.size': 12,
                     'text.color': INK, 'axes.labelcolor': INK,
                     'axes.titlesize': 14, 'figure.facecolor': 'white',
                     'savefig.facecolor': 'white'})


def read(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8-sig'))


def load_run(rel):
    folder = ROOT / rel
    actions = [json.loads(s) for s in (folder / 'actions.jsonl').read_text(
        encoding='utf-8-sig').splitlines() if s.strip()]
    result = read(rel + '/result.json')
    assert result['success']
    assert abs(sum(sum(a['independent_costs'].values()) for a in actions)
               - result['total_s']) < 1e-6
    assert sum(a['kind'] == 'measure' for a in actions) == result['measure_count']
    return actions, result


def path_xy(actions, start=(0, 0)):
    points = [list(start)]
    for a in actions:
        if a['position'] != points[-1]:
            points.append(a['position'])
    return np.array(points) / 1000.


def map_base(ax, sources):
    ax.add_patch(Circle((0, 0), 1.8, fill=False, ec='#8d99a9', lw=1.2))
    positions = np.array([s['position'] for s in sources]) / 1000.
    ax.scatter(positions[:, 0], positions[:, 1], marker='x', c='#687689', s=38,
               zorder=4)
    ax.scatter([0], [0], c=INK, s=110, marker='*', zorder=7)
    ax.set_xlim(-1.95, 1.95)
    ax.set_ylim(-1.95, 1.95)
    ax.set_aspect('equal')
    ax.set_xlabel('东西位置（千米）')
    ax.set_ylabel('南北位置（千米）')
    ax.set_xticks([-1.5, 0, 1.5])
    ax.set_yticks([-1.5, 0, 1.5])
    ax.grid(alpha=.15)
    for s in ax.spines.values():
        s.set_visible(False)


def route(ax, actions, color, start=(0, 0), lw=2, alpha=1):
    xy = path_xy(actions, start)
    ax.plot(xy[:, 0], xy[:, 1], color=color, lw=lw, alpha=alpha, zorder=2)
    return xy


def save(fig, name):
    # 使用本机字体文件，避开旧 matplotlib 字体缓存缺少中文字体的问题。
    fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for label in fig.findobj(Text):
        font = fonts / ('msyhbd.ttc' if label.get_weight() == 'bold' else 'msyh.ttc')
        label.set_fontproperties(FontProperties(fname=str(font), size=label.get_fontsize()))
    fig.savefig(str(OUT / name), dpi=145)
    plt.close(fig)


f3_dir = 'experiments/b_q3/refinement/runs/demo_f3_20260912/uniform_hashed_186539142/f3'
s4_dir = 'experiments/b_q3/clearability/runs/fixed_demo/uniform_hashed_186539142/s4'
f3a, f3r = load_run(f3_dir)
s4a, s4r = load_run(s4_dir)
case = read('experiments/b_q3/clearability/runs/fixed_demo/cases.json')[0]
assert case['name'] == f3r['case'] == s4r['case']
assert [a['position'] for a in f3a[:40]] == [a['position'] for a in s4a[:40]]

fig = plt.figure(figsize=(12.6, 8.4))
fig.text(.05, .955, '少测了 32 次，整局却慢了 7.4 分钟', fontsize=22, weight='bold')
fig.text(.05, .916, '同一场景、同样 16 个源、相同开局；两种方法都全部清除。', fontsize=12)
for i, (label, actions, result) in enumerate([('F3', f3a, f3r), ('S4', s4a, s4r)]):
    ax = fig.add_axes([.07 + i * .48, .31, .39, .51])
    map_base(ax, case['sources'])
    route(ax, actions, BLUE if i == 0 else GREY, lw=2)
    ax.set_title('{}：检测 {} 次，总用时 {:.1f} 分钟\n全程走了 {:.2f} 千米'.format(
        label, result['measure_count'], result['total_s']/60., result['move_s']*5/1000.), pad=12)
    if i == 1:
        selected = [a for a in actions if a['step'] >= 108]
        route(ax, selected, ORANGE, start=selected[0]['before']['position'], lw=3.2)
        a = next(a for a in actions if a['step'] == 110)
        p, q = np.array(a['before']['position'])/1000., np.array(a['position'])/1000.
        ax.annotate('', xy=q, xytext=p, arrowprops={'arrowstyle': '->', 'color': ORANGE, 'lw': 3})
        ax.annotate('末尾横穿场地\n这一段：2.75 千米 / 9.2 分钟', xy=(p+q)/2,
                    xytext=(-1.65, .75), fontsize=11, color=ORANGE,
                    arrowprops={'arrowstyle': '-', 'color': ORANGE},
                    bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': .95})
        ax.text(p[0]-.15, p[1]-.2, 'C2', fontsize=11)
        ax.text(q[0]-.1, q[1]+.15, 'C7', fontsize=11)
ax = fig.add_axes([.11, .13, .8, .10])
for y, r, label in [(1, f3r, 'F3'), (0, s4r, 'S4')]:
    parts = [r['move_s']/60., (r['measure_s']+r['switch_s'])/60.,
             (r['success_clear_s']+r['fail_clear_s'])/60.]
    left = 0
    for value, color in zip(parts, [BLUE, '#e7b56f', GREY]):
        ax.barh(y, value, left=left, height=.55, color=color)
        if value > 3:
            ax.text(left+value/2, y, '{:.1f}'.format(value), ha='center', va='center', fontsize=11,
                    color='white' if color == BLUE else INK)
        left += value
ax.set_xlim(0, 65)
ax.set_yticks([0, 1])
ax.set_yticklabels(['S4', 'F3'])
ax.set_xticks([])
for s in ax.spines.values():
    s.set_visible(False)
fig.text(.11, .098, '时间构成（分钟）：蓝色＝移动；浅橙＝检测与切频；灰色＝清除操作', fontsize=11)
fig.text(.05, .04, '来源：已有自建实验 186539142。× 为事后可见的真实源；★ 为起点。\n橙线展示实际绕行，不代表能把这一段全部归因于删掉测量。', fontsize=10, color='#677489')
save(fig, '01_fewer_measurements_longer_route.png')

demo = 'experiments/b_q3/adaptive_second/demonstration'
review = read(demo + '/review_findings.json')
replay = read(demo + '/replay.json')
alternatives = review['step75_alternatives']
p = np.array(next(a for a in replay['actions'] if a['step'] == 74)['position']) / 1000.
src = {s['channel']: np.array(s['position'])/1000. for s in replay['case']['sources']}
fig = plt.figure(figsize=(12.6, 7.2))
fig.text(.05, .955, '同样远的两个测点，顺便办成的事可以很不同', fontsize=21, weight='bold')
fig.text(.05, .905, '已有轨迹的第 75 步：左边实际执行；右边是从同一状态出发的局部替代试算。', fontsize=12)
for i, (key, color, title) in enumerate([('actual', BLUE, '原测点：实际走过'),
                                        ('reflected', ORANGE, '内侧测点：已有局部试算')]):
    ax = fig.add_axes([.07+i*.48, .30, .39, .53])
    q = np.array(alternatives[key]['q'])/1000.
    ax.set_title(title, pad=10)
    ax.scatter([p[0]], [p[1]], c=INK, marker='*', s=160, zorder=4)
    ax.text(p[0]-.35, p[1]+.12, '同一出发点', fontsize=11)
    ax.annotate('', xy=q, xytext=p, arrowprops={'arrowstyle': '->', 'color': color, 'lw': 3,
                                             'linestyle': '-' if i == 0 else '--'})
    ax.scatter([q[0]], [q[1]], s=100, c=color, zorder=4)
    ax.text(q[0]+.09, q[1]+.02, '测点', color=color, fontsize=11)
    ax.text(.3, -.98, '走路约 129 秒', fontsize=11, color=color,
            bbox={'facecolor': 'white', 'edgecolor': 'none', 'alpha': .9})
    for ch in [4, 10, 20]:
        pos = src[ch]
        ax.scatter([pos[0]], [pos[1]], marker='x', s=70, c='#627386', zorder=3)
        ax.text(pos[0]+.08, pos[1]+.02, 'C{}{}'.format(ch, '（本次主目标）' if ch == 20 else ''), fontsize=11)
    ax.set_xlim(-1.1, 1.05)
    ax.set_ylim(-1.82, -.25)
    ax.set_aspect('equal')
    ax.set_xlabel('东西位置（千米）')
    ax.set_ylabel('南北位置（千米）')
    ax.set_xticks([-1, 0, 1])
    ax.set_yticks([-1.5, -1, -.5])
    ax.grid(alpha=.16)
    for sp in ax.spines.values():
        sp.set_visible(False)
    body = ('新发现 2 个源\nC4：仍不能保证一次清除\n主目标 C20：定位范围略小' if i == 0 else
            '新发现 3 个源（多发现 C10）\nC4：已能保证一次清除\n主目标 C20：定位反而略差')
    fig.text(.08+i*.48, .19, body, fontsize=12, linespacing=1.6, va='center')
fig.text(.05, .047, '来源：案例 269525288 的原始轨迹与已保存的替代测点审查。仅标出讨论涉及的 3 个源。\n× 为事后真值。右侧这批操作多花 6 秒，尚未验证整局是否更快。', fontsize=10, color='#677489')
save(fig, '02_one_stop_several_benefits.png')

m3_dir = 'experiments/b_q3/belief_tree/runs/dev_macro_loaded/line_biased_330020/m3'
m3a, m3r = load_run(m3_dir)
m3case = next(c for c in read('experiments/b_q3/belief_tree/runs/dev_macro_loaded/cases.json')
              if c['name'] == m3r['case'])
last = max(i for i, a in enumerate(m3a) if a['independent_costs']['success_clear_s'] > 0)
clear_time = m3a[last]['response']['virtual_time_s']/60.
tail_time = m3r['total_s']/60. - clear_time
assert m3a[last]['after']['counts']['cleared'] == len(m3case['sources'])
assert all(a['kind'] == 'measure' for a in m3a[last+1:])
fig = plt.figure(figsize=(12.6, 8))
fig.text(.05, .955, '源已经清完，还花了 25.6 分钟确认没有遗漏', fontsize=21, weight='bold')
fig.text(.05, .909, '机器人当时不知道实际源数，仍需排除未确认的频道。橙线是最后一次成功清除后的路线。', fontsize=12)
for i in range(2):
    ax = fig.add_axes([.07+i*.48, .28, .39, .52])
    map_base(ax, m3case['sources'])
    route(ax, m3a[:last+1], BLUE if i == 0 else '#d8dfe7', lw=2)
    endpoint = np.array(m3a[last]['position'])/1000.
    ax.scatter([endpoint[0]], [endpoint[1]], marker='D', s=70, c=BLUE, zorder=6)
    if i == 0:
        ax.set_title('前 33.7 分钟\n实际存在的 {} 个源已全部清除'.format(len(m3case['sources'])), pad=12)
    else:
        ax.set_title('随后又用 25.6 分钟\n查漏结束，整局才完成', pad=12)
        xy = route(ax, m3a[last+1:], ORANGE, start=m3a[last]['position'], lw=3)
        ax.scatter(xy[1:, 0], xy[1:, 1], c=ORANGE, s=32, zorder=5)
        ax.text(-1.7, 1.52, '浅灰＝此前走过的路', fontsize=10, color='#798597')
ax = fig.add_axes([.11, .13, .80, .07])
ax.barh(0, clear_time, color=BLUE, height=.6)
ax.barh(0, tail_time, left=clear_time, color=ORANGE, height=.6)
ax.text(clear_time/2, 0, '到最后一个源清除：33.7 分钟', color='white', va='center', ha='center', fontsize=11)
ax.text(clear_time+tail_time/2, 0, '后续查漏：25.6 分钟', color='white', va='center', ha='center', fontsize=11)
ax.set_xlim(0, m3r['total_s']/60.)
ax.axis('off')
fig.text(.05, .052, '来源：已有自建实验 M3 / line_biased_330020。× 为事后真值；★ 为起点；蓝色菱形为最后清除位置。\n这是个案，用于展示后续查漏成本；不能据此直接让机器人在 33.7 分钟时停止。', fontsize=10, color='#677489')
save(fig, '03_after_last_clear_patrol.png')

evidence = {
    'scope': 'Only plot existing self-built experiment logs; no policy or simulator execution.',
    'sources': [f3_dir, s4_dir, demo, m3_dir],
    'f3_s4': {'case': case['name'], 'f3_total_min': f3r['total_s']/60.,
              's4_total_min': s4r['total_s']/60.,
              'delta_total_min': (s4r['total_s']-f3r['total_s'])/60.,
              'measurement_counts': [f3r['measure_count'], s4r['measure_count']],
              'move_km': [f3r['move_s']*.005, s4r['move_s']*.005]},
    'local_alternatives': alternatives,
    'm3_tail': {'last_clear_step': m3a[last]['step'], 'source_count': len(m3case['sources']),
                'last_clear_min': clear_time, 'tail_min': tail_time,
                'total_min': m3r['total_s']/60.},
    'checks': ['Completed runs', 'Independent action costs match stored total',
               'Detection counts match logs', 'F3/S4 same case and initial positions',
               'M3 all true sources cleared before tail; tail contains measurements only']}
(OUT / 'figure_evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'f3_s4': evidence['f3_s4'], 'm3_tail': evidence['m3_tail']}, ensure_ascii=False, indent=2))
