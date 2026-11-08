"""
race_drift_model.py
===================
赛车稳态漂移平衡点模型（单轨/自行车模型 + 刷子轮胎 + 摩擦圆 + 准静态载荷转移 + 气动）

坐标与符号约定
--------------
车身坐标系：x 轴指向车头，y 轴指向车身左侧，横摆角速度 r 逆时针（左转）为正。
状态量取  z = (beta, r, fx)：
    beta —— 车身侧偏角 [rad]，速度方向到车身 x 轴的有符号夹角，
            vx = V cos(beta), vy = V sin(beta)
    r    —— 横摆角速度 [rad/s]
    fx   —— 后轴纵向驱动力 [N]（平衡点处由方程解出，等价于"稳态油门"）

给定工况参数 (V, delta)：车速 V [m/s]、前轮转角 delta [rad]（左转为正，
漂移时通常为负，即"反打方向"）。

平衡方程组（三个未知量、三个方程）
    m (vx_dot - r vy) = Fx  ->  e1 = fx + Fdx - Fyf sin(delta) + m r vy = 0
    m (vy_dot + r vx) = Fy  ->  e2 = Fyf cos(delta) + Fyr + Fdy - m r vx = 0
    Iz r_dot = Mz           ->  e3 = a Fyf cos(delta) - b Fyr = 0

轮胎模型
--------
单轴刷子模型（纯侧偏、单调饱和、C2 连续）：
    u = C_alpha * tan(alpha) / M ,   M 为该轴可用摩擦圆半径
    Fy = -M * Phi(u),   Phi(u) = sign(u)(|u| - |u|^2/3 + |u|^3/27)  (|u|<=3)
                        Phi(u) = sign(u)                            (|u|>3)
前轴：M_f = mu_f * Fz_f （自由滚动）
后轴：M_r = sqrt( max(eps, (mu_r Fz_r)^2 - fx^2) )  （摩擦圆：驱动占用的纵向力
      会压缩剩余侧向能力，这是"动力漂移"产生的根本机理）

准静态载荷转移与气动
--------------------
    ax = -r vy                （平衡点处车身纵向比力）
    Fz_f = m g b/L + q ClA_f - m ax h/L
    Fz_r = m g a/L + q ClA_r + m ax h/L,   q = 0.5 rho V^2
（令 h = 0 或 ClA = 0 即可做消融对比）

本模块只负责"模型"，不含任何求解算法；算法见 race_drift_solver.py。
"""
from __future__ import annotations
import numpy as np

G = 9.81

# ---------------------------------------------------------------------------
# 默认参数（某后驱赛车，约 1450 kg）
# ---------------------------------------------------------------------------
DEFAULT_PARAMS = dict(
    m=1450.0,      # 整车质量 kg
    Iz=2200.0,     # 横摆转动惯量 kg m^2
    a=1.15,        # 质心到前轴距离 m
    b=1.35,        # 质心到后轴距离 m
    L=2.50,        # 轴距 m
    h=0.45,        # 质心高度 m
    mu_f=1.30,     # 前轴摩擦系数
    mu_r=1.35,     # 后轴摩擦系数
    Caf=130000.0,  # 前轴侧偏刚度 N/rad
    Car=150000.0,  # 后轴侧偏刚度 N/rad
    rho=1.225,     # 空气密度 kg/m^3
    CdA=1.00,      # 风阻面积 m^2
    ClA_f=0.60,    # 前轴升力（下压力）系数面积 m^2
    ClA_r=0.90,    # 后轴升力（下压力）系数面积 m^2
    eps_M=1.0,     # 摩擦圆半径平方的正则化下限 N^2
    Fz_min=200.0,  # 垂向载荷下限 N（数值保护）
)

PARAM_META = [
    ('m', '整车质量', 'kg'), ('Iz', '横摆转动惯量', 'kg·m²'),
    ('a', '质心至前轴距离', 'm'), ('b', '质心至后轴距离', 'm'),
    ('L', '轴距', 'm'), ('h', '质心高度', 'm'),
    ('mu_f', '前轴摩擦系数', '—'), ('mu_r', '后轴摩擦系数', '—'),
    ('Caf', '前轴侧偏刚度', 'N/rad'), ('Car', '后轴侧偏刚度', 'N/rad'),
    ('rho', '空气密度', 'kg/m³'), ('CdA', '风阻系数×迎风面积', 'm²'),
    ('ClA_f', '前轴下压力系数×面积', 'm²'), ('ClA_r', '后轴下压力系数×面积', 'm²'),
]

# 平衡点搜索的默认箱式约束（算法用的箱约束，不是物理限制本身）
#   beta:  |beta| <= 1.2 rad (约 69")
#   r:     |r|    <= 6 rad/s
#   fx:    |fx|   <= 1.1 * mu_r * (静态后轴载荷 + 最大载荷转移 + 40 m/s 下压力)
# 物理可行性另由 is_physical() 判定（前向速度、r>0、摩擦圆内、|beta|）。
def default_bounds(p=DEFAULT_PARAMS, V_max=40.0):
    q_max = 0.5 * p['rho'] * V_max * V_max
    Fzr_ub = p['m'] * G * p['a'] / p['L'] + q_max * p['ClA_r'] + p['m'] * G * p['h'] / p['L']
    fxmax = 1.10 * p['mu_r'] * Fzr_ub
    lo = np.array([-1.20, -6.0, -fxmax])
    hi = np.array([1.20, 6.0, fxmax])
    return lo, hi


def is_physical(z, V, delta, p=DEFAULT_PARAMS, tol_mr=0.02):
    """物理可行平衡点筛选：
    - 前向行驶 vx>0
    - 左转 r>0
    - |beta| <= 1.2 rad
    - 驱动比 |fx|/(mu_r Fzr) < 1 - tol_mr（后轴仍保留 2% 侧向摩擦圆余量）
    """
    beta, r, fx = z
    if V * np.cos(beta) <= 0.5 or r <= 1e-3 or abs(beta) > 1.2:
        return False
    ax = -r * V * np.sin(beta)
    Fzf, Fzr = vehicle_loads(V, ax, p)
    if (p['mu_r'] * Fzr) <= 0:
        return False
    return abs(fx) / (p['mu_r'] * Fzr) < (1.0 - tol_mr)


# ---------------------------------------------------------------------------
# 基础部件
# ---------------------------------------------------------------------------
def phi_unit(u):
    """单轴刷子模型的归一化力-滑移函数 Phi(u)，奇函数、C2 连续、单调饱和于 +-1。"""
    u = np.asarray(u, float)
    au = np.abs(u)
    core = au - au * au / 3.0 + au ** 3 / 27.0
    return np.where(au <= 3.0, core, 1.0) * np.sign(u)


def phi_unit_d(u):
    """dPhi/du。"""
    u = np.asarray(u, float)
    au = np.abs(u)
    return np.where(au <= 3.0, (1.0 - au / 3.0) ** 2, 0.0)


def tire_lateral(alpha, C, M):
    """刷子轮胎侧向力，正值指向车身 y 正方向（左）。"""
    s = np.tan(np.asarray(alpha, float))
    return -M * phi_unit(C * s / M)


def tire_lateral_parts(alpha, C, M):
    """返回 (Fy, dFy/dalpha, dFy/dM, Phi(u), u)。"""
    s = np.tan(np.asarray(alpha, float))
    u = C * s / M
    Phi = phi_unit(u)
    dPhi = phi_unit_d(u)
    Fy = -M * Phi
    dFy_da = -C * dPhi / np.maximum(np.cos(np.asarray(alpha, float)) ** 2, 1e-12)
    dFy_dM = -Phi + u * dPhi
    return Fy, dFy_da, dFy_dM, Phi, u


def vehicle_loads(V, ax, p=DEFAULT_PARAMS):
    """准静态垂向载荷（含气动下压力与纵向载荷转移）。"""
    q = 0.5 * p['rho'] * V * V
    Fzf = p['m'] * G * p['b'] / p['L'] + q * p['ClA_f'] - p['m'] * ax * p['h'] / p['L']
    Fzr = p['m'] * G * p['a'] / p['L'] + q * p['ClA_r'] + p['m'] * ax * p['h'] / p['L']
    return max(Fzf, p['Fz_min']), max(Fzr, p['Fz_min'])


def state_from_z(z, V):
    """z=(beta,r,fx) -> 车身状态 x=(vx,vy,r)。"""
    beta, r, fx = z
    return np.array([V * np.cos(beta), V * np.sin(beta), r]), fx


def z_from_state(x, fx):
    vx, vy, r = x
    return np.array([np.arctan2(vy, vx), r, fx])


# ---------------------------------------------------------------------------
# 残差、雅可比
# ---------------------------------------------------------------------------
def residual(z, V, delta, p=DEFAULT_PARAMS):
    """平衡方程残差 e(z) ∈ R^3。"""
    beta, r, fx = z
    vx = V * np.cos(beta)
    vy = V * np.sin(beta)
    ax = -r * vy
    Fzf, Fzr = vehicle_loads(V, ax, p)
    Mf = p['mu_f'] * Fzf
    Mr = np.sqrt(max(p['eps_M'], (p['mu_r'] * Fzr) ** 2 - fx * fx))
    af = np.arctan2(vy + p['a'] * r, vx) - delta
    ar = np.arctan2(vy - p['b'] * r, vx)
    Fyf = tire_lateral(af, p['Caf'], Mf)
    Fyr = tire_lateral(ar, p['Car'], Mr)
    qd = 0.5 * p['rho'] * p['CdA']
    Fdx = -qd * V * vx
    Fdy = -qd * V * vy
    e1 = fx + Fdx - Fyf * np.sin(delta) + p['m'] * r * vy
    e2 = Fyf * np.cos(delta) + Fyr + Fdy - p['m'] * r * vx
    e3 = p['a'] * Fyf * np.cos(delta) - p['b'] * Fyr
    return np.array([e1, e2, e3])


def residual_delta(z, V, delta, p=DEFAULT_PARAMS):
    """残差对参数 delta 的偏导 d e / d delta（延拓法预测步与折叠方程需要）。"""
    beta, r, fx = z
    vx, vy = V * np.cos(beta), V * np.sin(beta)
    ax = -r * vy
    Fzf, Fzr = vehicle_loads(V, ax, p)
    Mf = p['mu_f'] * Fzf
    af = np.arctan2(vy + p['a'] * r, vx) - delta
    Fyf, dFyf_da, _, _, _ = tire_lateral_parts(af, p['Caf'], Mf)
    sd, cd = np.sin(delta), np.cos(delta)
    # af 对 delta 的偏导为 -1
    dFyf_dd = -dFyf_da
    return np.array([
        -(dFyf_dd * sd + Fyf * cd),
        dFyf_dd * cd - Fyf * sd,
        p['a'] * (dFyf_dd * cd - Fyf * sd),
    ])


def residual_jac(z, V, delta, p=DEFAULT_PARAMS):
    """解析雅可比 d e / d(beta, r, fx)，用于牛顿法/灵敏度/分岔分析。"""
    beta, r, fx = z
    cb, sb = np.cos(beta), np.sin(beta)
    vx, vy = V * cb, V * sb
    ax = -r * vy
    Fzf, Fzr = vehicle_loads(V, ax, p)
    Mf = p['mu_f'] * Fzf
    Mr = np.sqrt(max(p['eps_M'], (p['mu_r'] * Fzr) ** 2 - fx * fx))
    af = np.arctan2(vy + p['a'] * r, vx) - delta
    ar = np.arctan2(vy - p['b'] * r, vx)
    Fyf, dFyf_da, dFyf_dM, _, _ = tire_lateral_parts(af, p['Caf'], Mf)
    Fyr, dFyr_da, dFyr_dM, _, _ = tire_lateral_parts(ar, p['Car'], Mr)
    sd, cd = np.sin(delta), np.cos(delta)
    qd = 0.5 * p['rho'] * p['CdA']

    # --- 滑移角对 (beta, r) 的偏导 ---
    Df = (vy + p['a'] * r) ** 2 + vx * vx
    Dr = (vy - p['b'] * r) ** 2 + vx * vx
    daf_db = (vx * vx + vy * vy + p['a'] * r * vy) / Df
    daf_dr = p['a'] * vx / Df
    dar_db = (vx * vx + vy * vy - p['b'] * r * vy) / Dr
    dar_dr = -p['b'] * vx / Dr

    # --- 垂向载荷/摩擦圆对 (beta, r) 的偏导 ---
    # ax = -r*vy ; dax/dbeta = -r*dvy/dbeta = -r*vx ; dax/dr = -vy
    dax_db = -r * vx
    dax_dr = -vy
    mtl = p['m'] * p['h'] / p['L']
    dFzf_db = -mtl * dax_db
    dFzf_dr = -mtl * dax_dr
    dFzr_db = mtl * dax_db
    dFzr_dr = mtl * dax_dr
    dMf_db = p['mu_f'] * dFzf_db
    dMf_dr = p['mu_f'] * dFzf_dr
    # Mr = sqrt(max(eps, (mu_r Fzr)^2 - fx^2))
    if (p['mu_r'] * Fzr) ** 2 - fx * fx > p['eps_M']:
        dMr_dFzr = p['mu_r'] ** 2 * Fzr / Mr
    else:
        dMr_dFzr = 0.0
    dMr_db = dMr_dFzr * dFzr_db
    dMr_dr = dMr_dFzr * dFzr_dr
    dMr_dfx = -fx / Mr if (p['mu_r'] * Fzr) ** 2 - fx * fx > p['eps_M'] else 0.0

    dFyf_db = dFyf_da * daf_db + dFyf_dM * dMf_db
    dFyf_dr = dFyf_da * daf_dr + dFyf_dM * dMf_dr
    dFyr_db = dFyr_da * dar_db + dFyr_dM * dMr_db
    dFyr_dr = dFyr_da * dar_dr + dFyr_dM * dMr_dr
    dFyr_dfx = dFyr_dM * dMr_dfx

    dFdx_db = qd * V * vy          # d(-qd V vx)/dbeta = -qd V (-vy)
    dFdy_db = -qd * V * vx         # d(-qd V vy)/dbeta = -qd V vx
    dvy_db = vx
    dvx_db = -vy
    dvx_dr = 0.0

    J = np.zeros((3, 3))
    # e1 = fx + Fdx - Fyf sd + m r vy
    J[0, 0] = dFdx_db - dFyf_db * sd + p['m'] * r * dvy_db
    J[0, 1] = -dFyf_dr * sd + p['m'] * vy
    J[0, 2] = 1.0
    # e2 = Fyf cd + Fyr + Fdy - m r vx
    J[1, 0] = dFyf_db * cd + dFyr_db + dFdy_db - p['m'] * r * dvx_db
    J[1, 1] = dFyf_dr * cd + dFyr_dr - p['m'] * vx
    J[1, 2] = dFyr_dfx
    # e3 = a Fyf cd - b Fyr
    J[2, 0] = p['a'] * dFyf_db * cd - p['b'] * dFyr_db
    J[2, 1] = p['a'] * dFyf_dr * cd - p['b'] * dFyr_dr
    J[2, 2] = -p['b'] * dFyr_dfx
    return J


# ---------------------------------------------------------------------------
# 动力学（状态 x=(vx,vy,r)，输入 delta 与后轴驱动力 fx）
# ---------------------------------------------------------------------------
def dynamics(x, delta, fx, p=DEFAULT_PARAMS):
    """车身坐标系三自由度动力学 x_dot = f(x; delta, fx)。"""
    vx, vy, r = x
    V = np.hypot(vx, vy)
    ax = -r * vy if False else 0.0  # 占位：载荷用比力，下面按定义计算
    # 载荷转移使用的比力就是当前加速度沿车身 x 的分量：
    # a_x = vx_dot - r vy ；在一般状态点用基于力的自洽近似会引入隐性耦合，
    # 这里采用准静态假设：用 Fx/m 的一阶近似 a_x = fx_body/m
    qd = 0.5 * p['rho'] * p['CdA']
    q = 0.5 * p['rho'] * V * V
    # 先用不含载荷转移的载荷计算轮胎力，再更新一次比力（两步准静态迭代，足够收敛）
    Fzf = p['m'] * G * p['b'] / p['L'] + q * p['ClA_f']
    Fzr = p['m'] * G * p['a'] / p['L'] + q * p['ClA_r']
    for _ in range(3):
        af = np.arctan2(vy + p['a'] * r, vx) - delta
        ar = np.arctan2(vy - p['b'] * r, vx)
        Fyf = tire_lateral(af, p['Caf'], p['mu_f'] * max(Fzf, p['Fz_min']))
        Mr = np.sqrt(max(p['eps_M'], (p['mu_r'] * max(Fzr, p['Fz_min'])) ** 2 - fx * fx))
        Fyr = tire_lateral(ar, p['Car'], Mr)
        Fx_body = fx - qd * V * vx - Fyf * np.sin(delta)
        ax_body = Fx_body / p['m']
        Fzf = p['m'] * G * p['b'] / p['L'] + q * p['ClA_f'] - p['m'] * ax_body * p['h'] / p['L']
        Fzr = p['m'] * G * p['a'] / p['L'] + q * p['ClA_r'] + p['m'] * ax_body * p['h'] / p['L']
    Fdy = -qd * V * vy
    Fy = Fyf * np.cos(delta) + Fyr + Fdy
    Mz = p['a'] * Fyf * np.cos(delta) - p['b'] * Fyr
    return np.array([Fx_body / p['m'] + r * vy,
                     Fy / p['m'] - r * vx,
                     Mz / p['Iz']])


def dynamics_jac(x, delta, fx, p=DEFAULT_PARAMS, h=1e-6):
    """中心差分动力学的雅可比 A = df/dx（3x3）。"""
    x = np.asarray(x, float)
    A = np.zeros((3, 3))
    for j in range(3):
        xp = x.copy(); xm = x.copy()
        xp[j] += h; xm[j] -= h
        A[:, j] = (dynamics(xp, delta, fx, p) - dynamics(xm, delta, fx, p)) / (2 * h)
    return A


# ---------------------------------------------------------------------------
# 平衡点诊断
# ---------------------------------------------------------------------------
def diagnose(z, V, delta, p=DEFAULT_PARAMS):
    """给定平衡点，返回全部诊断量（力、滑移角、特征值、稳定性）。"""
    beta, r, fx = z
    vx, vy = V * np.cos(beta), V * np.sin(beta)
    ax = -r * vy
    Fzf, Fzr = vehicle_loads(V, ax, p)
    Mf = p['mu_f'] * Fzf
    Mr = np.sqrt(max(p['eps_M'], (p['mu_r'] * Fzr) ** 2 - fx * fx))
    af = np.arctan2(vy + p['a'] * r, vx) - delta
    ar = np.arctan2(vy - p['b'] * r, vx)
    Fyf = tire_lateral(af, p['Caf'], Mf)
    Fyr = tire_lateral(ar, p['Car'], Mr)
    qd = 0.5 * p['rho'] * p['CdA']
    Fdx, Fdy = -qd * V * vx, -qd * V * vy
    x = np.array([vx, vy, r])
    ev = np.linalg.eigvals(dynamics_jac(x, delta, fx, p))
    d = dict(
        beta=beta, beta_deg=np.degrees(beta), r=r, fx=fx,
        vx=vx, vy=vy, V=V, delta=delta,
        Fzf=Fzf, Fzr=Fzr, Mf=Mf, Mr=Mr,
        af=af, af_deg=np.degrees(af), ar=ar, ar_deg=np.degrees(ar),
        Fyf=Fyf, Fyr=Fyr, Fdx=Fdx, Fdy=Fdy,
        sx_f=Fyf / Mf, sx_r=Fyr / Mr,
        fx_frac=fx / (p['mu_r'] * Fzr),
        ax=ax, ay=r * vx,
        eig=ev, eig_real=np.real(ev), eig_imag=np.imag(ev),
        max_real=np.max(np.real(ev)),
        is_stable=bool(np.all(np.real(ev) < -1e-9)),
        detJ=float(np.linalg.det(residual_jac(z, V, delta, p))),
        condJ=float(np.linalg.cond(residual_jac(z, V, delta, p))),
    )
    return d


def drift_measure(d):
    """漂移程度指标：侧偏角绝对值（度）与后轴侧向饱和率。"""
    return abs(d['beta_deg']), abs(d['sx_r'])


if __name__ == '__main__':
    p = DEFAULT_PARAMS
    z = np.array([0.0, 0.0, 0.0])
    V, delta = 15.0, 0.05
    e = residual(z, V, delta, p)
    J = residual_jac(z, V, delta, p)
    h = 1e-6
    Jfd = np.zeros((3, 3))
    for j in range(3):
        zp = z.copy(); zm = z.copy(); zp[j] += h; zm[j] -= h
        Jfd[:, j] = (residual(zp, V, delta, p) - residual(zm, V, delta, p)) / (2 * h)
    print('residual at z=0:', e)
    print('analytic J:\n', J)
    print('max |J - J_fd| =', np.max(np.abs(J - Jfd)))
    print('rel err =', np.max(np.abs(J - Jfd)) / max(1.0, np.max(np.abs(J))))
    print('loads:', vehicle_loads(15.0, 0.0, p))
    print('phi check:', phi_unit(np.array([-4.0, -3.0, -1.0, 0.0, 1.0, 3.0, 4.0])))
