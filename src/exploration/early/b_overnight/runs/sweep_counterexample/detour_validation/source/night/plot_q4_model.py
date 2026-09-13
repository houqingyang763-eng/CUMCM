"""Q4 方法图；兼容 Python 3.7 / matplotlib 2.2，读取冻结几何结果。"""
from __future__ import print_function
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
subprocess.check_call(['py', '-3.13', str(ROOT / 'astra_guard.py'), 'check'], cwd=str(PROJECT))
cache = ROOT / '.cache' / 'matplotlib_q4'
cache.mkdir(parents=True, exist_ok=True)
os.environ['MPLCONFIGDIR'] = str(cache)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.text import Text
from matplotlib.patches import Circle, Polygon, FancyArrowPatch, Rectangle

FONT = FontProperties(fname=str(Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'))
plt.rcParams.update({'font.family': 'sans-serif', 'font.sans-serif': [FONT.get_name()],
                     'axes.unicode_minus': False, 'font.size': 11, 'svg.fonttype': 'path',
                     'axes.edgecolor': '#7C8798', 'axes.labelcolor': '#334155',
                     'xtick.color': '#475569', 'ytick.color': '#475569'})
OUT = ROOT / 'figures' / 'q4_model'
OUT.mkdir(parents=True, exist_ok=True)
GEOMETRY = ROOT / 'runs' / 'q4_anchor_design' / 'symmetric25_geometry' / 'symmetric25_geometry.json'
JOINT = OUT / 'joint_example.json'
BLUE, TEAL, ORANGE, RED, INK = '#2563A6', '#087F8C', '#DA8A2B', '#BE3D3D', '#24364B'


def hull(points):
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def half(seq):
        result=[]
        for p in seq:
            while len(result)>1 and cross(result[-2], result[-1], p)<=0:
                result.pop()
            result.append(p)
        return result
    points=sorted(set(tuple(p) for p in points))
    return half(points)[:-1]+half(list(reversed(points)))[:-1]


def save(fig, name):
    # 老版matplotlib可能未把Windows的TTC注册进family列表，逐个Text指定字体文件。
    for label in fig.findobj(match=Text):
        prop=label.get_fontproperties().copy()
        prop.set_file(FONT.get_file())
        label.set_fontproperties(prop)
    fig.savefig(str(OUT / (name + '.png')), dpi=220, facecolor='white')
    fig.savefig(str(OUT / (name + '.svg')), facecolor='white')
    plt.close(fig)


def covering_figure(data):
    points=[tuple(p) for p in data['points']]
    assert len(points)==25 and len(data['triangulation'])==36
    fig=plt.figure(figsize=(11.6, 8.0))
    fig.text(.06,.945,'25 个参照点覆盖所有可能的源位置与发射方向',fontsize=18,color=INK,weight='bold')
    fig.text(.06,.905,'第四问可靠发现几何：内部三角格网 + 外正十二边形',fontsize=11,color='#596779')
    ax=fig.add_axes([.075,.13,.555,.72])
    ax.set_aspect('equal')
    ax.add_patch(Polygon(hull(points),closed=True,facecolor='#FFF4E2',edgecolor=ORANGE,lw=1.8,zorder=1))
    ax.add_patch(Circle((0,0),1800,facecolor='#EAF2FA',edgecolor=BLUE,linestyle='--',lw=1.8,zorder=2))
    edges=set()
    for tri in data['triangulation']:
        for i,j in ((tri[0],tri[1]),(tri[1],tri[2]),(tri[2],tri[0])):
            edges.add(tuple(sorted((i,j))))
    for i,j in edges:
        ax.plot([points[i][0],points[j][0]],[points[i][1],points[j][1]],color='#8597AB',lw=.75,zorder=3)
    groups=[([],INK),([],BLUE),([],TEAL),([],ORANGE)]
    for p in points:
        r=math.hypot(*p)
        index=0 if r<1 else 1 if r<1000 else 2 if r<1800 else 3
        groups[index][0].append(p)
    for group,color in groups:
        ax.scatter([p[0] for p in group],[p[1] for p in group],s=44,c=color,edgecolors='white',linewidths=.7,zorder=5)
    ax.add_patch(FancyArrowPatch((0,-90),(944,-90),arrowstyle='<->',mutation_scale=11,color=BLUE,lw=1.2,zorder=6))
    ax.text(470,-195,'a = 944 m',ha='center',color=BLUE,fontsize=10,
            bbox=dict(facecolor='white',edgecolor='none',alpha=.85,pad=2),zorder=7)
    e=(math.cos(math.radians(120)),math.sin(math.radians(120)))
    ax.add_patch(FancyArrowPatch((0,0),(1888*e[0],1888*e[1]),arrowstyle='<->',mutation_scale=11,color=ORANGE,lw=1.5,zorder=6))
    ax.text(-640,950,'2a = 1888 m',ha='center',rotation=-60,color='#AA621B',fontsize=10,
            bbox=dict(facecolor='white',edgecolor='none',alpha=.9,pad=2),zorder=7)
    ax.annotate('目标圆 R = 1800 m',xy=(1800/math.sqrt(2),-1800/math.sqrt(2)),
                xytext=(650,-1810),color=BLUE,fontsize=10,
                arrowprops=dict(arrowstyle='-',color=BLUE),zorder=8)
    ax.set_xlim(-2180,2180)
    ax.set_ylim(-2180,2180)
    ax.set_xlabel('x / m')
    ax.set_ylabel('y / m')
    ax.set_xticks([-1800,-900,0,900,1800])
    ax.set_yticks([-1800,-900,0,900,1800])
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    note=fig.add_axes([.675,.17,.29,.65])
    note.axis('off')
    note.text(0,.97,'几何保证',fontsize=15,color=INK,weight='bold')
    lines=[('24 个内部三角形 + 12 个外部三角形',.86),
           ('铺满外正十二边形。',.80),
           ('外边界内切半径',.66),
           ('1823.668 m > 1800 m',.59),
           ('三角形最大边长',.44),
           ('977.301 m < 1000 m',.37),
           ('每个可能位置都被近测点包围，',.22),
           ('任意发射半圆内至少有一个测点。',.16)]
    for text,y in lines:
        note.text(0,y,text,fontsize=11,color=INK)
    handles=[Line2D([0],[0],marker='o',color='none',markerfacecolor=c,markeredgecolor='white',markersize=7,label=t)
             for c,t in [(INK,'中心 1 点'),(BLUE,'半径 944 m：6 点'),(TEAL,'半径 √3a：6 点'),(ORANGE,'半径 1888 m：12 点')]]
    fig.legend(handles=handles,loc='lower center',bbox_to_anchor=(.51,.04),ncol=4,frameon=False,fontsize=10)
    fig.text(.06,.015,'25 是发现参照点数；不表示最少点数，也不是整局检测位置上限。坐标及三角形来自已保存的连续覆盖证据。',fontsize=9,color='#667386')
    save(fig,'q4_25point_cover')


def interval_plot(ax, cell, title, accent):
    cert=cell['certificate']
    rows=cell['positive_outer']+[cell['negative_outer'],cert['orientation_intervals']]
    colors=[TEAL,TEAL,ORANGE,accent]
    for y,pieces,color in zip([3,2,1,0],rows,colors):
        ax.add_patch(Rectangle((0,y-.28),360,.56,facecolor='#F0F3F6',edgecolor='none',zorder=0))
        for a,b in pieces:
            ax.add_patch(Rectangle((a,y-.28),b-a,.56,facecolor=color,edgecolor='none',alpha=.82))
    if cert['discarded']:
        ax.text(180,0,'空集 → 整格可排除',ha='center',va='center',color=RED,fontsize=12,weight='bold')
    ax.set_xlim(0,360)
    ax.set_ylim(-.65,3.7)
    ax.set_yticks([3,2,1,0])
    ax.set_yticklabels(['阳性 p-','阳性 p+','阴性 q','全部交集'])
    ax.set_xticks([0,90,180,270,360])
    ax.set_xticklabels(['0°','90°','180°','270°','360°'])
    ax.set_xlabel('允许的发射朝向（0° 与 360° 为同一方向）',fontsize=10)
    ax.set_title(title,loc='left',fontsize=12,color=accent,pad=10)
    for name in ('left','right','top'):
        ax.spines[name].set_visible(False)
    ax.tick_params(axis='y',length=0)


def joint_figure(data):
    fig=plt.figure(figsize=(12.2,8.0))
    fig.text(.07,.95,'联合位置单元与发射朝向：全格不相容才排除',fontsize=18,color=INK,weight='bold')
    fig.text(.07,.91,'连续单元的方向外包，不是几个代表点的投票；阴性 q 已对两个整格取得距离保证。',fontsize=10.5,color='#596779')
    gs=gridspec.GridSpec(2,2,height_ratios=[1.0,1.13])
    gs.update(left=.09,right=.965,bottom=.13,top=.855,hspace=.57,wspace=.38)
    ax=fig.add_subplot(gs[0,:])
    for cell,color in zip(data['cells'],[RED,BLUE]):
        ax.add_patch(Polygon(cell['polygon'],closed=True,edgecolor=color,facecolor=color,lw=1.5,alpha=.9,zorder=4))
    for p in data['positive_positions']:
        ax.plot([0,p[0]],[0,p[1]],color='#B7CDC9',lw=.9,linestyle='--')
        ax.plot([300,p[0]],[0,p[1]],color='#B8CAE0',lw=.8,linestyle=':')
    positive=data['positive_positions']
    ax.scatter([p[0] for p in positive],[p[1] for p in positive],marker='^',s=75,c=TEAL,zorder=5)
    ax.scatter([150],[0],marker='X',s=65,c=ORANGE,zorder=5)
    ax.scatter([300],[0],marker='o',s=13,c='white',zorder=6)
    ax.annotate('P0：待排除单元',xy=(0,10),xytext=(-20,160),fontsize=10,color=RED,
                arrowprops=dict(arrowstyle='-',color=RED))
    ax.annotate('P1：仍含相容源 (300, 0)',xy=(300,10),xytext=(320,150),fontsize=10,color=BLUE,
                arrowprops=dict(arrowstyle='-',color=BLUE))
    ax.annotate('阴性 q = (150, 0)',xy=(150,-10),xytext=(80,-185),fontsize=10,color='#AC671D',
                arrowprops=dict(arrowstyle='-',color=ORANGE))
    ax.text(1190,230,'阳性 p+ = (1450, 190)',fontsize=10,color=TEAL)
    ax.text(1190,-285,'阳性 p- = (1450, −190)',fontsize=10,color=TEAL)
    ax.set_xlim(-100,1660)
    ax.set_ylim(-325,285)
    ax.set_aspect('equal',adjustable='box')
    ax.set_xlabel('x / m',fontsize=10)
    ax.set_ylabel('y / m',fontsize=10)
    ax.set_xticks([0,300,600,900,1200,1500])
    ax.set_yticks([-200,0,200])
    for name in ('top','right'):
        ax.spines[name].set_visible(False)
    interval_plot(fig.add_subplot(gs[1,0]),data['cells'][0],'P0 = [−10,10] × [−10,10] m',RED)
    interval_plot(fig.add_subplot(gs[1,1]),data['cells'][1],'P1 = [290,310] × [−10,10] m',BLUE)
    fig.text(.09,.055,'两格的全向解释均已被阴性 q 排除。P0 的方向外包交为空；P1 的交非空，只说明必须继续保留。',fontsize=10,color=INK)
    fig.text(.09,.022,'方向区间来自冻结 joint 代码的整格计算，采用浮点容差；本图不表示 Fraction 精确联合认证。',fontsize=9,color='#667386')
    save(fig,'q4_joint_cell_exclusion')


geometry=json.loads(GEOMETRY.read_text(encoding='utf-8'))
joint=json.loads(JOINT.read_text(encoding='utf-8'))
covering_figure(geometry)
joint_figure(joint)
manifest=dict(python=sys.version,matplotlib=matplotlib.__version__,font='Microsoft YaHei',
              inputs={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (GEOMETRY,JOINT)},
              script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              outputs=['q4_25point_cover.png','q4_25point_cover.svg','q4_joint_cell_exclusion.png','q4_joint_cell_exclusion.svg'],
              scope='模型说明图；使用冻结几何/联合外包结果，不是新增性能试验')
(OUT/'figure_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(manifest,ensure_ascii=True))
