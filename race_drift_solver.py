"""
race_drift_solver.py
====================
《赛车稳态漂移平衡点的非线性优化求解》—— 算法实现与数值实验

本文件实现（全部为课程内容的手写实现，不依赖 scipy 作为主算法）：
  1. 线搜索（Armijo 回溯 / 强 Wolfe）与统一的算法记账接口
  2. 六种平衡点求解算法
       A1 阻尼牛顿法（解析雅可比）
       A2 阻尼牛顿法（中心差分雅可比，对照解析雅可比的计算代价）
       A3 Gauss-Newton 最小二乘
       A4 Levenberg-Marquardt（自适应阻尼）
       A5 信赖域 dogleg 法（Gauss-Newton 模型）
       A6 BFGS 拟牛顿法（最小化 1/2||e||^2）
       A7 投影牛顿法（箱约束 / 物理可行域）
  3. 多起点全局搜索（求全部物理可行平衡点）与吸引域统计
  4. 延拓法（自然参数 delta + 切向预测）追踪平衡点支路，det(J) 变号检测折叠分岔，
     并用扩展系统 [e; det J] = 0 精确求解折叠点
  5. (V, delta) 平面解个数分区图（抓地/漂移/无解）
  6. 设计优化：min kappa  s.t. e(x)=0, lb<=x<=ub（增广拉格朗日法 ALM + 投影 BFGS 内层），
     并与"嵌套消元法"交叉验证；输出 KKT 乘子与有效约束
  7. 闭环决策：漂移平衡点线性化 -> LQR（Kleinman 迭代求解 CARE，与 scipy 对照）
     -> 非线性闭环仿真 -> 闭环吸引域

运行：  python race_drift_solver.py            # 完整实验，写 results.json
        python race_drift_solver.py --quick    # 快速冒烟测试
"""
from __future__ import annotations

import json
import os
import sys
import time
import platform
import numpy as np

from race_drift_model import (
    DEFAULT_PARAMS, G, PARAM_META, residual, residual_jac, residual_delta,
    diagnose, vehicle_loads, tire_lateral, phi_unit, default_bounds,
    is_physical, state_from_z, z_from_state,
)

HERE = os.path.dirname(os.path.abspath(__file__))
TOL_RES = 1e-11          # 残差收敛阈值（2-范数）
TOL_STEP = 1e-13
MAXIT = 120


# ---------------------------------------------------------------------------
# 0. 工具
# ---------------------------------------------------------------------------
def _now():
    return time.perf_counter()


def _norm(e):
    return float(np.linalg.norm(e))


def _res_hist(result):
    return [float(v) for v in result['hist_res']]


def _mk(name, z0):
    return dict(name=name, z0=np.asarray(z0, float).copy(), z=None,
                ok=False, it=0, nf=0, nJ=0, hist_res=[], hist_step=[], msg='',
                t=0.0, extra={})


def _done(r, z, it, msg=''):
    r['z'] = np.asarray(z, float)
    r['it'] = it
    r['ok'] = True
    r['msg'] = msg
    return r


def _fail(r, it, msg):
    r['it'] = it
    r['ok'] = False
    r['msg'] = msg
    return r


def merit(z, V, delta, p):
    e = residual(z, V, delta, p)
    return 0.5 * float(np.dot(e, e)), e


def armijo(z, dz, phi0, V, delta, p, r, alpha0=1.0, c1=2e-4, shrink=0.5, maxbt=60):
    """Armijo 回溯线搜索（最小化 phi=1/2||e||^2）。返回 (z_new, phi_new, alpha)。"""
    alpha = alpha0
    for _ in range(maxbt):
        zt = z + alpha * dz
        phi_t, _ = merit(zt, V, delta, p)
        r['nf'] += 1
        if np.isfinite(phi_t) and phi_t <= (1.0 - c1 * alpha) * phi0:
            return zt, phi_t, alpha
        alpha *= shrink
    return None, None, 0.0


# ---------------------------------------------------------------------------
# 1. 六种平衡点求解算法（统一接口）
# ---------------------------------------------------------------------------
def solve_newton(z0, V, delta, p=DEFAULT_PARAMS, tol=TOL_RES, maxit=MAXIT, analytic=True):
    """A1/A2 阻尼牛顿法。analytic=False 时用中心差分雅可比。"""
    r = _mk('newton' if analytic else 'newton_fd', z0)
    t0 = _now()
    z = r['z0'].copy()
    h = 1e-6
    for k in range(maxit):
        e = residual(z, V, delta, p); r['nf'] += 1
        ne = _norm(e); r['hist_res'].append(ne)
        if ne < tol:
            return _done(r, z, k + 1)
        if analytic:
            J = residual_jac(z, V, delta, p); r['nJ'] += 1
        else:
            J = np.zeros((3, 3))
            for j in range(3):
                zp = z.copy(); zm = z.copy(); zp[j] += h; zm[j] -= h
                J[:, j] = (residual(zp, V, delta, p) - residual(zm, V, delta, p)) / (2 * h)
                r['nf'] += 2
        try:
            dz = -np.linalg.solve(J, e)
        except np.linalg.LinAlgError:
            return _fail(r, k + 1, 'singular Jacobian')
        if not np.all(np.isfinite(dz)):
            return _fail(r, k + 1, 'non-finite step')
        phi0 = 0.5 * ne * ne
        zn, phin, alpha = armijo(z, dz, phi0, V, delta, p, r)
        if zn is None:
            return _fail(r, k + 1, 'line search failed')
        stepn = float(np.linalg.norm(alpha * dz))
        r['hist_step'].append(stepn)
        z = zn
        if stepn < TOL_STEP * (1.0 + np.linalg.norm(z)):
            e2 = residual(z, V, delta, p); r['nf'] += 1
            if _norm(e2) < 1e3 * tol:
                r['hist_res'].append(_norm(e2))
                return _done(r, z, k + 1, 'stagnation')
    r['t'] = _now() - t0
    return _fail(r, maxit, 'maxit')


def solve_gn(z0, V, delta, p=DEFAULT_PARAMS, tol=TOL_RES, maxit=MAXIT):
    """A3 Gauss-Newton（最小化 1/2||e||^2）。"""
    r = _mk('gauss_newton', z0); t0 = _now()
    z = r['z0'].copy()
    for k in range(maxit):
        e = residual(z, V, delta, p); r['nf'] += 1
        ne = _norm(e); r['hist_res'].append(ne)
        if ne < tol:
            return _done(r, z, k + 1)
        J = residual_jac(z, V, delta, p); r['nJ'] += 1
        g = J.T @ e
        B = J.T @ J
        try:
            dz = -np.linalg.solve(B + 1e-12 * np.eye(3), g)
        except np.linalg.LinAlgError:
            return _fail(r, k + 1, 'singular normal eq')
        phi0 = 0.5 * ne * ne
        zn, phin, alpha = armijo(z, dz, phi0, V, delta, p, r)
        if zn is None:
            return _fail(r, k + 1, 'line search failed')
        r['hist_step'].append(float(np.linalg.norm(alpha * dz)))
        z = zn
    r['t'] = _now() - t0
    return _fail(r, maxit, 'maxit')


def solve_lm(z0, V, delta, p=DEFAULT_PARAMS, tol=TOL_RES, maxit=MAXIT, lam0=1e-2):
    """A4 Levenberg-Marquardt（Nielsen 阻尼更新）。"""
    r = _mk('levenberg_marquardt', z0); t0 = _now()
    z = r['z0'].copy(); lam = lam0
    e = residual(z, V, delta, p); r['nf'] += 1
    ne = _norm(e); r['hist_res'].append(ne); phi = 0.5 * ne * ne
    if ne < tol:
        return _done(r, z, 1)
    J = residual_jac(z, V, delta, p); r['nJ'] += 1
    B = J.T @ J; g = J.T @ e
    for k in range(1, maxit + 1):
        accepted = False
        for _ in range(40):
            try:
                dz = -np.linalg.solve(B + lam * np.eye(3), g)
            except np.linalg.LinAlgError:
                return _fail(r, k, 'singular')
            pred = -(np.dot(g, dz) + 0.5 * np.dot(dz, B @ dz))
            zt = z + dz
            pt, et = merit(zt, V, delta, p); r['nf'] += 1
            if not np.isfinite(pt):
                lam *= 4.0
                continue
            rho = (phi - pt) / pred if pred > 0 else -1.0
            if rho > 0.0:
                accepted = True
                break
            lam *= 4.0
            if lam > 1e12:
                return _fail(r, k, 'damping explosion')
        if not accepted:
            return _fail(r, k, 'no acceptable step')
        r['extra']['lambda'] = r['extra'].get('lambda', []) + [float(lam)]
        nu = 2.0
        lam = lam * max(1.0 / 3.0, 1.0 - (2.0 * rho - 1.0) ** 3)
        lam = max(lam, 1e-14)
        z = zt; phi = pt; e = et; ne = _norm(e)
        r['hist_res'].append(ne); r['hist_step'].append(float(_norm(dz)))
        if ne < tol:
            return _done(r, z, k)
        J = residual_jac(z, V, delta, p); r['nJ'] += 1
        B = J.T @ J; g = J.T @ e
    r['t'] = _now() - t0
    return _fail(r, maxit, 'maxit')


def solve_dogleg(z0, V, delta, p=DEFAULT_PARAMS, tol=TOL_RES, maxit=MAXIT, delta0=1.0):
    """A5 信赖域 dogleg 法（模型 m(p)=phi+g'p+1/2 p'Bp，B=J'J）。"""
    r = _mk('trust_region_dogleg', z0); t0 = _now()
    z = r['z0'].copy(); rad = float(delta0)
    e = residual(z, V, delta, p); r['nf'] += 1
    ne = _norm(e); r['hist_res'].append(ne); phi = 0.5 * ne * ne
    if ne < tol:
        return _done(r, z, 1)
    J = residual_jac(z, V, delta, p); r['nJ'] += 1
    B = J.T @ J; g = J.T @ e
    for k in range(1, maxit + 1):
        try:
            p_gn = -np.linalg.solve(B + 1e-14 * np.eye(3), g)
        except np.linalg.LinAlgError:
            return _fail(r, k, 'singular')
        gBg = float(g @ B @ g)
        if gBg <= 1e-300:
            return _fail(r, k, 'flat model')
        alpha_sd = float(g @ g) / gBg
        p_sd = -alpha_sd * g
        ngn = _norm(p_gn); nsd = _norm(p_sd)
        if ngn <= rad:
            st = p_gn
        elif nsd >= rad:
            st = p_sd * (rad / nsd)
        else:
            # 沿 sd -> gn 的 dogleg 路径
            d = p_gn - p_sd
            a_ = float(d @ d)
            b_ = 2.0 * float(p_sd @ d)
            c_ = float(p_sd @ p_sd) - rad * rad
            tau = (-b_ + np.sqrt(max(b_ * b_ - 4 * a_ * c_, 0.0))) / (2 * a_)
            st = p_sd + tau * d
        pred = -(float(g @ st) + 0.5 * float(st @ B @ st))
        if pred <= 0:
            st = p_sd * (rad / max(nsd, 1e-300)); pred = -(float(g @ st) + 0.5 * float(st @ B @ st))
        zt = z + st
        pt, et = merit(zt, V, delta, p); r['nf'] += 1
        if np.isfinite(pt) and pred > 0:
            rho = (phi - pt) / pred
        else:
            rho = -1.0
        if rho < 0.25:
            rad *= 0.25
        elif rho > 0.75 and _norm(st) >= 0.99 * rad:
            rad *= 2.0
        r['extra']['radius'] = r['extra'].get('radius', []) + [float(rad)]
        if rho > 0.0:
            z = zt; phi = pt; e = et; ne = _norm(e)
            r['hist_res'].append(ne); r['hist_step'].append(float(_norm(st)))
            if ne < tol:
                return _done(r, z, k)
            J = residual_jac(z, V, delta, p); r['nJ'] += 1
            B = J.T @ J; g = J.T @ e
        if rad < 1e-14:
            return _fail(r, k, 'trust region collapse')
    r['t'] = _now() - t0
    return _fail(r, maxit, 'maxit')


def _wolfe_ls(z, dz, phi0, g0, V, delta, p, r, c1=1e-4, c2=0.9, maxit=40):
    """强 Wolfe 线搜索（BFGS 用）：返回 (alpha, z_new, phi_new, g_new)。"""
    alpha = 1.0
    alpha_prev = 0.0
    phi_prev = phi0
    for _ in range(maxit):
        zt = z + alpha * dz
        pt, et = merit(zt, V, delta, p); r['nf'] += 1
        if not np.isfinite(pt) or pt > phi0 + c1 * alpha * float(g0 @ dz):
            alpha = 0.5 * (alpha_prev + alpha)
            if abs(alpha - alpha_prev) < 1e-16:
                break
            continue
        gt = residual_jac(zt, V, delta, p).T @ et; r['nJ'] += 1
        if float(gt @ dz) >= c2 * float(g0 @ dz):
            return alpha, zt, pt, gt
        alpha_prev = alpha
        phi_prev = pt
        alpha = min(alpha * 2.0, 1e3)
    # 退化为取满足 Armijo 的最小 alpha
    return alpha, z + alpha * dz, merit(z + alpha * dz, V, delta, p)[0], None


def solve_bfgs(z0, V, delta, p=DEFAULT_PARAMS, tol=TOL_RES, maxit=MAXIT):
    """A6 BFGS 拟牛顿法（最小化 1/2||e||^2，强 Wolfe 线搜索）。"""
    r = _mk('bfgs', z0); t0 = _now()
    z = r['z0'].copy()
    e = residual(z, V, delta, p); r['nf'] += 1
    ne = _norm(e); r['hist_res'].append(ne); phi = 0.5 * ne * ne
    if ne < tol:
        return _done(r, z, 1)
    J = residual_jac(z, V, delta, p); r['nJ'] += 1
    g = J.T @ e
    H = np.eye(3)
    for k in range(1, maxit + 1):
        dz = -H @ g
        if float(g @ dz) >= 0:
            H = np.eye(3); dz = -g
        alpha, zt, pt, gt = _wolfe_ls(z, dz, phi, g, V, delta, p, r)
        s = zt - z
        if gt is None:
            gt = residual_jac(zt, V, delta, p).T @ residual(zt, V, delta, p)
            r['nJ'] += 1; r['nf'] += 1
        y = gt - g
        sy = float(s @ y)
        if sy > 1e-12 * max(1.0, _norm(s) * _norm(y)):
            rho = 1.0 / sy
            I = np.eye(3)
            H = (I - rho * np.outer(s, y)) @ H @ (I - rho * np.outer(y, s)) + rho * np.outer(s, s)
        z = zt; phi = pt; g = gt
        e2 = residual(z, V, delta, p); r['nf'] += 1
        ne = _norm(e2); r['hist_res'].append(ne); r['hist_step'].append(float(_norm(s)))
        if ne < tol:
            return _done(r, z, k + 1)
    r['t'] = _now() - t0
    return _fail(r, maxit, 'maxit')


def solve_projected_newton(z0, V, delta, p=DEFAULT_PARAMS, tol=TOL_RES, maxit=MAXIT,
                           lo=None, hi=None):
    """A7 投影牛顿法（箱约束）。解在箱内部时退化为阻尼牛顿；越界分量被截断。"""
    r = _mk('projected_newton', z0); t0 = _now()
    if lo is None or hi is None:
        lo, hi = default_bounds(p)
    z = np.clip(r['z0'].copy(), lo, hi)
    for k in range(maxit):
        e = residual(z, V, delta, p); r['nf'] += 1
        ne = _norm(e); r['hist_res'].append(ne)
        if ne < tol:
            return _done(r, z, k + 1)
        J = residual_jac(z, V, delta, p); r['nJ'] += 1
        # 投影牛顿方向：先按自由变量求牛顿步，再整体投影
        dz = -np.linalg.solve(J, e)
        # 若某个分量在边界且方向指向界外，则冻结该分量
        at_lo = (z <= lo + 1e-12); at_hi = (z >= hi - 1e-12)
        frozen = ((at_lo & (dz < 0)) | (at_hi & (dz > 0)))
        if np.any(frozen):
            idx = np.where(~frozen)[0]
            if idx.size == 0:
                return _fail(r, k + 1, 'all variables frozen')
            Jf = J[:, idx]
            # 固定分量时用最小二乘求自由分量修正
            rhs = -(e - J[:, frozen] @ np.zeros(int(frozen.sum())))
            try:
                dz[idx] = np.linalg.lstsq(Jf, rhs, rcond=None)[0]
            except np.linalg.LinAlgError:
                pass
            dz[frozen] = 0.0
        phi0 = 0.5 * ne * ne
        # 沿投影路径做 Armijo
        alpha = 1.0
        ok = False
        for _ in range(60):
            zt = np.clip(z + alpha * dz, lo, hi)
            pt, _ = merit(zt, V, delta, p); r['nf'] += 1
            if np.isfinite(pt) and pt <= (1.0 - 2e-4 * alpha) * phi0:
                ok = True
                break
            alpha *= 0.5
        if not ok:
            return _fail(r, k + 1, 'line search failed')
        stepn = float(_norm(alpha * dz))
        r['hist_step'].append(stepn)
        z = zt
        if stepn < TOL_STEP * (1.0 + _norm(z)):
            e2 = residual(z, V, delta, p); r['nf'] += 1
            if _norm(e2) < 1e3 * tol:
                return _done(r, z, k + 1, 'stagnation')
    r['t'] = _now() - t0
    return _fail(r, maxit, 'maxit')


ALGORITHMS = {
    'A1_newton_analytic': lambda z0, V, d, p, **kw: solve_newton(z0, V, d, p, analytic=True, **kw),
    'A2_newton_fd': lambda z0, V, d, p, **kw: solve_newton(z0, V, d, p, analytic=False, **kw),
    'A3_gauss_newton': lambda z0, V, d, p, **kw: solve_gn(z0, V, d, p, **kw),
    'A4_levenberg_marquardt': lambda z0, V, d, p, **kw: solve_lm(z0, V, d, p, **kw),
    'A5_trust_region_dogleg': lambda z0, V, d, p, **kw: solve_dogleg(z0, V, d, p, **kw),
    'A6_bfgs': lambda z0, V, d, p, **kw: solve_bfgs(z0, V, d, p, **kw),
    'A7_projected_newton': lambda z0, V, d, p, **kw: solve_projected_newton(z0, V, d, p, **kw),
}


# ---------------------------------------------------------------------------
# 2. 多起点搜索与解的分类
# ---------------------------------------------------------------------------
def classify(z, V, delta, p=DEFAULT_PARAMS):
    """把物理可行平衡点分类：grip（|beta|<8°）/ drift（beta<=-8°）/ other。"""
    if not is_physical(z, V, delta, p):
        return 'none'
    bd = np.degrees(z[0])
    if abs(bd) < 8.0:
        return 'grip'
    if bd <= -8.0:
        return 'drift'
    return 'other'


def multistart(V, delta, p=DEFAULT_PARAMS, n_start=300, seed=0, algo='A1_newton_analytic',
               tol=TOL_RES, extra_starts=()):
    """随机多起点求解，返回按类型去重后的解列表（含诊断）与统计。"""
    rng = np.random.default_rng(seed)
    lo, hi = default_bounds(p)
    starts = [np.array([0.0, 0.0, 0.0]),
              np.array([0.05, 0.2, 200.0]),
              np.array([-0.35, 1.2, 7000.0])]
    starts += [np.asarray(s, float) for s in extra_starts]
    starts += [np.array([rng.uniform(-0.8, 0.35), rng.uniform(-1.0, 3.0),
                         rng.uniform(-500.0, 11000.0)]) for _ in range(n_start)]
    solver = ALGORITHMS[algo]
    found = []
    n_ok = 0
    its = []
    for z0 in starts:
        r = solver(z0, V, delta, p, tol=tol)
        if r['ok']:
            n_ok += 1
            its.append(r['it'])
            z = r['z']
            if not any(_norm(z - q) < 1e-5 * (1 + _norm(q)) for q in found):
                found.append(z)
    sols = []
    for z in found:
        typ = classify(z, V, delta, p)
        if typ == 'none':
            continue
        dg = diagnose(z, V, delta, p)
        sols.append(dict(type=typ, z=[float(v) for v in z],
                         beta_deg=float(dg['beta_deg']), r=float(dg['r']),
                         fx=float(dg['fx']), kappa=float(dg['fx_frac']),
                         max_real=float(dg['max_real']), stable=bool(dg['is_stable']),
                         detJ=float(dg['detJ']), condJ=float(dg['condJ']),
                         eig=[[float(a), float(b)] for a, b in zip(dg['eig_real'], dg['eig_imag'])]))
    sols.sort(key=lambda s: s['beta_deg'])
    return sols, dict(n_start=len(starts), n_ok=n_ok, mean_it=float(np.mean(its)) if its else 0.0)


def get_reference_solutions(V, delta, p=DEFAULT_PARAMS, seed=0):
    """返回 dict: grip / drift 的参考解（多起点 + 物理筛选）。"""
    sols, _ = multistart(V, delta, p=p, n_start=250, seed=seed)
    out = {}
    for s in sols:
        if s['type'] in ('grip', 'drift') and s['type'] not in out:
            out[s['type']] = s
    return out


# ---------------------------------------------------------------------------
# 3. 延拓法：平衡点支路 + 折叠分岔
# ---------------------------------------------------------------------------
def newton_fixed(z0, V, delta, p=DEFAULT_PARAMS, tol=1e-12, maxit=60):
    r = solve_newton(z0, V, delta, p, tol=tol, maxit=maxit)
    return (r['z'], r['it']) if r['ok'] else (None, r['it'])


def trace_branch(V, delta0, z0, dstep, nsteps, direction=+1, p=DEFAULT_PARAMS,
                 tol=1e-11, maxit=40, dmin=-1e9, dmax=1e9, dstep_min=2e-5,
                 jump_guard=4.0):
    """自然延拓：以 delta 为参数追踪平衡点支路（切向预测 + 牛顿校正 + 自适应步长）。

    - 起点先做一次牛顿校正；
    - 每步用切向预测 dz/ddelta = -J^{-1} de/ddelta，牛顿校正失败则步长折半重试；
    - 步长降到 dstep_min 以下仍无法校正，或相邻两点 detJ 变号，判定为折叠（鞍结）点；
    - points 元素：dict(delta, z, detJ, detJ_scaled, condJ, max_real, stable)
    返回 (points, why)。
    """
    points = []
    z = np.asarray(z0, float)
    d = float(delta0)
    zc, _ = newton_fixed(z, V, d, p, tol=tol, maxit=80)
    if zc is None:
        return points, 'seed failed'
    z = zc
    step = float(dstep)

    def _record(zz, dd):
        J = residual_jac(zz, V, dd, p)
        detJ = float(np.linalg.det(J))
        sna = np.linalg.norm(J)
        dg = diagnose(zz, V, dd, p)
        return dict(delta=float(dd), z=np.array(zz, float), detJ=detJ,
                    detJ_scaled=detJ / max(sna ** 3, 1e-300),
                    condJ=float(dg['condJ']), max_real=float(dg['max_real']),
                    stable=bool(dg['is_stable']))

    points.append(_record(z, d))
    for _ in range(nsteps):
        J = residual_jac(z, V, d, p)
        ed = residual_delta(z, V, d, p)
        try:
            tan = -np.linalg.solve(J, ed)
        except np.linalg.LinAlgError:
            return points, 'singular J at delta=%.6f' % d
        accepted = False
        while step >= dstep_min:
            dn = d + direction * step
            if dn < dmin or dn > dmax:
                return points, 'delta bound at %.5f' % d
            zp = z + tan * (dn - d)
            zn, _ = newton_fixed(zp, V, dn, p, tol=tol, maxit=maxit)
            if zn is not None:
                jump = np.linalg.norm(zn - zp)
                if jump <= jump_guard * (abs(dn - d) * np.linalg.norm(tan) + 1e-6):
                    accepted = True
                    break
            step *= 0.5
        if not accepted:
            return points, 'fold: step<%.1e at delta=%.6f' % (dstep_min, d)
        d = dn
        z = zn
        rec = _record(z, d)
        if points[-1]['detJ'] * rec['detJ'] < 0:
            points.append(rec)
            return points, 'fold: detJ sign change near delta=%.6f' % d
        points.append(rec)
    return points, 'max steps'


def trace_fold(V, z_seed, delta_seed, p=DEFAULT_PARAMS, dmax=1.2, direction=+1,
               dstep_min=2e-5):
    """从种子出发延拓到折叠点，返回折叠点位置、Jacobian 行列式与稳定性指标。"""
    pts, why = trace_branch(V, delta_seed, z_seed, 0.002, 4000, direction, p=p,
                            dmin=0.0 if direction < 0 else -1e9,
                            dmax=dmax if direction > 0 else 1e9,
                            dstep_min=dstep_min)
    if not pts:
        return dict(ok=False, why=why, n=0)
    cross = None
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        if a['detJ'] * b['detJ'] < 0:
            w = a['detJ'] / (a['detJ'] - b['detJ'])
            cross = dict(delta=float(a['delta'] + w * (b['delta'] - a['delta'])))
            break
    last = pts[-1]
    return dict(ok=True, why=why, delta=float(last['delta']),
                z=[float(v) for v in last['z']], detJ=float(last['detJ']),
                detJ_scaled=float(last['detJ_scaled']), max_real=float(last['max_real']),
                condJ=float(last['condJ']), n=int(len(pts)), cross=cross,
                trace_delta=[float(q['delta']) for q in pts[::max(1, len(pts) // 120)]],
                trace_detJ=[float(q['detJ']) for q in pts[::max(1, len(pts) // 120)]],
                trace_maxreal=[float(q['max_real']) for q in pts[::max(1, len(pts) // 120)]])


def _detJ_scaled(z, V, delta, p):
    J = residual_jac(z, V, delta, p)
    s = np.linalg.norm(J)
    return np.linalg.det(J) / max(s ** 3, 1e-300)


def trace_arclen(V, z0, delta0, p=DEFAULT_PARAMS, ds=0.05, nsteps=400,
                 tol=1e-11, maxit=40, dmin=-1e9, dmax=1e9,
                 scale=(0.30, 1.0, 5000.0, 0.30)):
    """伪弧长（pseudo-arclength）延拓：把 (mu,delta) 作为一条曲线，用弧长 s 参数化。

    状态向量先做尺度变换 u = (beta/0.30, r/1.0, fx/5000, delta/0.30)，
    使各分量量级相近，弧长有物理意义且数值条件更好。切向 t 由 [J, de/ddelta] 的零空间
    给出（SVD 取最小右奇异向量），校正步求解扩展系统 [e(z,delta); t_old·(u-u_pred)] = 0。
    由于 delta 不再充当参数，延拓可以自然通过 delta'=0 的折叠（鞍结点）而转入另一叶，
    这正是在自然参数化（trace_branch）下 ddelta/ds -> 0、步长塌缩的工况。
    返回点列表（含每点 detJ、scaled、max_real、稳定标记与切向 ddelta/ds）与折叠点列表。
    """
    sc = np.asarray(scale, float)
    u = np.array([z0[0] / sc[0], z0[1] / sc[1], z0[2] / sc[2], float(delta0) / sc[3]])

    def _F(u):
        w = u * sc
        return residual(w[:3], V, w[3], p)

    def _A(u):
        w = u * sc
        return np.hstack([residual_jac(w[:3], V, w[3], p),
                          residual_delta(w[:3], V, w[3], p).reshape(3, 1)]) * sc.reshape(1, 4)

    def _tangent(u, t_prev):
        A = _A(u)
        try:
            s = np.linalg.svd(A, compute_uv=True)
            t = s[2][-1]
        except np.linalg.LinAlgError:
            return None
        t = t / max(np.linalg.norm(t), 1e-300)
        if t_prev is not None and float(np.dot(t, t_prev)) < 0:
            t = -t
        return t

    def _point(u):
        w = u * sc
        dg = diagnose(w[:3], V, w[3], p)
        return dict(delta=float(w[3]), z=[float(v) for v in w[:3]],
                    detJ=float(dg['detJ']), detJ_scaled=float(_detJ_scaled(w[:3], V, w[3], p)),
                    condJ=float(dg['condJ']), max_real=float(dg['max_real']),
                    stable=bool(dg['is_stable']), tangent_delta=float(0.0),
                    beta_deg=float(dg['beta_deg']), r=float(dg['r']), fx=float(dg['fx']))

    t = _tangent(u, None)
    if t is None:
        return dict(ok=False, pts=[], folds=[], n=0, why='no tangent')
    pts = [_point(u)]
    reason = 'nsteps'
    for k in range(nsteps):
        u_pred = u + ds * t
        ut = u_pred.copy()
        ok = False
        for it in range(maxit):
            e = _F(ut)
            ext = np.array([e[0], e[1], e[2], float(np.dot(t, ut - u_pred))])
            if _norm(ext) < tol:
                ok = True
                break
            A = _A(ut)
            M = np.zeros((4, 4))
            M[:3, :] = A
            M[3, :] = t
            try:
                du = -np.linalg.solve(M, ext)
            except np.linalg.LinAlgError:
                break
            ut = ut + du
        if not ok:
            reason = 'correct_fail'
            break
        w = ut * sc
        if w[3] < dmin - 1e-9 or w[3] > dmax + 1e-9:
            reason = 'delta_bound'
            break
        t_new = _tangent(ut, t)
        if t_new is None:
            reason = 'tangent_fail'
            break
        u = ut
        t = t_new
        q = _point(u)
        q['tangent_delta'] = float(t[3] / sc[3])
        pts.append(q)
    folds = []
    for i2 in range(1, len(pts)):
        ta, tb = pts[i2 - 1]['tangent_delta'], pts[i2]['tangent_delta']
        if ta * tb < 0:
            wgt = ta / (ta - tb)
            folds.append(dict(index=i2,
                              delta=float(pts[i2 - 1]['delta'] + wgt * (pts[i2]['delta'] - pts[i2 - 1]['delta'])),
                              detJ_scaled=float(pts[i2 - 1]['detJ_scaled'] * (1 - wgt) + wgt * pts[i2]['detJ_scaled']),
                              max_real=float(pts[i2 - 1]['max_real'] * (1 - wgt) + wgt * pts[i2]['max_real'])))
    return dict(ok=True, pts=pts, folds=folds, reason=reason, n=len(pts))


def fold_point(V, z_guess, delta_guess, p=DEFAULT_PARAMS, tol=1e-11, maxit=60):
    """折叠（鞍结）点：解扩展系统 F(w) = [e(z,delta); detJ/||J||^3] = 0，w=(beta,r,fx,delta)。

    第 4 个方程要求平衡方程的雅可比 J=de/dz 奇异。扩展系统的雅可比按解析方式组装：
        d(detJ)/dw_j = detJ * tr(J^{-1} dJ/dw_j),
    其中 dJ/dw_j 由解析雅可比中心差分得到，因此 Newton 迭代保持二次收敛。
    """
    w = np.array([z_guess[0], z_guess[1], z_guess[2], delta_guess], float)

    def _parts(w):
        z = w[:3]; d = w[3]
        J = residual_jac(z, V, d, p)
        detJ = float(np.linalg.det(J))
        sn = max(float(np.linalg.norm(J)), 1e-300)
        return z, d, J, detJ, sn

    def F(w):
        z, d, J, detJ, sn = _parts(w)
        e = residual(z, V, d, p)
        return np.array([e[0], e[1], e[2], detJ / sn ** 3])

    def Fjac(w):
        z, d, J, detJ, sn = _parts(w)
        A = np.zeros((4, 4))
        A[:3, :3] = J
        A[:3, 3] = residual_delta(z, V, d, p)
        try:
            Jinv = np.linalg.inv(J)
        except np.linalg.LinAlgError:
            return None
        h = 1e-6 * (1.0 + np.abs(w))
        for jj in range(4):
            wp = w.copy(); wm = w.copy()
            wp[jj] += h[jj]; wm[jj] -= h[jj]
            dJ = (residual_jac(wp[:3], V, wp[3], p) - residual_jac(wm[:3], V, wm[3], p)) / (2 * h[jj])
            ddet = detJ * float(np.trace(Jinv @ dJ))
            dsn = float(np.sum(J * dJ)) / sn
            A[3, jj] = ddet / sn ** 3 - 3.0 * detJ * dsn / sn ** 4
        return A

    hist = []
    nf = _norm(F(w))
    hist.append(float(nf))
    for k in range(maxit):
        if nf < tol:
            return dict(ok=True, it=k, w=w.copy(), res=nf, hist=hist)
        A = Fjac(w)
        if A is None:
            return dict(ok=False, it=k, w=w.copy(), res=nf, msg='singular J', hist=hist)
        try:
            dw = -np.linalg.solve(A, F(w))
        except np.linalg.LinAlgError:
            return dict(ok=False, it=k, w=w.copy(), res=nf, msg='singular ext J', hist=hist)
        alpha = 1.0
        improved = False
        while alpha > 1e-12:
            wt = w + alpha * dw
            ft = _norm(F(wt))
            if np.isfinite(ft) and ft < (1 - 1e-4 * alpha) * nf:
                w = wt; nf = ft; improved = True
                break
            alpha *= 0.5
        hist.append(float(nf))
        if not improved:
            return dict(ok=False, it=k + 1, w=w.copy(), res=nf, msg='line search', hist=hist)
    return dict(ok=False, it=maxit, w=w.copy(), res=_norm(F(w)), msg='maxit', hist=hist)


# ---------------------------------------------------------------------------
# 4. 设计优化：增广拉格朗日法（等式约束+箱约束）
# ---------------------------------------------------------------------------
def projected_bfgs(fun, grad_fun, x0, lo, hi, maxit=120, tol=1e-7, m_mem=10):
    """带箱约束的投影 L-BFGS（内层子问题求解器）。fun/grad_fun 返回标量/梯度。"""
    x = np.clip(np.asarray(x0, float), lo, hi)
    f = fun(x)
    g = grad_fun(x)
    S, Y = [], []
    hist = [float(f)]
    for k in range(maxit):
        # 投影梯度
        x_new_proj = np.clip(x - g, lo, hi)
        pg = x - x_new_proj   # 投影梯度（0 表示 KKT 满足）
        if _norm(pg) < tol:
            break
        # 两循环递推求 H*g
        q = g.copy(); alphas = []
        for s, y in zip(reversed(S), reversed(Y)):
            rho = 1.0 / max(float(s @ y), 1e-300)
            a = rho * float(s @ q)
            q = q - a * y
            alphas.append(a)
        r = 1.0 / max(float(S[-1] @ Y[-1]), 1e-300) * q if S else q
        for (s, y), a in zip(zip(S, Y), reversed(alphas)):
            rho = 1.0 / max(float(s @ y), 1e-300)
            b = rho * float(y @ r)
            r = r + s * (a - b)
        p = -r
        # 投影方向并确保下降
        if float(g @ p) >= 0 or not np.all(np.isfinite(p)):
            p = -g
        # Armijo（沿投影路径）
        alpha = 1.0
        accepted = False
        for _ in range(40):
            xt = np.clip(x + alpha * p, lo, hi)
            ft = fun(xt)
            if np.isfinite(ft) and ft <= f + 1e-4 * alpha * float(g @ (xt - x)):
                accepted = True
                break
            alpha *= 0.5
        if not accepted:
            xt = np.clip(x - 1e-3 * g, lo, hi)
            ft = fun(xt)
            if not np.isfinite(ft) or ft > f:
                break
        s = xt - x; x_new = xt; f_new = ft
        g_new = grad_fun(x_new)
        sy = float(s @ (g_new - g))
        if sy > 1e-10 * _norm(s) * _norm(g_new - g) and len(S) >= m_mem:
            S.pop(0); Y.pop(0)
        if sy > 1e-10 * _norm(s) * _norm(g_new - g):
            S.append(s); Y.append(g_new - g)
        x, f, g = x_new, f_new, g_new
        hist.append(float(f))
    return dict(x=x, f=f, g=g, it=k + 1, hist=hist)


def design_state(xdes, p0=DEFAULT_PARAMS):
    """设计变量 xdes=(a, mu_r, ClA_r) -> 参数字典（b=L-a）。"""
    a, mu_r, cla_r = xdes
    p = dict(p0)
    p['a'] = float(a); p['b'] = float(p0['L'] - a); p['mu_r'] = float(mu_r)
    p['ClA_r'] = float(cla_r)
    return p


def design_objective(z, V, delta, xdes, p0=DEFAULT_PARAMS):
    """目标：漂移平衡点所需的驱动比 kappa = fx / (mu_r Fzr)。"""
    p = design_state(xdes, p0)
    Fzf, Fzr = vehicle_loads(V, -z[1] * V * np.sin(z[0]), p)
    return float(abs(z[2]) / (p['mu_r'] * Fzr))


def design_ay_grip(xdes, p0=DEFAULT_PARAMS, V_ref=40.0):
    """抓地工况下可达到的侧向加速度上限 [m/s^2]（前后轴侧向力之和除以质量）。

    只与设计变量有关、不依赖平衡点，因此可作为设计优化的约束函数。
    """
    p = design_state(xdes, p0)
    Fzf, Fzr = vehicle_loads(V_ref, 0.0, p)
    return float((p['mu_f'] * Fzf + p['mu_r'] * Fzr) / p['m'])


def design_derivs(xdes, V, delta, z_ref, p0=DEFAULT_PARAMS):
    """给定设计变量，解出漂移平衡点并用隐函数定理给出目标/约束的降维梯度。

    平衡方程 e(z; x) = 0 中 z=(beta,r,fx) 由 x=(a,mu_r,ClA_r) 决定，
        J_z = de/dz,  dz/dx = -J_z^{-1} de/dx,
        d kappa/dx = d kappa/dx|_z + (d kappa/dz) (dz/dx)。
    内层求解失败返回 None。该函数是"消元 + 隐函数定理"实现的核心。
    """
    xdes = np.asarray(xdes, float)
    p = design_state(xdes, p0)
    z, it = newton_fixed(z_ref, V, delta, p, tol=1e-13, maxit=120)
    if z is None:
        return None
    J = residual_jac(z, V, delta, p)
    try:
        Jinv = np.linalg.inv(J)
    except np.linalg.LinAlgError:
        return None
    # de/dx 与 dz/dx
    dedx = np.zeros((3, 3))
    for jj in range(3):
        h = 1e-6 * (1.0 + abs(xdes[jj]))
        xp = xdes.copy(); xm = xdes.copy()
        xp[jj] += h; xm[jj] -= h
        dedx[:, jj] = (residual(z, V, delta, design_state(xp, p0)) -
                       residual(z, V, delta, design_state(xm, p0))) / (2 * h)
    dzdx = -Jinv @ dedx
    # kappa 对 z、对 x 的偏导（中心差分）
    gz = np.zeros(3)
    for ii in range(3):
        h = 1e-6 * (1.0 + abs(z[ii]))
        zp = z.copy(); zm = z.copy()
        zp[ii] += h; zm[ii] -= h
        gz[ii] = (design_objective(zp, V, delta, xdes, p0) -
                  design_objective(zm, V, delta, xdes, p0)) / (2 * h)
    gx = np.zeros(3)
    for jj in range(3):
        h = 1e-6 * (1.0 + abs(xdes[jj]))
        xp = xdes.copy(); xm = xdes.copy()
        xp[jj] += h; xm[jj] -= h
        gx[jj] = (design_objective(z, V, delta, xp, p0) -
                  design_objective(z, V, delta, xm, p0)) / (2 * h)
    g_kappa = gz @ dzdx + gx
    # 约束 ay_grip 及其梯度
    ay = design_ay_grip(xdes, p0)
    g_ay = np.zeros(3)
    for jj in range(3):
        h = 1e-6 * (1.0 + abs(xdes[jj]))
        xp = xdes.copy(); xm = xdes.copy()
        xp[jj] += h; xm[jj] -= h
        g_ay[jj] = (design_ay_grip(xp, p0) - design_ay_grip(xm, p0)) / (2 * h)
    return dict(x=xdes, z=z, p=p, it=int(it), kappa=float(design_objective(z, V, delta, xdes, p0)),
                grad_kappa=g_kappa, ay=float(ay), grad_ay=g_ay, dzdx=dzdx,
                detJ=float(np.linalg.det(J)),
                eq_norm=float(_norm(residual(z, V, delta, p))))


def design_alm(V, delta, z_ref, p0=DEFAULT_PARAMS,
               xlo=np.array([1.00, 1.15, 0.20]), xhi=np.array([1.30, 1.55, 1.60]),
               ay_min=None, n_outer=14, mu0=10.0, mu_max=1e8, verbose=False,
               x_init=None):
    """设计优化：min_x kappa(x)  s.t.  ay_grip(x) >= ay_min,  lb <= x <= ub。

    平衡方程 e(z;x)=0 用内层牛顿法求解（消元），目标与约束的梯度用隐函数定理得到，
    于是原问题化为 3 维不等式约束问题；用 Powell-Hestenes-Rockafellar 增广拉格朗日
        L(x; lam, mu) = kappa + [max(0, lam + mu c)^2 - lam^2] / (2 mu),  c = ay_min - ay_grip,
        grad L = grad kappa - max(0, lam + mu c) grad ay_grip,
    内层为带箱约束的投影 L-BFGS，外层更新乘子与罚因子（lag 乘子逐步逼近 KKT 乘子）。
    """
    if ay_min is None:
        ay_min = 1.25 * G
    xlo = np.asarray(xlo, float); xhi = np.asarray(xhi, float)
    x0 = np.array([p0['a'], p0['mu_r'], p0['ClA_r']], float) if x_init is None else np.asarray(x_init, float)
    x = np.clip(x0, xlo, xhi)
    z_ref = np.asarray(z_ref, float)
    lam = 0.0
    mu = float(mu0)
    cache = {}
    hist = []
    n_state = [0]

    def evaluate(xx):
        key = (np.round(xx, 12)).tobytes()
        if key in cache:
            return cache[key]
        # 每次都用同一个参考平衡态热启动：保证解支随设计变量连续变化，不跳支
        d = design_derivs(np.clip(xx, xlo, xhi), V, delta, z_ref, p0)
        if d is None:  # 平衡态在参数扰动下可能收敛失败，换一个热启动再试
            for shift in (np.array([0.04, 0.06, 120.0]), np.array([-0.04, -0.06, -120.0]),
                          np.array([0.10, 0.15, 400.0])):
                d = design_derivs(np.clip(xx, xlo, xhi), V, delta, z_ref + shift, p0)
                if d is not None:
                    break
        n_state[0] += 1
        cache[key] = d
        return d

    for outer in range(n_outer):
        lam_o, mu_o = lam, mu

        def Lfun(xx):
            d = evaluate(xx)
            if d is None:
                return 1e6
            c = ay_min - d['ay']
            t = max(0.0, lam_o + mu_o * c)
            return d['kappa'] + (t * t - lam_o * lam_o) / (2.0 * mu_o)

        def Lgrad(xx):
            d = evaluate(xx)
            if d is None:
                return np.zeros(3)
            c = ay_min - d['ay']
            t = max(0.0, lam_o + mu_o * c)
            return d['grad_kappa'] - t * d['grad_ay']

        res = projected_bfgs(Lfun, Lgrad, x, xlo, xhi, maxit=120, tol=1e-9)
        x = np.array(res['x'], float)
        d = evaluate(x)
        if d is None:
            return dict(ok=False, x=[float(v) for v in x], hist=hist, msg='inner equilibrium failed')
        c = ay_min - d['ay']
        lam_new = max(0.0, lam_o + mu_o * c)
        hist.append(dict(outer=outer + 1, mu=float(mu_o), lam=float(lam_o), lam_new=float(lam_new),
                         kappa=float(d['kappa']), ay=float(d['ay']), c=float(c),
                         L=float(Lfun(x)), inner_it=int(res['it']), inner_hist=[float(v) for v in res['hist'][:60]],
                         x=[float(v) for v in x], n_state=int(n_state[0]),
                         grad_norm=float(_norm(Lgrad(x)))))
        if verbose:
            print('   ALM %2d: kappa=%.6f ay=%.4f c=%+.2e lam=%.3e mu=%.1e it=%d'
                  % (outer + 1, d['kappa'], d['ay'], c, lam_new, mu_o, res['it']))
        lam = lam_new
        viol = max(0.0, c)
        if viol < 1e-9 and lam * viol < 1e-9 and _norm(Lgrad(x)) < 1e-6:
            break
        mu = min(mu * 2.0, mu_max)

    d = evaluate(x)
    c = ay_min - d['ay'] if d is not None else np.nan
    stat = d['grad_kappa'] - lam * d['grad_ay'] if d is not None else np.full(3, np.nan)
    at_lo = x <= xlo + 1e-9
    at_hi = x >= xhi - 1e-9
    free = ~(at_lo | at_hi)
    kkt_free = float(np.max(np.abs(stat[free]))) if np.any(free) else 0.0
    return dict(ok=bool(d is not None and c <= 1e-7),
                x=[float(v) for v in x], design=[float(v) for v in x],
                z=[float(v) for v in (d['z'] if d is not None else np.zeros(3))],
                kappa=float(d['kappa']) if d is not None else np.nan,
                ay=float(d['ay']) if d is not None else np.nan,
                ay_min=float(ay_min), c=float(c), lam=float(lam), mu=float(mu),
                kkt_free=kkt_free, active_low=[int(v) for v in np.where(at_lo)[0]],
                active_high=[int(v) for v in np.where(at_hi)[0]],
                n_state=int(n_state[0]), hist=hist, xlo=[float(v) for v in xlo],
                xhi=[float(v) for v in xhi])


def design_verify(V, delta, z_ref, p0=DEFAULT_PARAMS, h=1e-5):
    """校验：隐函数定理降维梯度 vs 嵌套有限差分梯度（内层牛顿从头求解）。"""
    x = np.array([p0['a'], p0['mu_r'], p0['ClA_r']], float)
    d = design_derivs(x, V, delta, z_ref, p0)
    if d is None:
        return dict(ok=False)
    g_fd = np.zeros(3)
    for jj in range(3):
        xp = x.copy(); xm = x.copy()
        xp[jj] += h; xm[jj] -= h
        vals = []
        for xx in (xp, xm):
            p = design_state(xx, p0)
            z, _ = newton_fixed(np.array(d['z'], float), V, delta, p, tol=1e-13, maxit=120)
            vals.append(np.nan if z is None else design_objective(z, V, delta, xx, p0))
        g_fd[jj] = (vals[0] - vals[1]) / (2 * h)
    denom = np.maximum(np.abs(g_fd), 1e-12)
    rel = np.abs(d['grad_kappa'] - g_fd) / denom
    return dict(ok=True, x=[float(v) for v in x], h=h,
                grad_ift=[float(v) for v in d['grad_kappa']],
                grad_fd=[float(v) for v in g_fd],
                rel_err=[float(v) for v in rel], max_rel=float(np.max(rel)),
                kappa=float(d['kappa']), ay=float(d['ay']))


def design_sweep(V, delta, z_ref, p0=DEFAULT_PARAMS, n=21, cla_r=None):
    """在 (a, mu_r) 平面扫描目标 kappa 与约束 ay_grip，供等值线图与可行域可视化。"""
    if cla_r is None:
        cla_r = p0['ClA_r']
    av = np.linspace(1.02, 1.28, n)
    muv = np.linspace(1.16, 1.52, n)
    K = np.full((n, n), np.nan)
    AY = np.full((n, n), np.nan)
    z_cur = np.array(z_ref, float)
    for i, a in enumerate(av):
        for j, mur in enumerate(muv):
            d = design_derivs(np.array([a, mur, cla_r]), V, delta, z_cur, p0)
            if d is None:
                continue
            z_cur = np.array(d['z'], float)
            K[j, i] = d['kappa']
            AY[j, i] = d['ay']
    return dict(a=[float(v) for v in av], mu_r=[float(v) for v in muv],
                cla_r=float(cla_r), kappa=K.tolist(), ay=AY.tolist())


# ---------------------------------------------------------------------------
# 5. 闭环：线性化 + LQR（Kleinman 迭代）+ 非线性仿真
# ---------------------------------------------------------------------------
def input_jac(x, delta, fx, p=DEFAULT_PARAMS, h=1e-6):
    """B = df/d(delta, fx)（中心差分，两个输入量纲不同故步长分别取）。"""
    from race_drift_model import dynamics
    B = np.zeros((3, 2))
    B[:, 0] = (dynamics(x, delta + h, fx, p) - dynamics(x, delta - h, fx, p)) / (2 * h)
    hf = 1e-2  # fx 量纲 N，步长取 0.01 N
    B[:, 1] = (dynamics(x, delta, fx + hf, p) - dynamics(x, delta, fx - hf, p)) / (2 * hf)
    return B


def care_kleinman(A, B, Q, R, maxit=200, tol=1e-10):
    """Kleinman 策略迭代求解连续时间代数 Riccati 方程（不依赖 scipy）。"""
    from scipy.linalg import solve_continuous_lyapunov
    # 初始稳定增益：用极点配置/简单 LQR 近似（先取 u=-K0x 使 A-BK0 稳定）
    K = np.zeros((B.shape[1], A.shape[0]))
    # 用极小权重迭代几次得到可用初值：这里直接用 A 稳定化尝试
    try:
        K = np.linalg.lstsq(B, A + 2.0 * np.eye(3), rcond=None)[0]
    except np.linalg.LinAlgError:
        K = np.zeros((B.shape[1], A.shape[0]))
    P = np.eye(3)
    for k in range(maxit):
        Ak = A - B @ K
        # 解 Lyapunov 方程 Ak'P + P Ak = -(Q + K'RK)
        P = solve_continuous_lyapunov(Ak.T, -(Q + K.T @ R @ K))
        Kn = np.linalg.solve(R, B.T @ P)
        if _norm(Kn - K) < tol * (1 + _norm(K)):
            K = Kn
            break
        K = Kn
    return P, K, k + 1


def simulate_closed_loop(x0, delta_eq, fx_eq, K, x_eq, p=DEFAULT_PARAMS, T=6.0, dt=2e-3,
                         delta_bounds=(-0.35, 0.35), fx_bounds=(0.0, 13000.0)):
    """非线性闭环 RK4 积分，u = u_eq - K(x - x_eq)（带执行器限幅）。"""
    from race_drift_model import dynamics
    n = int(T / dt)
    ts = np.zeros(n + 1); xs = np.zeros((n + 1, 3)); us = np.zeros((n + 1, 2))
    xs[0] = x0
    def control(x):
        du = -K @ (x - x_eq)
        d = np.clip(delta_eq + du[0], delta_bounds[0], delta_bounds[1])
        fx = np.clip(fx_eq + du[1], fx_bounds[0], fx_bounds[1])
        return d, fx
    us[0] = control(x0)
    for i in range(n):
        x = xs[i]
        d1, f1 = us[i]
        k1 = dynamics(x, d1, f1, p)
        x2 = x + 0.5 * dt * k1; d2, f2 = control(x2)
        k2 = dynamics(x2, d2, f2, p)
        x3 = x + 0.5 * dt * k2; d3, f3 = control(x3)
        k3 = dynamics(x3, d3, f3, p)
        x4 = x + dt * k3; d4, f4 = control(x4)
        k4 = dynamics(x4, d4, f4, p)
        xn = x + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
        if not np.all(np.isfinite(xn)) or np.hypot(xn[0], xn[1]) > 200 or abs(xn[2]) > 30:
            xn = np.array([np.nan, np.nan, np.nan])
            ts[i + 1:] = ts[i] + dt * np.arange(1, n - i + 1)
            xs[i + 1:] = np.nan
            break
        xs[i + 1] = xn
        d5, f5 = control(xn)
        us[i + 1] = [d5, f5]
        ts[i + 1] = ts[i] + dt
    return ts, xs, us


def simulate_open_loop(x0, delta_eq, fx_eq, p=DEFAULT_PARAMS, T=6.0, dt=2e-3):
    """开环 RK4 积分（固定 delta_eq, fx_eq），用于对比漂移平衡点的开环发散。"""
    from race_drift_model import dynamics
    n = int(T / dt)
    ts = np.zeros(n + 1); xs = np.zeros((n + 1, 3))
    xs[0] = x0
    for i in range(n):
        x = xs[i]
        k1 = dynamics(x, delta_eq, fx_eq, p)
        k2 = dynamics(x + 0.5 * dt * k1, delta_eq, fx_eq, p)
        k3 = dynamics(x + 0.5 * dt * k2, delta_eq, fx_eq, p)
        k4 = dynamics(x + dt * k3, delta_eq, fx_eq, p)
        xn = x + dt / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
        if not np.all(np.isfinite(xn)) or np.hypot(xn[0], xn[1]) > 200 or abs(xn[2]) > 30:
            xs[i + 1:] = np.nan
            ts[i + 1:] = ts[i] + dt * np.arange(1, n - i + 1)
            break
        xs[i + 1] = xn
        ts[i + 1] = ts[i] + dt
    return ts, xs


# ---------------------------------------------------------------------------
# 6. 实验：算法比较、收敛阶、吸引域
# ---------------------------------------------------------------------------
def convergence_order(hist):
    """用最后几步残差估计收敛阶 p：e_{k+1} ≈ C e_k^p（对数最小二乘）。"""
    h = np.asarray(hist, float)
    h = h[h > 0]
    if len(h) < 4:
        return float('nan')
    h = h[-6:]
    ratios = []
    for i in range(1, len(h) - 1):
        num = np.log(h[i + 1] / h[i])
        den = np.log(h[i] / h[i - 1])
        if abs(den) > 1e-12 and np.isfinite(num):
            ratios.append(num / den)
    return float(np.median(ratios)) if ratios else float('nan')


def benchmark_case(V, delta, target, start, p=DEFAULT_PARAMS, reps=15):
    """对每个算法在同一初值/同一目标下计时并记录迭代历史。"""
    rows = []
    for name, fn in ALGORITHMS.items():
        r = fn(start, V, delta, p)
        err = float('nan')
        if r['ok']:
            err = float(_norm(residual(r['z'], V, delta, p)))
        ts = []
        for _ in range(reps):
            t0 = time.perf_counter()
            fn(start, V, delta, p)
            ts.append(time.perf_counter() - t0)
        rows.append(dict(algo=name, ok=bool(r['ok']), it=int(r['it']), nf=int(r['nf']),
                         nJ=int(r['nJ']), time_ms=float(np.median(ts) * 1e3),
                         res=err, hist=_res_hist(r), order=convergence_order(_res_hist(r)),
                         z=[float(v) for v in r['z']] if r['z'] is not None else None,
                         msg=r['msg']))
    return rows


def basin_map(V, delta, p=DEFAULT_PARAMS, n=61, beta_range=(-0.9, 0.25), r_range=(-0.5, 3.0),
              fx0=0.0):
    """(beta0, r0) 网格上的收敛结果分类：0=不收敛/非物理, 1=grip, 2=drift。"""
    bl = np.linspace(beta_range[0], beta_range[1], n)
    rl = np.linspace(r_range[0], r_range[1], n)
    lab = np.zeros((n, n), dtype=int)
    for i, b0 in enumerate(bl):
        for j, r0 in enumerate(rl):
            r = solve_newton(np.array([b0, r0, fx0]), V, delta, p)
            if r['ok'] and _norm(residual(r['z'], V, delta, p)) < 1e-9:
                typ = classify(r['z'], V, delta, p)
                lab[j, i] = {'grip': 1, 'drift': 2}.get(typ, 0)
    return dict(beta=list(map(float, bl)), r=list(map(float, rl)), label=lab.tolist())


# ---------------------------------------------------------------------------
# 7. 主实验流程
# ---------------------------------------------------------------------------
def main(quick=False):
    t_start = _now()
    _t_sec = [('start', _now())]
    p = DEFAULT_PARAMS
    out = dict(
        meta=dict(python=sys.version, numpy=np.__version__, platform=platform.platform(),
                  params={k: p[k] for k in p}, tol_res=TOL_RES, maxit=MAXIT,
                  generated=time.strftime('%Y-%m-%d %H:%M:%S')),
    )

    # ---- 7.1 参考工况：抓地/漂移多解性 ----
    cases = [(8.0, 0.10), (15.0, 0.10), (22.0, 0.10), (8.0, 0.25), (15.0, 0.25), (25.0, 0.10)]
    if quick:
        cases = cases[:2]
    out['cases'] = []
    for (V, d) in cases:
        sols, stat = multistart(V, d, p=p, n_start=250, seed=1)
        out['cases'].append(dict(V=V, delta=d, solutions=sols, multistart=stat))
        print('case V=%.1f delta=%.2f: %d physical equilibria' % (V, d, len(sols)))

    # ---- 7.2 平衡点支路：伪弧长延拓 + 折叠分岔 ----
    Vs = [6.0, 8.0, 10.0, 15.0, 18.0, 22.0, 26.0, 30.0]
    if quick:
        Vs = [8.0, 15.0]
    out['branches'] = {}
    fold_curve = []
    for V in Vs:
        ref = get_reference_solutions(V, 0.10, p=p, seed=2)
        if 'drift' not in ref:
            print('WARN no drift at V=%.1f' % V)
            continue
        zd = np.array(ref['drift']['z'])
        ar = trace_arclen(V, zd, 0.10, p=p, ds=0.01, nsteps=2400,
                          dmin=-0.80, dmax=1.80)
        pts = ar['pts']
        stride = max(1, len(pts) // 400)
        pack = [dict(delta=q['delta'], z=[float(v) for v in q['z']],
                     beta_deg=q['beta_deg'], r=q['r'], fx=q['fx'],
                     detJ=q['detJ'], detJ_scaled=q['detJ_scaled'],
                     condJ=q['condJ'], max_real=q['max_real'],
                     stable=q['stable']) for q in pts[::stride]]
        # 折叠点（delta'=0 的转向点），并同时给出该点的平衡态指标
        folds = []
        for f in ar['folds']:
            q = pts[f['index']]
            folds.append(dict(delta=f['delta'], beta_deg=q['beta_deg'], r=q['r'],
                              fx=q['fx'], detJ_scaled=f['detJ_scaled'],
                              max_real=f['max_real']))
        # 漂移支路上最大实部变号 -> 稳定化分岔（鞍点 -> 稳定结点）
        stab = None
        for k in range(1, len(pts)):
            a, b = pts[k - 1], pts[k]
            if a['max_real'] * b['max_real'] < 0 and a['delta'] > 0 and b['delta'] > 0:
                w = a['max_real'] / (a['max_real'] - b['max_real'])
                stab = dict(delta=float(a['delta'] + w * (b['delta'] - a['delta'])),
                            a_val=float(a['max_real']), b_val=float(b['max_real']))
                break
        out['branches'][str(V)] = dict(
            ref={k: dict(z=[float(v) for v in v['z']], beta_deg=v['beta_deg'],
                         r=v['r'], fx=v['fx'], kappa=v['kappa'],
                         max_real=v['max_real'], stable=v['stable'])
                 for k, v in ref.items()},
            n_pts=len(pts), n_pack=len(pack), ds=0.01, reason=ar['reason'],
            delta_min=float(min(q['delta'] for q in pts)),
            delta_max=float(max(q['delta'] for q in pts)),
            folds=folds, drift_stab=stab, pts=pack)
        if folds:
            for f in folds:
                if f['delta'] > 0:
                    fold_curve.append(dict(V=V, delta=f['delta'], beta_deg=f['beta_deg'],
                                           fx=f['fx'], max_real=f['max_real']))
        print('branch V=%.1f: %d pts (%s), folds=[%s]' % (
            V, len(pts), ar['reason'], ', '.join('%.5f' % f['delta'] for f in folds)))
    out['fold_curve'] = sorted(fold_curve, key=lambda q: q['V'])

    # ---- 7.2b (V,delta) 平面上的物理解个数（多起点统计） ----
    Vs_map = [6.0, 8.0, 10.0, 12.0, 15.0, 18.0, 22.0, 26.0, 30.0]
    deltas_map = [round(0.05 * k, 2) for k in range(17)]
    n_start_map = 60 if quick else 90
    if quick:
        Vs_map = [8.0, 15.0]
        deltas_map = [round(0.10 * k, 2) for k in range(9)]
    smap = dict(Vs=Vs_map, deltas=deltas_map, counts=[], n_start=n_start_map)
    for V in Vs_map:
        row = []
        for d in deltas_map:
            sols, _st = multistart(V, d, p=p, n_start=n_start_map, seed=7)
            row.append(dict(n=len(sols),
                            drift=sum(1 for s in sols if s['type'] == 'drift'),
                            grip=sum(1 for s in sols if s['type'] == 'grip')))
        smap['counts'].append(row)
        print('solmap V=%.1f done' % V)
    out['solmap'] = smap

    _t_sec.append(('7.2 branches+solmap', _now()))

    # ---- 7.3 算法比较（固定初值，同一目标） ----
    bench = []
    for V, d, typ in [(10.0, 0.05, 'grip'), (22.0, 0.10, 'grip'),
                      (8.0, 0.10, 'drift'), (15.0, 0.10, 'drift'), (22.0, 0.10, 'drift')]:
        ref = get_reference_solutions(V, d, p=p, seed=3)
        if typ not in ref:
            print('WARN bench no %s at V=%.1f delta=%.2f' % (typ, V, d)); continue
        zr = np.array(ref[typ]['z'])
        start = zr + np.array([-0.06, 0.15, 400.0]) if typ == 'drift' else zr + np.array([0.02, 0.05, 50.0])
        rows = benchmark_case(V, d, typ, start, p=p, reps=5 if quick else 15)
        bench.append(dict(V=V, delta=d, type=typ, target=[float(v) for v in zr], start=[float(v) for v in start], rows=rows))
        print('bench V=%.1f delta=%.2f %s' % (V, d, typ))
    out['benchmark'] = bench

    _t_sec.append(('7.3 benchmark', _now()))

    # ---- 7.4 随机初值成功率 ----
    rs = []
    for V, d, typ in [(8.0, 0.10, 'drift'), (15.0, 0.10, 'drift'), (22.0, 0.10, 'grip'), (22.0, 0.10, 'drift')]:
        ref = get_reference_solutions(V, d, p=p, seed=4)
        if typ not in ref:
            continue
        zr = np.array(ref[typ]['z'])
        rng = np.random.default_rng(11)
        lo, hi = default_bounds(p)
        N = 60 if quick else 300
        starts = [np.array([rng.uniform(-0.8, 0.35), rng.uniform(-1.0, 3.0),
                            rng.uniform(-500.0, 11000.0)]) for _ in range(N)]
        for name, fn in ALGORITHMS.items():
            ok = 0; iters = []
            for z0 in starts:
                rr = fn(z0, V, d, p)
                if rr['ok'] and _norm(residual(rr['z'], V, d, p)) < 1e-8:
                    ok += 1; iters.append(rr['it'])
            rs.append(dict(V=V, delta=d, type=typ, algo=name, success=ok / N,
                           n=N, mean_it=float(np.mean(iters)) if iters else 0.0))
        print('random-start V=%.1f delta=%.2f %s done' % (V, d, typ))
    out['random_start'] = rs

    _t_sec.append(('7.4 random_start', _now()))

    # ---- 7.5 吸引域 ----
    out['basin'] = {}
    for (V, d) in [(8.0, 0.10), (15.0, 0.10)]:
        out['basin']['%.1f_%.2f' % (V, d)] = basin_map(V, d, p=p, n=61 if not quick else 21)
        print('basin %s done' % ('%.1f_%.2f' % (V, d)))

    _t_sec.append(('7.5 basin', _now()))

    # ---- 7.6 设计优化（增广拉格朗日 + 隐函数定理消元）----
    out['design'] = {}
    try:
        Vd, dd = 8.0, 0.10
        ref = get_reference_solutions(Vd, dd, p=p, seed=5)
        zr = np.array(ref['drift']['z'])
        xbase = np.array([p['a'], p['mu_r'], p['ClA_r']], float)
        db = design_derivs(xbase, Vd, dd, zr, p0=p)
        ay_min = 13.40
        xlo = np.array([1.00, 1.10, 0.20]); xhi = np.array([1.30, 1.55, 0.90])
        alm = design_alm(Vd, dd, zr, p0=p, ay_min=ay_min, xlo=xlo, xhi=xhi,
                         n_outer=12 if quick else 18, verbose=True)
        # 多起点：检验设计问题是否非凸（不同初值是否收敛到同一 KKT 点）
        best = alm; starts = []
        for x0 in (np.array([1.00, 1.20, 0.50]), np.array([1.30, 1.50, 0.85]),
                   np.array([1.05, 1.45, 0.30])):
            aa = design_alm(Vd, dd, zr, p0=p, ay_min=ay_min, xlo=xlo, xhi=xhi,
                            n_outer=10, x_init=x0)
            starts.append(aa)
            if aa.get('ok') and aa['kappa'] < best['kappa']:
                best = aa
        # 影子价格：d kappa*/d ay_min ≈ -lambda（KKT 乘子即约束灵敏度）
        alm2 = design_alm(Vd, dd, zr, p0=p, ay_min=ay_min - 0.20, xlo=xlo, xhi=xhi,
                          n_outer=10)
        shadow = None
        if alm2.get('ok'):
            shadow = dict(delta_ay=-0.20, dkappa=float(alm2['kappa'] - best['kappa']),
                          ratio=float((alm2['kappa'] - best['kappa']) / (-0.20)),
                          lam=float(best['lam']))
        ver = design_verify(Vd, dd, zr, p0=p)
        sw = design_sweep(Vd, dd, zr, p0=p, n=19 if quick else 25)
        z_opt = np.array(alm['design'], float)
        dopt = design_derivs(z_opt, Vd, dd, zr, p0=p)
        out['design'] = dict(V=Vd, delta=dd, ay_min=float(ay_min),
                             base=dict(x=[float(v) for v in xbase],
                                       kappa=float(db['kappa']), ay=float(db['ay']),
                                       z=[float(v) for v in zr]),
                             opt=dict(x=[float(v) for v in z_opt],
                                      kappa=float(best['kappa']), ay=float(best['ay']),
                                      c=float(best['c']), lam=float(best['lam']),
                                      kkt_free=float(best['kkt_free']),
                                      z=[float(v) for v in dopt['z']] if dopt else []),
                             alm=best, multistart=starts, shadow=shadow,
                             verify=ver, sweep=sw,
                             xlo=[float(v) for v in xlo], xhi=[float(v) for v in xhi])
        print('design: kappa %.6f -> %.6f | ay %.3f (min %.3f) lam=%.4e'
              % (db['kappa'], alm['kappa'], alm['ay'], ay_min, alm['lam']))
    except Exception as exc:
        out['design'] = dict(error=repr(exc))
        print('design failed:', repr(exc))

    # ---- 7.7 闭环控制：线性化 + LQR（Kleinman 迭代）+ 非线性仿真 ----
    out['control'] = []
    for (V, d) in [(8.0, 0.10), (15.0, 0.10), (22.0, 0.10)]:
        try:
            ref = get_reference_solutions(V, d, p=p, seed=6)
            if 'drift' not in ref:
                continue
            zr = np.array(ref['drift']['z'])
            dg = diagnose(zr, V, d, p)
            x_eq = np.array([dg['vx'], dg['vy'], dg['r']])
            A = _dynamics_jac(x_eq, d, zr[2], p)
            B = input_jac(x_eq, d, zr[2], p)
            ctrl_rank = int(np.linalg.matrix_rank(np.hstack([B, A @ B, A @ A @ B])))
            Q = np.diag([1.0, 4.0, 40.0]); R = np.diag([40.0, 1e-4])
            P, K, kit = care_kleinman(A, B, Q, R)
            P_s, K_s = _care_scipy(A, B, Q, R)
            eig_cl = np.linalg.eigvals(A - B @ K)
            sim_pert = np.array([0.8, 0.4, 0.10])
            ts, xs, us = simulate_closed_loop(x_eq + sim_pert, d, zr[2], K, x_eq, p=p, T=8.0)
            ts_o, xs_o = simulate_open_loop(x_eq + sim_pert, d, zr[2], p=p, T=8.0)
            err0 = float(_norm(sim_pert))
            errT_c = float(_norm(xs[-1] - x_eq))
            errT_o = float(_norm(xs_o[-1] - x_eq))
            en = np.linalg.norm(xs - x_eq, axis=1)
            thr = 0.1 * err0
            idx = np.where(en < thr)[0]
            settle = float(ts[idx[0]]) if idx.size and np.all(en[idx[0]:] < thr) else None
            bgrid = np.linspace(-0.55, -0.20, 15)
            rgrid = np.linspace(1.20, 1.75, 15)
            basin = np.zeros((15, 15), dtype=int)
            for ii, b0 in enumerate(bgrid):
                for jj, r0 in enumerate(rgrid):
                    x0 = np.array([V * np.cos(b0), V * np.sin(b0), r0])
                    _, xsb, _ = simulate_closed_loop(x0, d, zr[2], K, x_eq, p=p, T=4.0, dt=4e-3)
                    basin[jj, ii] = int(np.all(np.isfinite(xsb[-1])) and _norm(xsb[-1] - x_eq) < 0.35)
            out['control'].append(dict(
                V=V, delta=d, z=[float(v) for v in zr], x_eq=[float(v) for v in x_eq],
                A=[[float(v) for v in row] for row in A],
                B=[[float(v) for v in row] for row in B],
                controllability_rank=ctrl_rank,
                Q=[float(Q[k, k]) for k in range(3)], R=[float(R[k, k]) for k in range(2)],
                K=[[float(v) for v in row] for row in K],
                eigen_open=[[float(a), float(b)] for a, b in zip(np.real(np.linalg.eigvals(A)),
                                                                 np.imag(np.linalg.eigvals(A)))],
                eigen_closed=[[float(a), float(b)] for a, b in zip(np.real(eig_cl), np.imag(eig_cl))],
                kleinman_it=int(kit), care_diff=float(np.linalg.norm(K - K_s) / max(1.0, np.linalg.norm(K))),
                err0=err0, errT_closed=errT_c, errT_open=errT_o,
                reduction=float(errT_o / max(errT_c, 1e-12)), settle_time=settle,
                du_max=float(np.max(np.abs(us[:, 0]))), dfx_max=float(np.max(np.abs(us[:, 1]))),
                sim=dict(t=[round(float(v), 5) for v in ts[::4]],
                         x=[[round(float(v), 6) for v in row] for row in xs[::4]],
                         u=[[round(float(v), 6) for v in row] for row in us[::4]]),
                sim_open=dict(t=[round(float(v), 5) for v in ts_o[::4]],
                              x=[[round(float(v), 6) for v in row] for row in xs_o[::4]]),
                basin_beta=[float(v) for v in bgrid], basin_r=[float(v) for v in rgrid],
                basin=basin.tolist(), basin_frac=float(basin.mean())))
            print('control V=%.1f: rank=%d settle=%s err %.2e -> %.2e (open %.2e) basin=%.2f'
                  % (V, ctrl_rank, settle, err0, errT_c, errT_o, basin.mean()))
        except Exception as exc:
            print('control V=%.1f failed:' % V, repr(exc))

    # ---- 7.8 收敛阶随车速 / 不稳定增长率随车速 ----
    growth = []
    for V in np.arange(6.0, 30.1, 2.0):
        ref = get_reference_solutions(V, 0.10, p=p, seed=7)
        if 'drift' not in ref:
            continue
        zr = np.array(ref['drift']['z'])
        dg = diagnose(zr, V, 0.10, p)
        growth.append(dict(V=float(V), beta_deg=float(dg['beta_deg']), r=float(dg['r']),
                           fx=float(dg['fx']), kappa=float(dg['fx_frac']),
                           max_real=float(dg['max_real']), condJ=float(dg['condJ']),
                           detJ=float(dg['detJ'])))
    out['drift_growth'] = growth
    print('drift growth points:', len(growth))

    out['elapsed_s'] = _now() - t_start
    path = os.path.join(HERE, 'results.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print('written', path, 'elapsed %.1fs' % out['elapsed_s'])
    return out


def _dynamics_jac(x, delta, fx, p=DEFAULT_PARAMS, h=1e-6):
    from race_drift_model import dynamics
    A = np.zeros((3, 3))
    for j in range(3):
        xp = x.copy(); xm = x.copy(); xp[j] += h; xm[j] -= h
        A[:, j] = (dynamics(xp, delta, fx, p) - dynamics(xm, delta, fx, p)) / (2 * h)
    return A


def _care_scipy(A, B, Q, R):
    from scipy.linalg import solve_continuous_are
    P = solve_continuous_are(A, B, Q, R)
    K = np.linalg.solve(R, B.T @ P)
    return P, K


if __name__ == '__main__':
    quick = '--quick' in sys.argv
    main(quick=quick)
