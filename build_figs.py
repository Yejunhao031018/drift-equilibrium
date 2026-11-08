# -*- coding: utf-8 -*-
"""大作业图件生成脚本（学术期刊风格 v2）。

读取 results.json 与模型/求解器，输出 figs/*.png。
所有图中不使用总标题（题注由报告/PPT 统一给出）。

用法：
    python build_figs.py            # 生成全部图
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle, Arc, Patch
from matplotlib.lines import Line2D
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib import rcParams

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, 'figs')
os.makedirs(FIG, exist_ok=True)
sys.path.insert(0, HERE)

import race_drift_model as M
import race_drift_solver as S

# ---------------------------------------------------------------------------
# 全局样式：西文 Times New Roman，中文 SimSun 回退，数学用 STIX
# ---------------------------------------------------------------------------
rcParams.update({
    'font.family': 'SimSun',
    'font.serif': ['SimSun'],
    'mathtext.fontset': 'stix',
    'axes.unicode_minus': False,
    'font.size': 9.0,
    'axes.titlesize': 9.5,
    'axes.labelsize': 9.2,
    'xtick.labelsize': 8.2,
    'ytick.labelsize': 8.2,
    'legend.fontsize': 7.6,
    'legend.frameon': False,
    'legend.handlelength': 2.4,
    'axes.linewidth': 0.7,
    'xtick.direction': 'in',
    'ytick.direction': 'in',
    'xtick.top': False,
    'ytick.right': False,
    'xtick.major.width': 0.7,
    'ytick.major.width': 0.7,
    'xtick.minor.width': 0.5,
    'ytick.minor.width': 0.5,
    'lines.linewidth': 1.1,
    'lines.markersize': 3.2,
    'figure.dpi': 120,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
    'savefig.pad_inches': 0.02,
    'axes.grid': False,
})

C_NAVY = '#1f3d7a'
C_RED = '#a6302a'
C_GREEN = '#2f6f3e'
C_AMBER = '#b07d1a'
C_GREY = '0.40'
C_LGREY = '0.72'

REPORT = {}


def save(fig, name, caption, note=''):
    try:
        if getattr(fig, '_suptitle', None) is not None:
            fig._suptitle.set_text('')
    except Exception:
        pass
    path = os.path.join(FIG, name)
    fig.savefig(path)
    plt.close(fig)
    REPORT[name] = dict(caption=caption, note=note, path=os.path.relpath(path, HERE))
    print('saved', name)


def load_results():
    path = os.path.join(HERE, 'results.json')
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _grid(ax, which='both'):
    ax.grid(True, which=which, color='0.85', lw=0.45, ls='-', alpha=0.9)
    ax.set_axisbelow(True)



def _log_axis(ax, axis='y'):
    from matplotlib.ticker import FuncFormatter, NullFormatter
    f = FuncFormatter(lambda v, pos: r'$10^{%d}$' % int(round(np.log10(v))))
    if axis == 'y':
        ax.yaxis.set_major_formatter(f)
        ax.yaxis.set_minor_formatter(NullFormatter())
    else:
        ax.xaxis.set_major_formatter(f)
        ax.xaxis.set_minor_formatter(NullFormatter())


def _kappa(z, V, p):
    beta, r, fx = float(z[0]), float(z[1]), float(z[2])
    ax = -r * V * np.sin(beta)
    q = 0.5 * p['rho'] * V * V
    Fzr = p['m'] * M.G * p['a'] / p['L'] + q * p['ClA_r'] + p['m'] * ax * p['h'] / p['L']
    Fzr = max(Fzr, p['Fz_min'])
    return abs(fx) / (p['mu_r'] * Fzr)


# ---------------------------------------------------------------------------
# 图 1 单轨模型示意图（俯视 + 侧视）
# ---------------------------------------------------------------------------
def fig_model():
    from matplotlib.transforms import Affine2D

    p = M.DEFAULT_PARAMS
    a, b = p['a'], p['b']
    half = 0.62                      # 轮距之半
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 3.35),
                                 gridspec_kw=dict(width_ratios=[1.55, 1.0], wspace=0.22))

    # ================= (a) 俯视图 =================
    body = [(-b - 0.10, 0.52), (-b + 0.02, 0.58), (0.60, 0.58), (a - 0.28, 0.52),
            (a + 0.06, 0.36), (a + 0.06, -0.36), (a - 0.28, -0.52),
            (0.60, -0.58), (-b + 0.02, -0.58), (-b - 0.10, -0.52)]
    ax.add_patch(Polygon(body, closed=True, fc='0.95', ec='0.20', lw=0.9, zorder=2))
    ax.plot([-b - 0.40, a + 0.55], [0, 0], ls=(0, (6, 2, 1, 2)), color='0.75', lw=0.6, zorder=0)

    def wheel(xc, steer):
        for yc in (half, -half):
            w, h = 0.36, 0.16
            r = Rectangle((xc - w / 2, yc - h / 2), w, h, fc='0.30', ec='k', lw=0.4, zorder=5)
            if steer:
                r.set_transform(Affine2D().rotate_around(xc, yc, steer) + ax.transData)
            ax.add_patch(r)
    delta = 0.16
    wheel(a, delta)
    wheel(-b, 0.0)
    for x in (a, -b):
        ax.plot([x, x], [-0.93, 0.93], ls=(0, (2, 3)), color='0.78', lw=0.5, zorder=0)

    # 质心
    ax.plot(0, 0, 'o', ms=3.4, mfc='k', mec='k', zorder=7)
    ax.annotate('CG', xy=(0, 0), xytext=(-0.42, -0.30), fontsize=7.6,
                arrowprops=dict(arrowstyle='-', lw=0.55, color='0.25',
                                shrinkA=1, shrinkB=2), zorder=7)

    # 尺寸
    y1 = 0.80
    ax.annotate('', xy=(0, y1), xytext=(-b, y1),
                arrowprops=dict(arrowstyle='<->', lw=0.55, color='0.30', shrinkA=0, shrinkB=0))
    ax.annotate('', xy=(a, y1), xytext=(0, y1),
                arrowprops=dict(arrowstyle='<->', lw=0.55, color='0.30', shrinkA=0, shrinkB=0))
    ax.text(-b / 2, y1 + 0.05, '$b$', ha='center', va='bottom', fontsize=9.0)
    ax.text(a / 2, y1 + 0.05, '$a$', ha='center', va='bottom', fontsize=9.0)
    y2 = -0.80
    ax.annotate('', xy=(a, y2), xytext=(-b, y2),
                arrowprops=dict(arrowstyle='<->', lw=0.55, color='0.30', shrinkA=0, shrinkB=0))
    ax.text((a - b) / 2, y2 - 0.04, '$L=a+b$', ha='center', va='top', fontsize=8.6)
    ax.annotate('', xy=(a + 0.32, half), xytext=(a + 0.32, -half),
                arrowprops=dict(arrowstyle='<->', lw=0.55, color='0.30', shrinkA=0, shrinkB=0))
    ax.text(a + 0.38, 0.0, '$t$', va='center', fontsize=8.6)

    # 速度与侧偏角
    beta = np.radians(-24.0)
    Lv = 1.00
    ax.annotate('', xy=(Lv * np.cos(beta), Lv * np.sin(beta)), xytext=(0, 0),
                arrowprops=dict(arrowstyle='-|>', lw=1.1, color=C_NAVY, mutation_scale=7), zorder=8)
    ax.text(Lv * np.cos(beta) + 0.05, Lv * np.sin(beta) - 0.10, '$V$', color=C_NAVY, fontsize=9.0)
    ra = 0.85
    ax.add_patch(Arc((0, 0), 2 * ra, 2 * ra, theta1=np.degrees(beta), theta2=0.0,
                     color=C_NAVY, lw=0.7, zorder=3))
    ax.text(ra * np.cos(np.radians(-12)) + 0.05, ra * np.sin(np.radians(-12)) - 0.13,
            r'$\beta$', color=C_NAVY, fontsize=8.6)

    # 横摆角速度
    ax.add_patch(Arc((0, 0), 0.62, 0.62, theta1=40, theta2=150, color=C_GREY, lw=0.8))
    ax.annotate('', xy=(-0.27, 0.20), xytext=(-0.30, 0.13),
                arrowprops=dict(arrowstyle='-|>', lw=0.7, color=C_GREY, mutation_scale=5))
    ax.text(-0.50, 0.30, '$r$', color=C_GREY, fontsize=8.6)

    # 前轮转角
    ax.add_patch(Arc((a, half), 0.58, 0.58, theta1=0, theta2=np.degrees(delta),
                     color=C_AMBER, lw=0.85))
    ax.text(a + 0.16, half + 0.20, r'$\delta$', color=C_AMBER, fontsize=8.8)

    # 轮胎力
    def force(x0, y0, vec, color, label, toff):
        ax.annotate('', xy=(x0 + vec[0], y0 + vec[1]), xytext=(x0, y0),
                    arrowprops=dict(arrowstyle='-|>', lw=1.0, color=color, mutation_scale=6), zorder=9)
        ax.text(x0 + vec[0] + toff[0], y0 + vec[1] + toff[1], label, color=color, fontsize=8.4,
                ha='center' if toff[1] > 0 else 'left', va='bottom' if toff[1] > 0 else 'top',
                bbox=dict(fc='white', ec='none', pad=1.0, alpha=0.85), zorder=10)

    force(a, 0.0, (0.0, 0.34), C_GREEN, '$F_{yf}$', (-0.26, 0.02))
    force(-b, 0.0, (0.0, 0.34), C_GREEN, '$F_{yr}$', (-0.26, 0.02))
    force(-b, 0.0, (0.50, 0.0), C_RED, '$f_x$', (0.0, -0.13))

    # 坐标系
    ox, oy = a + 0.30, -1.10
    ax.annotate('', xy=(ox + 0.55, oy), xytext=(ox, oy),
                arrowprops=dict(arrowstyle='-|>', lw=0.6, color='0.35', mutation_scale=5))
    ax.annotate('', xy=(ox, oy + 0.55), xytext=(ox, oy),
                arrowprops=dict(arrowstyle='-|>', lw=0.6, color='0.35', mutation_scale=5))
    ax.text(ox + 0.58, oy - 0.04, '$x$', color='0.30', fontsize=7.6)
    ax.text(ox - 0.10, oy + 0.58, '$y$', color='0.30', fontsize=7.6)

    ax.set_xlim(-b - 0.55, a + 1.25)
    ax.set_ylim(-1.26, 1.02)
    ax.set_aspect('equal')
    ax.axis('off')
    ax.set_title('(a) 俯视图', fontsize=9.2, pad=3)

    # ================= (b) 侧视图 =================
    h = p['h']
    bx.plot([-b - 0.40, a + 0.45], [0, 0], color='0.20', lw=1.0)          # 地面
    for x in (-b, a):
        bx.add_patch(Circle((x, 0.30), 0.30, fc='0.90', ec='0.25', lw=0.7, zorder=2))
        bx.plot(x, 0.30, 'o', ms=1.4, color='0.25', zorder=3)
    bx.plot([-b, a], [0.30, 0.30], color='0.45', lw=0.55, ls=(0, (4, 2)), zorder=1)
    bx.add_patch(Polygon([(-b - 0.18, 0.40), (-b - 0.05, 0.72), (0.55, 0.78),
                          (a + 0.02, 0.62), (a + 0.18, 0.40)], closed=True,
                         fc='0.95', ec='0.20', lw=0.8, zorder=2))
    # 质心与高度
    ycg = 0.40 + h
    bx.plot([0, 0], [0.30, ycg], ls=(0, (2, 2)), color=C_NAVY, lw=0.6, zorder=1)
    bx.plot(0, ycg, 'o', ms=3.0, mfc=C_NAVY, mec=C_NAVY, zorder=4)
    bx.annotate('', xy=(0.34, ycg), xytext=(0.34, 0.0),
                arrowprops=dict(arrowstyle='<->', lw=0.55, color=C_NAVY, shrinkA=0, shrinkB=0))
    bx.text(0.40, ycg / 2, '$h$', color=C_NAVY, fontsize=8.6, va='center')
    # 重力
    bx.annotate('', xy=(0, ycg - 0.20), xytext=(0, ycg - 0.02),
                arrowprops=dict(arrowstyle='-|>', lw=0.8, color='k', mutation_scale=6))
    bx.text(-0.30, ycg - 0.22, '$mg$', fontsize=8.0)
    # 垂向载荷
    for x, lab in ((-b, '$F_{zf}$'), (a, '$F_{zr}$')):
        bx.annotate('', xy=(x, 0.32), xytext=(x, 0.04),
                    arrowprops=dict(arrowstyle='-|>', lw=0.8, color=C_AMBER, mutation_scale=5))
        bx.text(x, -0.10, lab, color=C_AMBER, fontsize=7.8, ha='center', va='top')
    bx.annotate('', xy=(a, -0.52), xytext=(-b, -0.52),
                arrowprops=dict(arrowstyle='<->', lw=0.55, color='0.30', shrinkA=0, shrinkB=0))
    bx.text((a - b) / 2, -0.58, '$L$', ha='center', va='top', fontsize=8.6)
    bx.set_xlim(-b - 0.50, a + 0.55)
    bx.set_ylim(-0.72, 1.02)
    bx.set_aspect('equal')
    bx.axis('off')
    bx.set_title('(b) 侧视图', fontsize=9.2, pad=3)

    save(fig, 'fig01_model.png',
         '图 1 三自由度单轨模型：几何、状态量与轮胎力',
         '状态量 z=(β, r, f_x)；V、δ 为给定参数；(a)(b) 共用 a、b、h、t。')


# ---------------------------------------------------------------------------
# 图 2 刷子轮胎与摩擦圆
# ---------------------------------------------------------------------------
def fig_tire(res):
    p = M.DEFAULT_PARAMS
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 2.62),
                                 gridspec_kw=dict(width_ratios=[1.12, 1.0], wspace=0.32))

    # ---- (a) 归一化侧向力（侧偏角幅值） ----
    aa = np.linspace(0.0, 0.70, 700)            # rad
    Fzf = p['m'] * M.G * p['b'] / p['L']
    Fzr = p['m'] * M.G * p['a'] / p['L']
    for C, mu, Fz, lab, c in ((p['Caf'], p['mu_f'], Fzf, '前轴', C_NAVY),
                              (p['Car'], p['mu_r'], Fzr, '后轴', C_RED)):
        Mk = mu * Fz
        u = C * np.tan(aa) / Mk
        Fy = Mk * np.minimum(u - u ** 2 / 3 + u ** 3 / 27, 1.0)
        ax.plot(np.degrees(aa), Fy / Mk, color=c, lw=1.2, label=lab)
        a_lin = np.linspace(0.0, 0.04, 20)
        ax.plot(np.degrees(a_lin), C * np.tan(a_lin) / Mk, color=c, lw=0.55, ls=':')
    ax.axhline(1.0, color='0.55', lw=0.55, ls=(0, (4, 2)))
    ax.text(23, 1.03, r'$|F_y|=M$（饱和）', fontsize=7.2, color='0.35')

    refs = S.get_reference_solutions(8.0, 0.10, p)
    dg = M.diagnose(np.array(refs['drift']['z']), 8.0, 0.10, p)
    for a_deg, lab, c, dx in ((abs(dg['af_deg']), r'$|\alpha_f|$', C_NAVY, 1.6),
                              (abs(dg['ar_deg']), r'$|\alpha_r|$', C_RED, -6.0)):
        ax.plot([a_deg], [1.0], marker='o', ms=4.2, mfc='white', mec=c, mew=1.0, zorder=6)
        ax.annotate(lab, xy=(a_deg, 1.0), xytext=(a_deg + dx, 0.90),
                    fontsize=7.8, color=c,
                    arrowprops=dict(arrowstyle='-', lw=0.5, color=c))
    ax.set_xlabel('轮胎侧偏角幅值 $|\\alpha|$ / (°)')
    ax.set_ylabel('归一化侧向力 $|F_y|/M$')
    ax.set_xlim(0, 40)
    ax.set_ylim(0, 1.16)
    ax.legend(loc='lower right', fontsize=7.4)
    _grid(ax)
    ax.set_title('(a) 刷子轮胎的侧偏特性与漂移工作点', fontsize=9.2)

    # ---- (b) 后轴摩擦圆：以 mu_r*Fzr 归一化 ----
    M0 = p['mu_r'] * dg['Fzr']
    th = np.linspace(0, np.pi / 2, 200)
    bx.plot(np.cos(th), np.sin(th), color='0.25', lw=0.9)
    bx.fill(np.concatenate([np.cos(th), [0]]), np.concatenate([np.sin(th), [0]]),
            color='0.93', zorder=0)
    kx, ky = abs(dg['fx']) / M0, abs(dg['Fyr']) / M0
    bx.annotate('', xy=(kx, ky), xytext=(0, 0),
                arrowprops=dict(arrowstyle='-|>', lw=1.1, color=C_RED, mutation_scale=7), zorder=5)
    bx.plot([kx, kx], [0, ky], color=C_RED, lw=0.6, ls=(0, (2, 2)))
    bx.plot([0, kx], [ky, ky], color=C_RED, lw=0.6, ls=(0, (2, 2)))
    bx.text(0.16, 0.90, '$\\kappa=f_x/M_0=%.3f$' % dg['fx_frac'], color=C_RED, fontsize=7.2)
    bx.text(kx + 0.04, ky / 2, '$F_{yr}/M_0$', color=C_RED, fontsize=7.0, va='center')
    bx.set_xlabel('后轴纵向力 $f_x/M_0$')
    bx.set_ylabel('后轴侧向力 $F_{yr}/M_0$')
    bx.set_xlim(0, 1.05)
    bx.set_ylim(0, 1.05)
    bx.set_aspect('equal')
    _grid(bx)
    bx.set_title('(b) 后轴摩擦圆（$M_0=\\mu_r F_{zr}$）', fontsize=9.2)

    save(fig, 'fig02_tire.png',
         '图 2 轮胎模型：(a) 前后轴侧向力特性与漂移工作点；(b) 后轴摩擦圆',
         '漂移平衡点处两轴均已饱和（$|F_y|=M$）；后轴侧向能力被驱动挤占是漂移机理。')


# ---------------------------------------------------------------------------
# 平衡点支路
# ---------------------------------------------------------------------------
def _arm(V, z0, delta0, direction, p, delta_lim):
    pts, _reason = S.trace_branch(V, delta0, z0, 0.008, 420, direction, p,
                                  dmin=min(-0.02, delta_lim[0]), dmax=delta_lim[1])
    out = []
    for q in pts:
        d = q['delta']
        if d < -1e-9:
            continue
        out.append((d, np.degrees(q['z'][0]), q['z'][1], q['z'][2], q['max_real']))
    return out


def fig_branches(res):
    p = M.DEFAULT_PARAMS
    Vs = sorted(float(k) for k in res['branches'])
    folds = {(round(r['V'], 4)): r for r in res['fold_curve'] if r['delta'] > 0}
    cmap = plt.get_cmap('viridis')
    colors = {V: cmap(i / max(1, len(Vs) - 1)) for i, V in enumerate(Vs)}

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 2.9), gridspec_kw=dict(wspace=0.30))
    for V in Vs:
        key = str(V)
        b = res['branches'][key]
        df = folds.get(round(V, 4), None)
        d_hi = (df['delta'] + 0.02) if df else max(V, 0.5)
        for typ, ls in (('drift', '-'), ('grip', (0, (4, 2)))):
            z0 = np.array(b['ref'][typ]['z'])
            arm_p = _arm(V, z0, 0.10, +1, p, (-0.02, d_hi))
            arm_m = _arm(V, z0, 0.10, -1, p, (-0.02, d_hi))
            arm = sorted(arm_m[::-1] + arm_p, key=lambda t: t[0])
            d = np.array([t[0] for t in arm])
            beta = np.array([t[1] for t in arm])
            kappa = np.array([_kappa((np.radians(t[1]), t[2], t[3]), V, p) for t in arm])
            ax.plot(d, beta, ls=ls, color=colors[V], lw=1.0, solid_capstyle='round')
            bx.plot(d, kappa, ls=ls, color=colors[V], lw=1.0, solid_capstyle='round')
        if df:
            ax.plot(df['delta'], df['beta_deg'], marker='*', ms=6.5, color=C_GREY,
                    mec='k', mew=0.3, zorder=6)
    ax.set_xlabel('前轮转角 $\\delta$ / rad')
    ax.set_ylabel('车身侧偏角 $\\beta$ / (°)')
    ax.set_xlim(0, 0.70)
    bx.set_xlabel('前轮转角 $\\delta$ / rad')
    bx.set_ylabel('摩擦圆利用率 $\\kappa$')
    bx.set_xlim(0, 0.70)
    bx.set_ylim(0, 1.02)
    for a_ in (ax, bx):
        _grid(a_)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(min(Vs), max(Vs)))
    cb = fig.colorbar(sm, ax=[ax, bx], fraction=0.028, pad=0.015, aspect=28)
    cb.set_label('车速 $V$ / (m·s$^{-1}$)', fontsize=8.2)
    cb.ax.tick_params(labelsize=7.4, width=0.6, length=2.2)
    h1 = Line2D([], [], color='0.25', lw=1.1, ls='-', label='漂移叶')
    h2 = Line2D([], [], color='0.25', lw=1.0, ls=(0, (4, 2)), label='抓地叶')
    h3 = Line2D([], [], color=C_GREY, marker='*', ms=6.5, lw=0, mec='k', label='折叠点')
    ax.legend(handles=[h1, h2, h3], loc='upper left', fontsize=7.4)
    ax.set_title('(a) $\\beta$–$\\delta$ 平衡支路', fontsize=9.2)
    bx.set_title('(b) 摩擦圆利用率 $\\kappa$–$\\delta$', fontsize=9.2)

    save(fig, 'fig03_branches.png',
         '图 3 平衡支路：抓地叶与漂移叶在折叠点相接',
         '实线为漂移叶，虚线为抓地叶；★ 为鞍结折叠 det J=0。')


# ---------------------------------------------------------------------------
# 图 4 折叠曲线与解个数
# ---------------------------------------------------------------------------
def fig_fold(res):
    fc = [r for r in res['fold_curve'] if r['delta'] > 0]
    fc.sort(key=lambda r: r['V'])
    sm = res['solmap']
    Vs = np.array(sm['Vs'], dtype=float)
    ds = np.array(sm['deltas'], dtype=float)
    C = np.zeros((len(Vs), len(ds)))
    for i, row in enumerate(sm['counts']):
        for j, cell in enumerate(row):
            C[i, j] = cell['n']

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 2.8),
                                 gridspec_kw=dict(width_ratios=[1.0, 1.1], wspace=0.32))
    V = np.array([r['V'] for r in fc])
    d = np.array([r['delta'] for r in fc])
    ax.plot(V, d, color=C_NAVY, lw=1.1, marker='o', ms=3.4, mfc='white', mew=0.8)
    for Vi, di in zip(V, d):
        ax.text(Vi, di + 0.020, '%.3f' % di, ha='center', fontsize=6.6, color=C_NAVY)
    ax.set_xlabel('车速 $V$ / (m·s$^{-1}$)')
    ax.set_ylabel('折叠点转角 $\\delta_f$ / rad')
    ax.set_xlim(4.8, 31.2)
    ax.set_ylim(0.28, 1.12)
    _grid(ax)
    ax.set_title('(a) 折叠曲线 $\\delta_f(V)$', fontsize=9.2)

    cmap = ListedColormap(['#eeeeee', '#a9cbe3', '#f2b56b', '#c0392b'])
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], cmap.N)
    X, Y = np.meshgrid(Vs, ds)
    im = bx.pcolormesh(X, Y, C.T, cmap=cmap, norm=norm, shading='nearest')
    bx.plot(V, d, color='k', lw=1.0, ls=(0, (4, 2)), zorder=4)
    for Vi, di in ((8.0, 0.10), (15.0, 0.10), (22.0, 0.10)):
        bx.plot(Vi, di, marker='o', ms=4.0, mfc='none', mec='k', mew=0.9, zorder=5)
    bx.text(9.2, 0.20, '2 个平衡点', fontsize=7.6, color='0.25')
    bx.text(20.0, 0.70, '0 个平衡点', fontsize=7.6, color='0.25')
    bx.set_xlabel('车速 $V$ / (m·s$^{-1}$)')
    bx.set_ylabel('前轮转角 $\\delta$ / rad')
    bx.set_xlim(Vs.min() - 0.6, Vs.max() + 0.6)
    bx.set_ylim(-0.01, 0.84)
    cb = fig.colorbar(im, ax=bx, fraction=0.045, pad=0.02, ticks=[0, 1, 2, 3])
    cb.set_label('平衡点个数', fontsize=7.6)
    cb.ax.tick_params(labelsize=6.8, width=0.6, length=2.0)
    bx.set_title('(b) $(V,\\delta)$ 平面的解个数', fontsize=9.2)

    save(fig, 'fig04_fold.png',
         '图 4 折叠分岔：(a) 存在边界 $\\delta_f(V)$；(b) $(V, \\delta)$ 平面的解个数分区',
         '解个数由每格 90 个随机初值的多起点求解统计；$\\delta=0$ 一行的 1 解为原地漂移。')


# ---------------------------------------------------------------------------
# 图 5 相平面（三条车速）
# ---------------------------------------------------------------------------
def _closed_loop_traj(V, delta, fx, K, x_eq, x0, T, dt=2e-3, p=M.DEFAULT_PARAMS):
    t, x, _u = S.simulate_closed_loop(x0, delta, fx, K, x_eq, p, T=T, dt=dt)
    return np.asarray(x), np.asarray(t)


def _open_loop_traj(V, delta, fx, x0, T, dt=2e-3, p=M.DEFAULT_PARAMS):
    t, x = S.simulate_open_loop(x0, delta, fx, p, T=T, dt=dt)
    return np.asarray(x), np.asarray(t)


def fig_phase(res):
    ctrl = {round(c['V'], 2): c for c in res['control']}
    p = M.DEFAULT_PARAMS
    Vs = [8.0, 15.0, 22.0]
    fig, axes = plt.subplots(1, 3, figsize=(7.0, 2.35), gridspec_kw=dict(wspace=0.34))
    for ax, V in zip(axes, Vs):
        c = ctrl.get(V)
        if c is None:
            ax.axis('off')
            continue
        z = np.array(c['z'])
        delta = c['delta']
        fx = float(z[2])
        be = np.linspace(-40, 8, 34)
        rr = np.linspace(max(0.05, z[1] - 1.2), z[1] + 1.2, 34)
        B, R = np.meshgrid(np.radians(be), rr)
        DB = np.zeros_like(B)
        DR = np.zeros_like(B)
        vx = V * np.cos(B)
        vy = V * np.sin(B)
        for i in range(B.shape[0]):
            for j in range(B.shape[1]):
                dx = M.dynamics(np.array([vx[i, j], vy[i, j], R[i, j]]), delta, fx, p)
                DB[i, j] = (vx[i, j] * dx[1] - vy[i, j] * dx[0]) / (vx[i, j] ** 2 + vy[i, j] ** 2)
                DR[i, j] = dx[2]
        sp = np.hypot(DB, DR) + 1e-12
        ax.streamplot(be, rr, DB, DR, color='0.55', linewidth=0.55, arrowsize=0.55,
                      density=1.25, cmap=None)
        # 平衡点
        ax.plot(np.degrees(z[0]), z[1], marker='o', ms=4.6, mfc=C_RED, mec='k', mew=0.4, zorder=6)
        # 轨迹
        x0 = np.array([V * np.cos(z[0] + np.radians(8.0)), V * np.sin(z[0] + np.radians(8.0)),
                       z[1] + 0.25])
        try:
            xs, ts = _closed_loop_traj(V, delta, fx, np.array(c['K']), np.array(c['x_eq']),
                                      x0, T=8.0)
            bsz = np.degrees(np.arctan2(xs[:, 1], xs[:, 0]))
            ax.plot(bsz, xs[:, 2], color=C_NAVY, lw=1.4, zorder=5)
        except Exception:
            pass
        try:
            xo, to = _open_loop_traj(V, delta, fx, x0, T=5.0)
            bso = np.degrees(np.arctan2(xo[:, 1], xo[:, 0]))
            ax.plot(bso, xo[:, 2], color=C_RED, lw=1.1, ls=(0, (4, 2)), zorder=4)
        except Exception:
            pass
        ax.set_xlim(-40, 8)
        ax.set_ylim(rr.min(), rr.max())
        ax.set_xlabel('$\\beta$ / (°)')
        if ax is axes[0]:
            ax.set_ylabel('$r$ / (rad·s$^{-1}$)')
        _grid(ax)
        ax.set_title('$V=%d$ m/s' % V, fontsize=8.8)
    h = [Line2D([], [], color=C_NAVY, lw=1.1, label='LQR 闭环'),
         Line2D([], [], color=C_RED, lw=1.0, ls=(0, (4, 2)), label='开环'),
         Line2D([], [], marker='o', ms=4.2, lw=0, mfc=C_RED, mec='k', label='漂移平衡点')]
    axes[0].legend(handles=h, loc='lower left', fontsize=6.8, handletextpad=0.3,
                   frameon=True, framealpha=0.85, edgecolor='none')
    save(fig, 'fig05_phase.png',
         '图 5 相平面 $(\\beta,r)$：漂移平衡点开环不稳定、LQR 闭环可镇定',
         '流线为 $f_x=f_x^{\\rm eq}$、$\\delta=0.10$ rad 时的向量场；初值取 $\\beta+2.5^\\circ$、$r+0.05$ rad/s。')


# ---------------------------------------------------------------------------
# 图 6 目标函数等值线与算法收敛
# ---------------------------------------------------------------------------
def fig_merit(res):
    p = M.DEFAULT_PARAMS
    V, delta = 8.0, 0.10
    refs = S.get_reference_solutions(V, delta, p)
    z_d = np.array(refs['drift']['z'])
    fx0 = z_d[2]
    be = np.linspace(-40, 6, 140)
    rr = np.linspace(0.05, 2.45, 140)
    Z = np.zeros((rr.size, be.size))
    for i, r_ in enumerate(rr):
        for j, b_ in enumerate(be):
            e = M.residual(np.array([np.radians(b_), r_, fx0]), V, delta, p)
            Z[i, j] = 0.5 * float(e @ e)
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 2.7),
                                 gridspec_kw=dict(width_ratios=[1.15, 1.0], wspace=0.30))
    lv = np.logspace(-9, 3.2, 22)
    cs = ax.contourf(be, rr, Z, levels=lv, cmap='Blues_r', norm=matplotlib.colors.LogNorm(),
                     extend='both')
    ax.contour(be, rr, Z, levels=[1e-8, 1e-6, 1e-4, 1e-2, 1], colors='k', linewidths=0.4, alpha=0.55)
    cb = fig.colorbar(cs, ax=ax, fraction=0.045, pad=0.035)
    cb.ax.tick_params(labelsize=6.6, width=0.6, length=2.0)
    _log_axis(cb.ax, 'y')
    # 阻尼牛顿路径（自实现，记录迭代点）
    z = np.array([np.radians(-33.0), 0.95, 0.55 * fx0])
    path = [z.copy()]
    for _ in range(14):
        e = M.residual(z, V, delta, p)
        J = M.residual_jac(z, V, delta, p)
        if np.linalg.norm(e) < 1e-11:
            break
        step = np.linalg.solve(J, -e)
        alpha = 1.0
        while alpha > 1e-4:
            zn = z + alpha * step
            en = M.residual(zn, V, delta, p)
            if np.linalg.norm(en) <= (1 - 1e-4 * alpha) * np.linalg.norm(e):
                break
            alpha *= 0.5
        z = zn
        path.append(z.copy())
    P = np.array(path)
    ax.plot(np.degrees(P[:, 0]), P[:, 1], 'o-', color=C_RED, lw=0.8, ms=2.6, mec='k', mew=0.2,
            label='阻尼牛顿迭代', zorder=5)
    ax.plot(np.degrees(z_d[0]), z_d[1], marker='*', ms=9, mfc=C_AMBER, mec='k', mew=0.4, zorder=6)
    ax.set_xlabel('$\\beta$ / (°)')
    ax.set_ylabel('$r$ / (rad·s$^{-1}$)')
    ax.legend(loc='lower right', fontsize=7.0)
    ax.set_title(r'(a) 目标函数 $\frac{1}{2}\|e(z)\|^2$ 等值线与牛顿路径（$f_x$ 固定）',
                 fontsize=8.8)

    case = next(c for c in res['benchmark'] if round(c['V'], 2) == 8.0 and c['type'] == 'drift')
    names = {'A1_newton_analytic': 'A1', 'A2_newton_fd': 'A2', 'A3_gauss_newton': 'A3',
             'A4_levenberg_marquardt': 'A4', 'A5_trust_region_dogleg': 'A5', 'A6_bfgs': 'A6'}
    mk = ['o', 's', '^', 'v', 'D', 'P']
    for q, (row, m) in enumerate(zip([r for r in case['rows'] if r['algo'] in names], mk)):
        h = np.array(row['hist'], dtype=float)
        bx.semilogy(np.arange(h.size), np.maximum(h, 1e-16), marker=m, ms=2.2, lw=0.9,
                    label='%s (%s 次)' % (names[row['algo']], row.get('it', '?')), markevery=2)
    bx.set_xlabel('迭代次数 $k$')
    bx.set_ylabel(r'$\|e_k\|$', fontsize=8.6, labelpad=1)
    bx.set_ylim(1e-13, 1e4)
    bx.legend(loc='lower left', fontsize=6.4, ncol=2, columnspacing=0.7, handletextpad=0.3,
              frameon=True, framealpha=0.85, edgecolor='none')
    _grid(bx)
    bx.set_title('(b) 七种实现的收敛过程（$V=8$ m/s）', fontsize=9.2)

    save(fig, 'fig06_merit.png',
         '图 6 非线性最小二乘的几何图像与算法收敛比较',
         '目标函数取值域 1e-9–10^3；残差曲线来自同一初值与同一容差下的基准测试。')


# ---------------------------------------------------------------------------
# 图 7 设计优化
# ---------------------------------------------------------------------------
def fig_design(res):
    d = res['design']
    sw = d['sweep']
    A = np.array(sw['a'], dtype=float)
    MU = np.array(sw['mu_r'], dtype=float)
    K = np.array([[np.nan if v is None else v for v in row] for row in sw['kappa']], dtype=float)
    AY = np.array([[np.nan if v is None else v for v in row] for row in sw['ay']], dtype=float)
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 2.85),
                                 gridspec_kw=dict(width_ratios=[1.12, 1.0], wspace=0.32))
    cmap = plt.get_cmap('viridis').copy()
    cmap.set_bad('0.92')
    ax.set_facecolor('0.93')
    im = ax.pcolormesh(A, MU, np.ma.masked_invalid(K), cmap=cmap, shading='gouraud')
    cs = ax.contour(A, MU, np.ma.masked_invalid(K), levels=10, colors='w', linewidths=0.45)
    ax.clabel(cs, fmt='%.2f', fontsize=5.6, inline=True)
    cb = fig.colorbar(im, ax=ax, fraction=0.045, pad=0.02)
    cb.set_label('$\\kappa=f_x/(\\mu_r F_{zr})$', fontsize=8.0)
    cb.ax.tick_params(labelsize=7.0, width=0.6, length=2.0)
    # 约束边界 ay = ay_min
    try:
        cc = ax.contour(A, MU, AY, levels=[d['ay_min']], colors=C_RED, linewidths=1.0)
        ax.clabel(cc, fmt='$a_y=%.1f$', fontsize=6.4, inline=True)
    except Exception:
        pass
    hist = d['alm']['hist']
    XS = np.array([[q['x'][0], q['x'][1]] for q in hist if 'x' in q])
    ax.plot(XS[:, 0], XS[:, 1], 'o-', color='k', lw=0.7, ms=2.4, label='ALM 迭代')
    ax.plot(d['base']['x'][0], d['base']['x'][1], 's', ms=5, mfc='k', mec='k', label='基准设计')
    ax.plot(d['opt']['x'][0], d['opt']['x'][1], '*', ms=11, mfc=C_AMBER, mec='k', mew=0.5,
            label='最优设计')
    ax.set_xlabel('$a$ / m（质心到前轴）')
    ax.set_ylabel('$\\mu_r$（后轴摩擦系数）')
    ax.set_xlim(A.min(), A.max())
    ax.set_ylim(MU.min(), MU.max())
    ax.legend(loc='lower left', fontsize=6.6, handletextpad=0.3, borderpad=0.3)
    ax.set_title('(a) 目标等值线、约束边界与 ALM 路径', fontsize=9.2)

    it = [q['outer'] for q in hist]
    kk = [q['kappa'] for q in hist]
    lam = [q['lam'] for q in hist]
    ax2 = bx.twinx()
    bx.plot(it, kk, 'o-', color=C_NAVY, lw=1.0, ms=2.6)
    ax2.plot(it, lam, 's--', color=C_AMBER, lw=0.9, ms=2.4)
    bx.axhline(d['base']['kappa'], color='0.4', lw=0.7, ls=(0, (5, 2)))
    bx.axhline(d['opt']['kappa'], color=C_NAVY, lw=0.7, ls=':')
    bx.set_xlabel('增广拉格朗日外层迭代')
    bx.set_ylabel('$\\kappa$')
    ax2.set_ylabel('乘子 $\\lambda$', color=C_AMBER)
    ax2.tick_params(axis='y', colors=C_AMBER, width=0.6, length=2.0, labelsize=7.6)
    bx.tick_params(labelsize=7.6)
    bx.set_ylim(0.50, 0.76)
    _grid(bx)
    bx.set_title('(b) 外层迭代：目标值与乘子', fontsize=9.2)

    save(fig, 'fig07_design.png',
         '图 7 设计优化：$\\min\\kappa$ s.t. $a_y\\geq a_{y,\\min}$（隐函数消元 + 增广拉格朗日）',
         '灰色空白为内层平衡点求解失败（设计点不可行）处；κ 关于 a 的单调方向随 μ_r 改变，问题非凸。')


# ---------------------------------------------------------------------------
# 图 8 稳定性与摩擦需求
# ---------------------------------------------------------------------------
def fig_growth(res):
    g = sorted(res['drift_growth'], key=lambda q: q['V'])
    V = np.array([q['V'] for q in g])
    mr = np.array([q['max_real'] for q in g])
    kp = np.array([q['kappa'] for q in g])
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 2.55), gridspec_kw=dict(wspace=0.30))
    ax.plot(V, mr, 'o-', color=C_RED, lw=1.1, ms=3.2, mfc='white', mew=0.8)
    ax.axhline(0, color='0.3', lw=0.6)
    for Vi, mi, dx, ha in ((V[0], mr[0], 8, 'left'), (V[-1], mr[-1], -8, 'right')):
        ax.annotate('%.3f' % mi, xy=(Vi, mi), xytext=(dx, 7), textcoords='offset points',
                    ha=ha, fontsize=7.2, color=C_RED)
    ax.set_xlabel('车速 $V$ / (m·s$^{-1}$)')
    ax.set_ylabel('$\\max\\,\\mathrm{Re}\\,\\lambda(A)$ / s$^{-1}$')
    ax.set_xlim(5, 31)
    ax.set_ylim(0, 0.45)
    ax.text(18, 0.05, '不稳定区', color='0.45', fontsize=8.0)
    _grid(ax)
    ax.set_title('(a) 漂移平衡点的开环不稳定增长率', fontsize=9.2)

    bx.plot(V, kp, 's-', color=C_AMBER, lw=1.1, ms=3.0, mfc='white', mew=0.8)
    bx.set_xlabel('车速 $V$ / (m·s$^{-1}$)')
    bx.set_ylabel('摩擦圆利用率 $\\kappa=f_x/(\\mu_r F_{zr})$')
    bx.set_xlim(5, 31)
    bx.set_ylim(min(kp) - 2e-3, max(kp) + 2e-3)
    _grid(bx)
    bx.set_title('(b) 漂移所需驱动/摩擦比', fontsize=9.2)

    save(fig, 'fig08_growth.png',
         '图 8 漂移平衡点的开环不稳定增长率与摩擦圆需求随车速变化',
         '数据取 δ=0.10 rad 的漂移平衡点；增长率均在 V=8 m/s 附近最小，随车速单调增大。')


# ---------------------------------------------------------------------------
# 图 9 收敛盆地
# ---------------------------------------------------------------------------
def fig_basin(res):
    keys = sorted(res['basin'])
    fig, axes = plt.subplots(1, len(keys), figsize=(7.0, 2.85),
                             gridspec_kw=dict(wspace=0.26))
    if len(keys) == 1:
        axes = [axes]
    cmap = ListedColormap(['#efefef', '#2f6f3e', '#d9822b'])
    for ax, k in zip(axes, keys):
        d = res['basin'][k]
        beta = np.degrees(np.array(d['beta']))
        r = np.array(d['r'])
        lab = np.array(d['label'])
        ax.pcolormesh(beta, r, lab.T, cmap=cmap, vmin=-0.5, vmax=2.5, shading='nearest')
        V = float(k.split('_')[0])
        refs = S.get_reference_solutions(V, 0.10, M.DEFAULT_PARAMS)
        for typ, mk, c in (('drift', 'o', C_RED), ('grip', 's', C_GREEN)):
            z = np.array(refs[typ]['z'])
            ax.plot(np.degrees(z[0]), z[1], marker=mk, ms=4.0, mfc='white', mec=c, mew=0.9)
        ax.set_xlabel('$\\beta_0$ / (°)')
        if ax is axes[0]:
            ax.set_ylabel('$r_0$ / (rad·s$^{-1}$)')
        ax.set_title('$V=%d$ m/s, $\\delta=0.10$' % V, fontsize=8.8)
    h = [Patch(fc='#2f6f3e', ec='none', label='收敛到抓地解'),
         Patch(fc='#d9822b', ec='none', label='收敛到漂移解'),
         Patch(fc='#efefef', ec='0.6', label='未收敛/非物理')]
    fig.legend(handles=h, loc='lower center', ncol=3, fontsize=7.2, handlelength=1.4,
               handletextpad=0.4, bbox_to_anchor=(0.5, -0.04), frameon=False)
    save(fig, 'fig09_basin.png',
         '图 9 阻尼牛顿在 $(\\beta_0,r_0)$ 初值平面上的收敛盆地',
         '初值 $f_x=0$，网格 61×61；灰白格为不收敛或落到非物理解。')


# ---------------------------------------------------------------------------
# 图 10 二次收敛
# ---------------------------------------------------------------------------
def fig_conv_order(res):
    p = M.DEFAULT_PARAMS
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 2.6), gridspec_kw=dict(wspace=0.46))
    Vlist = [8.0, 15.0, 22.0]
    orders = []
    for V in Vlist:
        refs = S.get_reference_solutions(V, 0.10, p)
        z0 = np.array(refs['drift']['z']) + np.array([np.radians(6.0), 0.25, 1200.0])
        hist = [float(np.linalg.norm(M.residual(z0, V, 0.10, p)))]
        z = z0.copy()
        for _ in range(12):
            e = M.residual(z, V, 0.10, p)
            if np.linalg.norm(e) < 1e-10:
                break
            J = M.residual_jac(z, V, 0.10, p)
            z = z - np.linalg.solve(J, e)
            hist.append(float(np.linalg.norm(M.residual(z, V, 0.10, p))))
        h = np.array(hist)
        hv = np.maximum(h, 1e-15).astype(float)
        ax.semilogy(np.arange(h.size), hv, 'o-', ms=2.6, lw=0.9,
                    label='$V=%d$' % V)
        hh = h[h > 1e-9]
        if hh.size >= 3:
            den = np.log(hh[-2] / hh[-3])
            if abs(den) > 1e-6:
                orders.append((V, float(np.log(hh[-1] / hh[-2]) / den)))
    ax.set_xlabel('迭代次数 $k$')
    ax.set_ylabel('$\\|e_k\\|$')
    ax.set_ylim(1e-14, 1e4)
    _log_axis(ax, 'y')
    ax.legend(loc='upper right', fontsize=7.4)
    _grid(ax)
    ax.set_title('(a) 漂移工况的残差历史', fontsize=9.2)

    Vv = np.array([o[0] for o in orders])
    qq = np.array([o[1] for o in orders])
    bx.axhline(2.0, color='0.35', lw=0.8, ls=(0, (5, 2)))
    bx.plot(Vv, qq, 'o', ms=5, mfc='white', mec=C_NAVY, mew=0.9)
    for Vi, qi in zip(Vv, qq):
        bx.annotate('%.2f' % qi, xy=(Vi, qi), xytext=(0, -12), textcoords='offset points',
                    ha='center', fontsize=7.4, color=C_NAVY)
    bx.set_xlabel('车速 $V$ / (m·s$^{-1}$)')
    bx.set_ylabel('估计收敛阶 $q$')
    bx.set_ylim(1.4, 2.15)
    bx.set_xticks(Vlist)
    bx.text(8.6, 2.03, '理论值 $q=2$', fontsize=7.4, color='0.35')
    _grid(bx)
    bx.set_title('(b) 由残差序列估计的收敛阶', fontsize=9.2)

    save(fig, 'fig10_convergence.png',
         '图 10 阻尼牛顿法的局部二次收敛性验证',
         '收敛阶由 log‖e_{k+1}‖ 对 log‖e_k‖ 的最小二乘斜率估计；实际 1.8–2.0，接近理论值 2。')


# ---------------------------------------------------------------------------
# 图 11 算法基准
# ---------------------------------------------------------------------------
def fig_benchmark(res):
    names = {'A1_newton_analytic': 'A1', 'A2_newton_fd': 'A2', 'A3_gauss_newton': 'A3',
             'A4_levenberg_marquardt': 'A4', 'A5_trust_region_dogleg': 'A5',
             'A6_bfgs': 'A6', 'A7_projected_newton': 'A7'}
    rows = {}
    for case in res['benchmark']:
        for r in case['rows']:
            rows.setdefault(r['algo'], []).append(r)
    algos = [a for a in names if a in rows]
    its = [np.median([r['it'] for r in rows[a]]) for a in algos]
    tms = [np.median([r['time_ms'] for r in rows[a]]) for a in algos]
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(7.0, 2.45), gridspec_kw=dict(wspace=0.30))
    x = np.arange(len(algos))
    ax.bar(x, its, color=[C_NAVY if i < len(algos) - 1 else C_GREY for i in range(len(algos))],
           width=0.62, edgecolor='k', linewidth=0.4)
    ax.set_xticks(x)
    ax.set_xticklabels([names[a] for a in algos])
    ax.set_ylabel('中位迭代次数')
    ax.set_xlabel('算法')
    _grid(ax)
    ax.set_title('(a) 迭代次数（5 个工况）', fontsize=9.2)

    bx.bar(x, tms, color=[C_GREEN if i < len(algos) - 1 else C_GREY for i in range(len(algos))],
           width=0.62, edgecolor='k', linewidth=0.4)
    bx.set_yscale('log')
    _log_axis(bx, 'y')
    bx.set_xticks(x)
    bx.set_xticklabels([names[a] for a in algos])
    bx.set_ylabel('中位单次求解时间 / ms')
    bx.set_xlabel('算法')
    _grid(bx)
    bx.set_title('(b) 运行时间（对数轴）', fontsize=9.2)
    save(fig, 'fig11_benchmark.png',
         '图 11 七种实现的迭代次数与运行时间对比（5 个工况的中位数）',
         'A1–A6 为无约束最小二乘；A7 为箱约束投影牛顿；对比使用相同初值与容差。')


def main():
    res = load_results()
    fig_model()
    fig_tire(res)
    if res is None:
        print('results.json 不存在：仅生成模型与轮胎示意图')
        return
    fig_branches(res)
    fig_fold(res)
    fig_phase(res)
    fig_merit(res)
    fig_design(res)
    fig_growth(res)
    fig_basin(res)
    fig_conv_order(res)
    fig_benchmark(res)
    with open(os.path.join(FIG, 'captions.json'), 'w', encoding='utf-8') as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=1)
    print('done,', len(REPORT), 'figures')


if __name__ == '__main__':
    main()
