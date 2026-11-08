# -*- coding: utf-8 -*-
"""生成世界坐标系下的漂移轨迹（静态图 + 动画），并导出数据供 HTML 复用。

输出：
    figs/fig12_drift_traj.png   （论文插图：轨迹俯视 + 时间历程 + 侧偏角示意）
    figs/drift_traj.gif         （动画：车辆沿漂移圆行驶，车身/速度矢量可见侧偏角）
    figs/drift_traj.npz         （轨迹数据，供 HTML 演示复用）
"""
import io
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = HERE
for cand in (HERE, os.path.join(os.path.dirname(HERE), '大作业')):
    if os.path.exists(os.path.join(cand, 'race_drift_model.py')):
        BASE = cand
        break
sys.path.insert(0, BASE)
sys.path.insert(0, HERE)

import race_drift_model as M
import race_drift_solver as S

plt.rcParams.update({'font.family': 'SimSun', 'font.serif': ['SimSun'],
                     'mathtext.fontset': 'stix', 'axes.linewidth': 0.8,
                     'xtick.direction': 'in', 'ytick.direction': 'in',
                     'xtick.labelsize': 8.5, 'ytick.labelsize': 8.5,
                     'axes.labelsize': 9.0, 'axes.titlesize': 9.5,
                     'legend.fontsize': 8.0, 'legend.frameon': False,
                     'savefig.dpi': 300, 'figure.dpi': 120,
                     'axes.spines.top': False, 'axes.spines.right': False})
plt.rcParams['axes.unicode_minus'] = False

C_BLUE = '#1f3d7a'
C_RED = '#a6302a'
C_GREEN = '#2f6f3e'
C_GREY = '#57606a'
C_CAR_FACE = '#e8eef7'
C_CAR_EDGE = '#2b4f86'


def pose_from_body(ts, xs, psi0=0.0):
    """由车身速度 (vx,vy,r) 积分出世界坐标 (X,Y,psi)。"""
    n = len(ts)
    X = np.zeros(n); Y = np.zeros(n); PSI = np.zeros(n)
    X[0], Y[0], PSI[0] = 0.0, 0.0, psi0
    for i in range(n - 1):
        if not np.all(np.isfinite(xs[i + 1])):
            X[i + 1:] = np.nan; Y[i + 1:] = np.nan; PSI[i + 1:] = np.nan
            break
        dt = ts[i + 1] - ts[i]
        vx1, vy1, r1 = xs[i]
        vx2, vy2, r2 = xs[i + 1]
        psi_m = PSI[i] + 0.5 * dt * r1
        vxm = 0.5 * (vx1 + vx2); vym = 0.5 * (vy1 + vy2)
        X[i + 1] = X[i] + dt * (vxm * np.cos(psi_m) - vym * np.sin(psi_m))
        Y[i + 1] = Y[i] + dt * (vxm * np.sin(psi_m) + vym * np.cos(psi_m))
        PSI[i + 1] = PSI[i] + dt * 0.5 * (r1 + r2)
    return X, Y, PSI


def body_to_world_vel(psi, vx, vy):
    return (vx * np.cos(psi) - vy * np.sin(psi),
            vx * np.sin(psi) + vy * np.cos(psi))


def car_polygon(X, Y, psi, scale=1.0):
    """车身矩形（俯视）顶点；wheelbase 2.5，车长/宽按 4.2/1.85 比例。"""
    L, W = 4.2 * scale, 1.85 * scale
    hx, hy = 0.5 * L, 0.5 * W
    pts = np.array([[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]])
    c, s = np.cos(psi), np.sin(psi)
    R = np.array([[c, -s], [s, c]])
    return pts @ R.T + np.array([X, Y])


def draw_car(ax, X, Y, psi, scale=1.0, vel=None, vscale=0.22, zorder=3, alpha=0.95):
    poly = car_polygon(X, Y, psi, scale)
    ax.add_patch(plt.Polygon(poly, closed=True, facecolor=C_CAR_FACE,
                             edgecolor=C_CAR_EDGE, lw=1.2, alpha=alpha, zorder=zorder))
    if vel is not None:
        vwx, vwy = vel
        ax.annotate('', xy=(X + vscale * vwx, Y + vscale * vwy), xytext=(X, Y),
                    arrowprops=dict(arrowstyle='-|>', color=C_GREEN, lw=1.9,
                                    shrinkA=0, shrinkB=0), zorder=zorder + 1)


def main():
    out_dir = os.path.join(BASE, 'figs')
    os.makedirs(out_dir, exist_ok=True)
    res = json.load(open(os.path.join(BASE, 'results.json'), encoding='utf-8'))
    V, delta = 8.0, 0.10
    c = res['control'][0]
    p = M.DEFAULT_PARAMS
    x_eq = np.array(c['x_eq'], dtype=float)
    K = np.array(c['K'], dtype=float)
    beta_eq, r_eq, fx_eq = c['z']

    # 初始扰动：侧偏角 +2.5°，横摆角速度 +0.05 rad/s
    db = np.deg2rad(2.5)
    beta0 = beta_eq + db
    x0 = np.array([V * np.cos(beta0), V * np.sin(beta0), r_eq + 0.05])

    ts_c, xs_c, us_c = S.simulate_closed_loop(x0, delta, fx_eq, K, x_eq, p=p,
                                               T=14.0, dt=2e-3)
    ts_o, xs_o = S.simulate_open_loop(x0, delta, fx_eq, p=p, T=3.2, dt=2e-3)
    Xc, Yc, PSIc = pose_from_body(ts_c, xs_c)
    Xo, Yo, PSIo = pose_from_body(ts_o, xs_o)

    R_circ = V / abs(r_eq)
    bc = np.degrees(np.arctan2(xs_c[:, 1], xs_c[:, 0]))
    bo = np.degrees(np.arctan2(xs_o[:, 1], xs_o[:, 0]))

    # ---------- 静态图 ----------
    fig, ax = plt.subplots(figsize=(7.9, 5.5))
    ax.set_aspect('equal')

    ax.plot(Xc, Yc, '-', color=C_BLUE, lw=2.4, label='闭环（LQR）轨迹')
    ax.plot(Xo, Yo, '-', color=C_RED, lw=1.9, label='开环（固定 δ, f_x）轨迹')

    # 车身姿态采样（稳态圈）
    idx = np.linspace(int(0.45 * len(ts_c)), len(ts_c) - 1, 7).astype(int)
    for k, i in enumerate(idx):
        if not np.all(np.isfinite([Xc[i], Yc[i], PSIc[i]])):
            continue
        vel = body_to_world_vel(PSIc[i], xs_c[i, 0], xs_c[i, 1])
        draw_car(ax, Xc[i], Yc[i], PSIc[i], scale=0.72, vel=vel, vscale=0.30)

    # 航向线示意
    i0 = idx[0]
    ax.annotate('', xy=(Xc[i0] + 2.3 * np.cos(PSIc[i0]), Yc[i0] + 2.3 * np.sin(PSIc[i0])),
                xytext=(Xc[i0], Yc[i0]),
                arrowprops=dict(arrowstyle='-', color=C_GREY, lw=1.0, ls='--',
                                shrinkA=0, shrinkB=0))


    # 半径标注
    i_c = 4200
    cx = Xc[i_c] - R_circ * np.sin(PSIc[i_c])
    cy = Yc[i_c] + R_circ * np.cos(PSIc[i_c])
    ax.plot([cx, Xc[i_c]], [cy, Yc[i_c]], 'k--', lw=0.9, alpha=0.55)
    ax.plot([cx], [cy], marker='+', color='k', ms=10)
    ax.text(0.5 * (cx + Xc[i_c]) - 2.0, 0.5 * (cy + Yc[i_c]) + 0.35,
            'R≈%.1f m' % R_circ, fontsize=10)
    ax.plot([Xc[0]], [Yc[0]], 'x', color='#8250df', ms=9, mew=2.2)
    ax.text(Xc[0] - 2.8, Yc[0] - 1.9, '初始扰动点', color='#8250df', fontsize=9.5)

    ax.text(-12.4, 11.2, '开环：3 s 内甩尾', color=C_RED, fontsize=9.5, ha='left')

    ax.set_xlabel('世界坐标 X / m'); ax.set_ylabel('世界坐标 Y / m')
    ax.legend(loc='lower left', fontsize=8.8, framealpha=0.92)
    lim = 1.28 * max(np.nanmax(np.abs(Xc)), np.nanmax(np.abs(Yc)))
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)

    # 侧偏角示意插图
    axins = ax.inset_axes([0.60, 0.06, 0.37, 0.32])
    axins.set_aspect('equal')
    scale = 0.50
    car = np.array([[-4.2 * scale / 2, -1.85 * scale / 2],
                    [4.2 * scale / 2, -1.85 * scale / 2],
                    [4.2 * scale / 2, 1.85 * scale / 2],
                    [-4.2 * scale / 2, 1.85 * scale / 2]])
    axins.add_patch(plt.Polygon(car, closed=True, facecolor=C_CAR_FACE,
                                edgecolor=C_CAR_EDGE, lw=1.1))
    ang = beta_eq  # rad
    Lv = 2.8
    axins.annotate('', xy=(Lv, 0.0), xytext=(0, 0),
                   arrowprops=dict(arrowstyle='->', color=C_GREY, lw=1.1, ls='--'))
    axins.annotate('', xy=(Lv * np.cos(ang), Lv * np.sin(ang)), xytext=(0, 0),
                   arrowprops=dict(arrowstyle='-|>', color=C_GREEN, lw=2.0))
    axins.text(0.42, 0.62, '航向（车身）', color=C_GREY, fontsize=7.6)
    axins.text(1.55, -2.18, '速度（质心）', color=C_GREEN, fontsize=7.6)
    from matplotlib.patches import Arc
    r_arc = 1.5
    axins.add_patch(Arc((0, 0), 2 * r_arc, 2 * r_arc, theta1=np.degrees(ang), theta2=0.0,
                        color=C_BLUE, lw=1.3))
    axins.text(r_arc * np.cos(0.42 * ang) + 0.30, r_arc * np.sin(0.42 * ang) - 0.28,
               r'$|\beta|$', fontsize=9.0, color=C_BLUE)
    axins.set_xlim(-1.6, 4.0); axins.set_ylim(-2.2, 1.6)
    axins.set_xticks([]); axins.set_yticks([])
    axins.set_title(r'航向与速度夹角 $|\beta|\approx%.0f^\circ$' % abs(np.degrees(ang)),
                    fontsize=8.5)
    for sp in axins.spines.values():
        sp.set_visible(False)
    axins.patch.set_alpha(0.0)

    fig.savefig(os.path.join(out_dir, 'fig12_drift_traj.png'), dpi=300,
                bbox_inches='tight')
    plt.close(fig)

    # ---------- 数据导出 ----------
    np.savez(os.path.join(out_dir, 'drift_traj.npz'),
             t=ts_c, X=Xc, Y=Yc, psi=PSIc, vx=xs_c[:, 0], vy=xs_c[:, 1], r=xs_c[:, 2],
             R=R_circ, beta=beta_eq, delta=delta, V=V)
    print('saved fig12_drift_traj.png, drift_traj.npz')
    print('drift circle R=%.3f m, beta_eq=%.2f deg, r_eq=%.3f' % (R_circ, np.degrees(beta_eq), r_eq))
    print('closed-loop final beta=%.3f deg, r=%.3f' % (bc[-1], xs_c[-1, 2]))




def _gif_car_pts(X, Y, psi, scale=1.0):
    L, W = 4.2 * scale, 1.85 * scale
    pts = np.array([[-L / 2, -W / 2], [L / 2, -W / 2], [L / 2, W / 2], [-L / 2, W / 2]])
    c, s = np.cos(psi), np.sin(psi)
    R = np.array([[c, -s], [s, c]])
    return pts @ R.T + np.array([X, Y])


def make_gif():
    d = np.load(os.path.join(BASE, 'figs', 'drift_traj.npz'))
    t, X, Y, psi = d['t'], d['X'], d['Y'], d['psi']
    vx, vy, r = d['vx'], d['vy'], d['r']
    R_circ, beta = float(d['R']), float(d['beta'])
    V = float(d['V'])
    lim = 1.30 * max(np.nanmax(np.abs(X)), np.nanmax(np.abs(Y)))

    # 选取稳态两圈（约 8.6 s）
    keep = np.isfinite(t) & (t <= 8.6)
    t, X, Y, psi, vx, vy, r = t[keep], X[keep], Y[keep], psi[keep], vx[keep], vy[keep], r[keep]
    step = 25  # 2e-3*25 = 0.05 s → 20 fps
    idx = np.arange(0, len(t), step)

    frames = []
    for k in idx:
        fig, ax = plt.subplots(figsize=(5.2, 5.2), dpi=90)
        ax.set_aspect('equal')
        ax.plot(X, Y, color='#9ec1f5', lw=1.4, alpha=0.8)
        ax.plot(X[:k + 1], Y[:k + 1], color='#1f6feb', lw=2.2)
        ax.plot([0], [0], 'x', color='#8250df', ms=8, mew=2)
        # 车辆
        ax.add_patch(Polygon(_gif_car_pts(X[k], Y[k], psi[k], 0.9), closed=True,
                             facecolor='#cfe2ff', edgecolor='#1f4e9e', lw=1.3, zorder=3))
        # 航向
        ax.annotate('', xy=(X[k] + 1.7 * np.cos(psi[k]), Y[k] + 1.7 * np.sin(psi[k])),
                    xytext=(X[k], Y[k]),
                    arrowprops=dict(arrowstyle='-', color='#57606a', lw=1.1, ls='--'))
        # 速度
        vwx = vx[k] * np.cos(psi[k]) - vy[k] * np.sin(psi[k])
        vwy = vx[k] * np.sin(psi[k]) + vy[k] * np.cos(psi[k])
        ax.annotate('', xy=(X[k] + 0.22 * vwx, Y[k] + 0.22 * vwy), xytext=(X[k], Y[k]),
                    arrowprops=dict(arrowstyle='-|>', color='#2da44e', lw=2.0))
        # 半径指示
        cx = X[k] - R_circ * np.sin(psi[k] + beta)
        cy = Y[k] + R_circ * np.cos(psi[k] + beta)
        ax.plot([cx, X[k]], [cy, Y[k]], color='0.65', lw=0.8, ls=':')
        ax.plot([cx], [cy], '+', color='0.35', ms=9)
        ax.text(-lim * 0.94, lim * 0.86,
                'V=%.0f m/s, δ=0.10 rad\nβ=%.1f°, r=%.2f rad/s' % (V, np.degrees(beta), r[k]),
                fontsize=9.0, va='top',
                bbox=dict(fc='white', ec='0.75', alpha=0.9, lw=0.8))
        ax.text(-lim * 0.94, -lim * 0.90, 't = %.1f s    闭环漂移（LQR）' % t[k], fontsize=10)
        ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
        ax.set_xlabel('X / m'); ax.set_ylabel('Y / m')
        ax.set_title('漂移轨迹：车身相对速度方向偏转 |β|≈%.0f°' % abs(np.degrees(beta)),
                     fontsize=11)
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120)
        plt.close(fig)
        buf.seek(0)
        frames.append(Image.open(buf).convert('P', palette=Image.ADAPTIVE, colors=128))

    out = os.path.join(BASE, 'figs', 'drift_traj.gif')
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=50, loop=0,
                   optimize=True)
    print('saved', out, 'frames', len(frames), 'size', os.path.getsize(out))




if __name__ == '__main__':
    main()
    make_gif()
