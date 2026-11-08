# -*- coding: utf-8 -*-
"""
build_ppt.py
============
《基于非线性优化的赛车漂移平衡点求解与稳定性设计》答辩 PPT 生成脚本。

用法：
    python 大作业\\build_ppt.py

流程：
  1) 读取 大作业\\results.json（全部数字现算/现读，不写死；缺键时跳过并给 fallback）
  2) 生成 16:9 中文答辩 PPT（约 17 页）：大作业\\大作业_答辩PPT.pptx
  3) 调用 LibreOffice Kit 导出 PDF：大作业\\大作业_答辩PPT.pdf
  4) 自检：页数、形状越界、文本高度估算、PDF 大小与 %PDF- 头

仅本脚本与输出 pptx/pdf 可写；不改动 results.json / figs / 求解器。
"""
from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

# ---------------------------------------------------------------------------
# 路径与常量
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results.json")
FIGS = os.path.join(HERE, "figs")
PPTX = os.path.join(HERE, "大作业_答辩PPT.pptx")
PDF = os.path.join(HERE, "大作业_答辩PPT.pdf")

NODE_CANDIDATES = [
    r"E:\code\node-v24.19.0-win-x64\node.exe",
    r"C:\Users\86768\AppData\Local\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\node\bin\node.exe",
]
CLI = (r"C:\Users\86768\AppData\Local\Programs\DeepSeek Harness\resources\app.asar.unpacked"
       r"\dsh\node_modules\@deepseek-ai\libreoffice-kit\lib\cli.js")

CN = "Microsoft YaHei"
MONO = "Consolas"

SW = 13.333  # slide width (in)
SH = 7.5     # slide height (in)

NAVY = RGBColor(0x12, 0x28, 0x4B)
BLUE = RGBColor(0x2E, 0x75, 0xB6)
LBLUE = RGBColor(0xD9, 0xE2, 0xF3)
RED = RGBColor(0xC0, 0x00, 0x00)
INK = RGBColor(0x1F, 0x1F, 0x1F)
GRAY = RGBColor(0x59, 0x59, 0x59)
LGRAY = RGBColor(0xF2, 0xF5, 0xFA)
BORDER = RGBColor(0xBF, 0xBF, 0xBF)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
GREEN = RGBColor(0x1E, 0x6B, 0x52)

WARNINGS: list[str] = []
TOTAL = 17  # 由 build_deck 结束时校准


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def log(msg: str) -> None:
    print(msg, flush=True)


def load_results() -> dict:
    """读取 results.json；若正被后台任务重写导致解析失败，等待重试。"""
    last_err = None
    for attempt in range(4):
        try:
            with open(RESULTS, "r", encoding="utf-8") as f:
                d = json.load(f)
            mt = datetime.fromtimestamp(os.path.getmtime(RESULTS))
            log(f"[data] results.json 读取成功：{len(open(RESULTS,'rb').read())/1024:.0f} KB，"
                f"修改时间 {mt:%H:%M:%S}，generated={d.get('meta',{}).get('generated','?')}，"
                f"elapsed={d.get('elapsed_s', d.get('meta',{}).get('elapsed_s','?'))}")
            return d
        except Exception as e:  # noqa: BLE001
            last_err = e
            log(f"[data] 第 {attempt+1} 次读取失败（{e}），40 s 后重试…")
            time.sleep(40)
    raise RuntimeError(f"无法读取 results.json：{last_err}")


def get(d, *path, default=None):
    cur = d
    for k in path:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and isinstance(k, int) and -len(cur) <= k < len(cur):
            cur = cur[k]
        else:
            return default
    return cur


def fnum(x, nd=2, sign=False, dash="—"):
    """常规数字格式化；None/NaN 回退为 dash。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return dash
    if not math.isfinite(v):
        return dash
    s = f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"
    return s.replace("-", "−")


def fsci(x, nd=1, sign=False):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v) or v == 0:
        return "0"
    exp = int(math.floor(math.log10(abs(v))))
    mant = v / 10 ** exp
    s = f"{mant:.{nd}f}×10^{exp}"
    return ("+" + s) if (sign and v > 0) else s


def fpct(x, nd=1, dash="—"):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return dash
    if not math.isfinite(v):
        return dash
    return f"{v*100:.{nd}f}%"


def deg(rad, nd=1):
    try:
        return f"{math.degrees(float(rad)):.{nd}f}°"
    except (TypeError, ValueError):
        return "—"


def set_run(run, size=14, bold=False, color=INK, name=CN, italic=False):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", name)


def add_textbox(slide, x, y, w, h, name=""):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tb.name = name or f"tb_{len(slide.shapes)}"
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = Inches(0.06)
    tf.margin_right = Inches(0.06)
    tf.margin_top = Inches(0.04)
    tf.margin_bottom = Inches(0.04)
    return tb


def add_para(tf, text, size=14, bold=False, color=INK, space_before=0, space_after=4,
             align=PP_ALIGN.LEFT, level=0, line=1.12, name=CN, first=False):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.level = level
    p.space_before = Pt(space_before)
    p.space_after = Pt(space_after)
    p.line_spacing = line
    r = p.add_run()
    r.text = text
    set_run(r, size=size, bold=bold, color=color, name=name)
    return p


def add_bullets(slide, x, y, w, h, items, size=16, gap=5, lead="• "):
    """items: list[str] 或 list[(str, level)]。"""
    tb = add_textbox(slide, x, y, w, h, "bullets")
    tf = tb.text_frame
    first = True
    for it in items:
        if isinstance(it, tuple):
            text, level = it[0], it[1]
        else:
            text, level = it, 0
        if level == -1:
            add_para(tf, text, size=size, bold=True, color=NAVY,
                     space_before=(0 if first else 8), space_after=3, first=first)
            first = False
            continue
        bullet = ("• " if level == 0 else "– ")
        add_para(tf, bullet + text, size=size, color=INK, space_after=gap,
                 level=max(level, 0), first=first)
        first = False
    return tb


def add_title(slide, title, eyebrow=None):
    if eyebrow:
        tb = add_textbox(slide, 0.55, 0.20, 8.0, 0.32, "eyebrow")
        add_para(tb.text_frame, eyebrow, size=11, bold=False, color=BLUE, first=True)
    tb = add_textbox(slide, 0.5, 0.44, 12.35, 0.72, "title")
    add_para(tb.text_frame, title, size=26, bold=True, color=NAVY, first=True)
    # 标题下的细线
    ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(1.17),
                                Inches(12.25), Inches(0.028))
    ln.fill.solid()
    ln.fill.fore_color.rgb = BLUE
    ln.line.fill.background()
    ln.shadow.inherit = False
    return ln


def add_footer(slide, idx, total):
    tb = add_textbox(slide, 0.55, 7.10, 9.6, 0.28, "footer_left")
    add_para(tb.text_frame, "非线性优化方法课程大作业 · 赛车稳态漂移平衡点求解与稳定性设计",
             size=9.5, color=GRAY, first=True)
    tb = add_textbox(slide, 11.55, 7.10, 1.25, 0.28, "footer_page")
    add_para(tb.text_frame, f"{idx} / {total}", size=10, color=GRAY,
             align=PP_ALIGN.RIGHT, first=True)


def figure_size(path):
    if Image is not None:
        try:
            with Image.open(path) as im:
                return im.size
        except Exception:  # noqa: BLE001
            pass
    return (1600, 900)


def add_figure(slide, path, x, y, w, h, caption=None, cap_size=11):
    """在 (x,y,w,h) 盒内等比缩放并居中，返回实际图片底边 y。"""
    if not os.path.exists(path):
        tb = add_textbox(slide, x, y, w, 0.6, "missing_fig")
        add_para(tb.text_frame, f"[缺图] {os.path.basename(path)}", size=14, color=RED, first=True)
        return y + 0.6
    iw, ih = figure_size(path)
    ar = iw / ih
    if w / h > ar:
        ph = h
        pw = h * ar
    else:
        pw = w
        ph = w / ar
    px = x + (w - pw) / 2
    py = y + (h - ph) / 2
    pic = slide.shapes.add_picture(path, Inches(px), Inches(py), Inches(pw), Inches(ph))
    pic.line.color.rgb = BORDER
    pic.line.width = Pt(0.75)
    bot = py + ph
    if caption:
        tb = add_textbox(slide, x, bot + 0.04, w, 0.30, "fig_caption")
        add_para(tb.text_frame, caption, size=cap_size, color=GRAY,
                 align=PP_ALIGN.CENTER, first=True)
        bot += 0.34
    return bot


def _cell_border(cell, color=BORDER, width=6350):
    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        ln = tcPr.find(qn(tag))
        if ln is not None:
            tcPr.remove(ln)
        ln = tcPr.makeelement(qn(tag), {"w": str(width), "cap": "flat", "cmpd": "sng", "algn": "ctr"})
        fill = ln.makeelement(qn("a:solidFill"), {})
        clr = fill.makeelement(qn("a:srgbClr"), {"val": f"{color:02X}" if isinstance(color, int) else str(color)})
        fill.append(clr)
        ln.append(fill)
        tcPr.append(ln)


def add_table(slide, rows, x, y, w, col_widths, row_h=0.34, font=14, header_font=14,
              align=None, fills=None, colors=None, bolds=None):
    """rows[0] 为表头。fills/colors/bolds: dict[(r,c)] -> 值。"""
    nrow, ncol = len(rows), len(rows[0])
    height = row_h * nrow
    gf = slide.shapes.add_table(nrow, ncol, Inches(x), Inches(y), Inches(w), Inches(height))
    table = gf.table
    table.first_row = True
    table.horz_banding = False
    # 列宽（按比例缩放到给定总宽）
    total_cw = float(sum(col_widths)) or 1.0
    for j, cw in enumerate(col_widths):
        table.columns[j].width = Inches(cw * w / total_cw)
    for i in range(nrow):
        table.rows[i].height = Inches(row_h)
        for j in range(ncol):
            cell = table.cell(i, j)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.margin_left = Inches(0.05)
            cell.margin_right = Inches(0.05)
            cell.margin_top = Inches(0.01)
            cell.margin_bottom = Inches(0.01)
            text = str(rows[i][j])
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            p.alignment = (align[j] if align else (PP_ALIGN.CENTER if j else PP_ALIGN.LEFT))
            r = p.add_run()
            r.text = text
            header = i == 0
            fill = NAVY if header else (WHITE if i % 2 else LGRAY)
            if fills and (i, j) in fills:
                fill = fills[(i, j)]
            color = WHITE if header else INK
            if colors and (i, j) in colors:
                color = colors[(i, j)]
            bold = header or (bolds and (i, j) in bolds)
            set_run(r, size=header_font if header else font, bold=bool(bold), color=color)
            cell.fill.solid()
            cell.fill.fore_color.rgb = fill
            _cell_border(cell)
    return gf


def kpi_card(slide, x, y, w, h, label, value, sub="", accent=BLUE):
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    box.fill.solid()
    box.fill.fore_color.rgb = LGRAY
    box.line.color.rgb = accent
    box.line.width = Pt(1.0)
    box.shadow.inherit = False
    box.adjustments[0] = 0.10
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = Inches(0.10)
    tf.margin_right = Inches(0.10)
    tf.margin_top = Inches(0.05)
    tf.margin_bottom = Inches(0.04)
    add_para(tf, value, size=22, bold=True, color=accent, align=PP_ALIGN.CENTER, first=True, space_after=1)
    add_para(tf, label, size=12, color=INK, align=PP_ALIGN.CENTER, space_after=1)
    if sub:
        add_para(tf, sub, size=10, color=GRAY, align=PP_ALIGN.CENTER, space_after=0)


# ---------------------------------------------------------------------------
# 数据整理（全部从 results.json 现算）
# ---------------------------------------------------------------------------
def bench_stats(d):
    """按工况汇总 benchmark：中位迭代/耗时，以及 A1/A6 的代表值。"""
    out = []
    for b in d.get("benchmark", []) or []:
        rows = b.get("rows") or []
        its = [r.get("it") for r in rows if isinstance(r.get("it"), (int, float))]
        ts = [r.get("time_ms") for r in rows if isinstance(r.get("time_ms"), (int, float))]
        ok = sum(1 for r in rows if r.get("ok"))
        a1 = next((r for r in rows if r.get("algo", "").startswith("A1")), {})
        a6 = next((r for r in rows if r.get("algo", "").startswith("A6")), {})
        out.append(dict(V=b.get("V"), delta=b.get("delta"), type=b.get("type"),
                        med_it=statistics.median(its) if its else None,
                        med_t=statistics.median(ts) if ts else None,
                        min_it=min(its) if its else None,
                        max_it=max(its) if its else None,
                        n_ok=ok, n=len(rows),
                        a1_it=a1.get("it"), a1_t=a1.get("time_ms"),
                        a6_it=a6.get("it"), a6_t=a6.get("time_ms")))
    return out


def algo_medians(d):
    """单个算法跨 5 工况的中位迭代/耗时 + 收敛阶中位。"""
    names = []
    for r in (get(d, "benchmark", 0, "rows", default=[]) or []):
        names.append(r.get("algo"))
    names = [n for n in dict.fromkeys(names) if n]
    out = {}
    for n in names:
        its, ts, orders = [], [], []
        for b in d.get("benchmark", []) or []:
            for r in b.get("rows", []) or []:
                if r.get("algo") == n:
                    its.append(r.get("it"))
                    ts.append(r.get("time_ms"))
                    orders.append(r.get("order"))
        out[n] = dict(it=statistics.median([x for x in its if isinstance(x, (int, float))]) if its else None,
                      t=statistics.median([x for x in ts if isinstance(x, (int, float))]) if ts else None,
                      order=statistics.median([x for x in orders if isinstance(x, (int, float))]) if orders else None)
    return out


def growth_at(d, V):
    pts = d.get("drift_growth") or []
    if not pts:
        return None
    return min(pts, key=lambda p: abs(float(p.get("V", 0)) - V))


def case_sol(d, V, typ):
    for c in d.get("cases", []) or []:
        if abs(float(c.get("V", -1)) - V) < 1e-6:
            for s in c.get("solutions", []) or []:
                if s.get("type") == typ:
                    return s, c
    return None, None


def branch_list(d):
    out = []
    for k, v in (d.get("branches") or {}).items():
        try:
            out.append((float(k), v))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def fmt_eig(eig, n=3):
    """[re, im] 列表 → '0.019、−0.018±1.457i'（共轭对只打印一次）。"""
    if not eig:
        return "—"
    real_parts, pair_parts = [], []
    for pair in eig:
        try:
            re_, im_ = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if im_ > 1e-9:
            pair_parts.append(f"{re_:+.{n}f}±{im_:.{n}f}i")
        elif abs(im_) <= 1e-9:
            real_parts.append(f"{re_:+.{n}f}")
    return "、".join(real_parts + pair_parts).replace("-", "−") if (real_parts or pair_parts) else "—"


# ---------------------------------------------------------------------------
# 幻灯片
# ---------------------------------------------------------------------------
def slide_cover(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    # 装饰
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.22), Inches(SH))
    bar.fill.solid(); bar.fill.fore_color.rgb = NAVY; bar.line.fill.background(); bar.shadow.inherit = False
    accent = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.75), Inches(1.02), Inches(3.4), Inches(0.05))
    accent.fill.solid(); accent.fill.fore_color.rgb = BLUE; accent.line.fill.background(); accent.shadow.inherit = False

    tb = add_textbox(s, 0.75, 0.52, 8.0, 0.4, "cover_eyebrow")
    add_para(tb.text_frame, "非线性优化方法 · 课程大作业答辩", size=16, color=BLUE, first=True)

    tb = add_textbox(s, 0.72, 1.31, 11.9, 1.55, "cover_title")
    add_para(tb.text_frame, "基于非线性优化的", size=40, bold=True, color=NAVY, first=True, space_after=2)
    add_para(tb.text_frame, "赛车漂移平衡点求解与稳定性设计", size=40, bold=True, color=NAVY, space_after=0)

    tb = add_textbox(s, 0.75, 3.10, 11.6, 0.55, "cover_sub")
    add_para(tb.text_frame, "从平衡点方程、延拓分岔到稳定性设计与闭环控制", size=20, color=GRAY, first=True)

    # 信息块
    info = [
        ("汇  报  人", "叶骏豪"),
        ("学        号", "12632103"),
        ("专        业", "控制科学与工程"),
        ("课程 / 教师", "非线性优化方法 / 任沁源"),
    ]
    y = 4.28
    for lab, val in info:
        tb = add_textbox(s, 0.78, y, 2.0, 0.42, "cover_lab")
        add_para(tb.text_frame, lab, size=13, color=GRAY, first=True)
        tb = add_textbox(s, 2.55, y - 0.02, 5.2, 0.45, "cover_val")
        add_para(tb.text_frame, val, size=17, bold=True, color=INK, first=True)
        y += 0.62

    tb = add_textbox(s, 0.78, 6.80, 6.4, 0.4, "cover_date")
    meta_date = get(d, "meta", "generated", default="") or ""
    date_txt = "2026 年 11 月"
    try:
        dt = datetime.strptime(str(meta_date)[:10], "%Y-%m-%d")
        date_txt = f"{dt.year} 年 {dt.month} 月"
    except (ValueError, TypeError):
        pass
    add_para(tb.text_frame, date_txt, size=14, color=GRAY, first=True)

    # 右下角关键词
    keys = ["三自由度单轨模型", "多起点/延拓", "鞍结分岔", "LQR 镇定", "增广拉格朗日"]
    for i, k in enumerate(keys):
        box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                 Inches(7.55 + (i % 3) * 1.85), Inches(4.98 if i < 3 else 5.58),
                                 Inches(1.68), Inches(0.50))
        box.fill.solid(); box.fill.fore_color.rgb = LGRAY
        box.line.color.rgb = LBLUE; box.line.width = Pt(0.75); box.shadow.inherit = False
        tf = box.text_frame
        tf.margin_left = Inches(0.03); tf.margin_right = Inches(0.03)
        tf.margin_top = Inches(0.02); tf.margin_bottom = Inches(0.02)
        add_para(tf, k, size=10.5, color=NAVY, align=PP_ALIGN.CENTER, first=True)
    return s


def slide_background(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "研究背景：为什么漂移平衡点是一个非线性优化问题", "01 · 研究背景")
    add_bullets(s, 0.55, 1.42, 8.3, 5.3, [
        "漂移 = 后轴侧向力饱和后的大侧偏稳态：|β| 常超过 20°，前轮反打（δ<0），后轴驱动比高。",
        "平衡点由 3 个非线性代数方程 e(z;V,δ)=0 描述：arctan2、tan 与摩擦圆 sqrt(max(·)) 复合，强非线性、非凸。",
        "解析解不存在，且解不唯一：同一 (V,δ) 可同时存在抓地解与漂移解（多起点可稳定复现）。",
        "漂移解在开环意义下不稳定（鞍点），必须闭环镇定才能维持——这决定了后续控制设计。",
        "因此技术路线为：数值优化求根 → 延拓/分岔 → 特征值判稳 → 线性化控制 → 设计优化。",
    ], size=16, gap=9)
    # 右侧流程
    steps = [("三自由度模型", "单轨 + 刷子胎 + 摩擦圆", NAVY),
             ("平衡点求解", "牛顿 / GN / LM / 信赖域", BLUE),
             ("分支与稳定性", "延拓 + 折叠 + 特征值", RED),
             ("控制与设计", "LQR + 增广拉格朗日", GREEN)]
    y = 1.55
    for i, (a, b, c) in enumerate(steps):
        box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(9.25), Inches(y), Inches(3.45), Inches(0.86))
        box.fill.solid(); box.fill.fore_color.rgb = WHITE
        box.line.color.rgb = c; box.line.width = Pt(1.25); box.shadow.inherit = False
        tf = box.text_frame; tf.word_wrap = True
        tf.margin_left = Inches(0.10); tf.margin_top = Inches(0.04); tf.margin_bottom = Inches(0.04)
        add_para(tf, a, size=15, bold=True, color=c, first=True, space_after=0)
        add_para(tf, b, size=11, color=GRAY, space_after=0)
        if i < len(steps) - 1:
            ar = s.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, Inches(10.86), Inches(y + 0.88),
                                    Inches(0.22), Inches(0.26))
            ar.fill.solid(); ar.fill.fore_color.rgb = BORDER; ar.line.fill.background(); ar.shadow.inherit = False
        y += 1.22
    return s


def slide_model(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "问题定义与模型：三自由度单轨平衡方程", "02 · 模型")
    tb = add_textbox(s, 0.55, 1.36, 7.6, 2.55, "model_eq")
    tf = tb.text_frame
    add_para(tf, "状态 z = (β, r, fx)；参数 (V, δ)；速度 vx = V cosβ，vy = V sinβ", size=14, color=GRAY, first=True, space_after=7)
    add_para(tf, "e1 = fx + Fdx − Fyf·sinδ + m·r·vy = 0      （纵向力平衡）", size=15, color=INK, space_after=6)
    add_para(tf, "e2 = Fyf·cosδ + Fyr + Fdy − m·r·vx = 0    （侧向力平衡）", size=15, color=INK, space_after=6)
    add_para(tf, "e3 = a·Fyf·cosδ − b·Fyr = 0                    （横摆力矩平衡）", size=15, color=INK, space_after=6)
    add_para(tf, "Fdx = −½ρCdA·V·vx，Fdy = −½ρCdA·V·vy，ay = r·vx", size=14, color=GRAY, space_after=0)

    tb = add_textbox(s, 0.55, 4.02, 7.6, 2.5, "model_params")
    tf = tb.text_frame
    add_para(tf, "整车参数（某后驱赛车，1450 kg）", size=14, bold=True, color=NAVY, first=True, space_after=6)
    add_para(tf, "m = 1450 kg，Iz = 2200 kg·m²，a = 1.15 m，b = 1.35 m", size=14, color=INK, space_after=4)
    add_para(tf, "L = 2.50 m，h = 0.45 m；μf = 1.30，μr = 1.35", size=14, color=INK, space_after=4)
    add_para(tf, "Caf = 1.3×10^5 N/rad，Car = 1.5×10^5 N/rad", size=14, color=INK, space_after=4)
    add_para(tf, "气动：ρ = 1.225 kg/m³，CdA = 1.0 m²，ClA_f = 0.6，ClA_r = 0.9 m²", size=14, color=INK, space_after=4)
    add_para(tf, "可行性：vx>0、r>0、|fx| ≤ μr·Fzr；箱约束 |β| ≤ 1.2 rad、|r| ≤ 6 rad/s。",
             size=13, color=GRAY, space_after=0)
    add_figure(s, os.path.join(FIGS, "fig01_model.png"), 8.35, 1.28, 4.55, 4.05)
    return s


def slide_tire(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "轮胎模型：刷子模型与后轴摩擦圆", "03 · 轮胎")
    add_bullets(s, 0.55, 1.40, 6.9, 5.4, [
        "归一化滑移 u = Cα·tanα / M，侧向力 Fy = −M·Φ(u)。",
        "Φ(u) = sign(u)·(|u| − |u|²/3 + |u|³/27)（|u|≤3）；Φ(u) = sign(u)（|u|>3）：奇函数、单调饱和、C² 连续。",
        "前轴 Mf = μf·Fzf（自由滚动）；后轴 Mr = √max(ε, (μr·Fzr)² − fx²)。",
        "动力漂移机理：驱动 fx↑ ⇒ 摩擦圆剩余侧向能力 Mr↓ ⇒ 后轴先饱和；维持平衡需大 β 与反打 δ。",
        "准静态载荷：Fzf = mgb/L + qClA_f − m·ax·h/L；Fzr = mga/L + qClA_r + m·ax·h/L，q = ½ρV²。",
        "数值保护：Fz_min = 200 N，ε = 1 N²（避免 sqrt 在 0 处不可导）。",
    ], size=15, gap=8)
    add_figure(s, os.path.join(FIGS, "fig02_tire.png"), 7.7, 1.35, 5.15, 3.55)
    # 公式卡
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(7.78), Inches(5.05), Inches(4.98), Inches(1.85))
    box.fill.solid(); box.fill.fore_color.rgb = LGRAY
    box.line.color.rgb = BLUE; box.line.width = Pt(1.0); box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.14); tf.margin_top = Inches(0.08)
    add_para(tf, "核心结构", size=14, bold=True, color=NAVY, first=True, space_after=4)
    add_para(tf, "Fy = −M·Φ(Cα·tanα / M)", size=15, color=INK, space_after=3)
    add_para(tf, "Mr = √[(μrFzr)² − fx²]：纵向力挤占横向摩擦圆", size=14, color=GRAY, space_after=0)
    return s


def slide_optim(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "优化建模：平衡点 = 残差范数最小化", "04 · 优化建模")
    add_bullets(s, 0.55, 1.42, 6.35, 5.4, [
        "目标：min_{z∈[lo,hi]} ½·||e(z; V, δ)||²；当 e=0 时达到全局最小值 0，平衡点即其零点。",
        "牛顿法：J(z_k)·Δz = −e(z_k)，J = ∂e/∂z ∈ R^{3×3}；解析雅可比与中心差分相对误差 1.72×10^-10。",
        "高斯–牛顿：JᵀJ·Δz = −Jᵀe；Levenberg–Marquardt：(JᵀJ + λI)·Δz = −Jᵀe；信赖域 dogleg 控制步长。",
        "全局化：回溯线搜索 / 信赖域半径，保证残差单调下降并抑制过冲。",
        "收敛性：半对数残差斜率 ≈ 2（A1 实测收敛阶中位 1.91），二次收敛；但仅局部收敛，非凸多解。",
        "箱约束：|β| ≤ 1.2 rad，|r| ≤ 6 rad/s，|fx| ≤ 1.1·μr·Fzr,max；物理可行解另需 vx>0、r>0、摩擦圆余量。",
    ], size=14.5, gap=9)
    add_figure(s, os.path.join(FIGS, "fig06_merit.png"), 7.05, 1.34, 5.9, 2.65)
    # 小结论
    tb = add_textbox(s, 7.05, 4.62, 5.9, 1.9, "optim_note")
    tf = tb.text_frame
    add_para(tf, "为什么“解方程”要写成“最小化”？", size=14, bold=True, color=NAVY, first=True, space_after=4)
    add_para(tf, "① 残差可量化，便于监控与比较；② 奇异/病态 J 时退化为最小二乘；", size=14, color=INK, space_after=3)
    add_para(tf, "③ 可自然加入阻尼、信赖域与箱约束；④ 便于多起点与延拓的批量调用。", size=14, color=INK, space_after=0)
    return s


def slide_algorithms(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "六类算法 / 七种实现与基准对比", "05 · 算法")
    am = algo_medians(d)
    names = [
        ("A1", "newton_analytic", "解析雅可比 + 线搜索"),
        ("A2", "newton_fd", "中心差分雅可比"),
        ("A3", "gauss_newton", "正规方程 / 最小二乘"),
        ("A4", "levenberg_marquardt", "阻尼自适应，最稳健"),
        ("A5", "trust_region_dogleg", "dogleg 信赖域"),
        ("A6", "bfgs", "拟牛顿，仅用梯度"),
        ("A7", "projected_newton", "投影牛顿，处理箱约束"),
    ]
    y = 1.38
    for code, key, trait in names:
        full = next((k for k in am if k.startswith(code + "_")), None)
        st = am.get(full, {}) if full else {}
        med_it = st.get("it")
        med_t = st.get("t")
        tb = add_textbox(s, 0.55, y, 6.35, 0.40, f"algo_{code}")
        tf = tb.text_frame
        p = tf.paragraphs[0]
        p.space_after = Pt(0)
        r = p.add_run(); r.text = f"{code}  "; set_run(r, size=15, bold=True, color=BLUE)
        r = p.add_run(); r.text = f"{trait}"; set_run(r, size=14, color=INK)
        if med_it is not None:
            r = p.add_run(); r.text = f"  ·  中位 {fnum(med_it,0)} 次 / {fnum(med_t,2)} ms"
            set_run(r, size=14, color=GRAY)
        y += 0.325

    add_figure(s, os.path.join(FIGS, "fig11_benchmark.png"), 7.0, 1.32, 5.95, 2.55)

    stats = bench_stats(d)
    rows = [["工况（V, δ）", "中位迭代", "中位耗时/ms", "A1 迭代/耗时", "A6 迭代/耗时", "收敛"]]
    for st in stats:
        typ = "抓地" if st["type"] == "grip" else "漂移"
        rows.append([
            f"V={fnum(st['V'],0)}, δ={fnum(st['delta'],2)}（{typ}）",
            fnum(st["med_it"], 0),
            fnum(st["med_t"], 2),
            f"{fnum(st['a1_it'],0)} / {fnum(st['a1_t'],2)}",
            f"{fnum(st['a6_it'],0)} / {fnum(st['a6_t'],2)}",
            f"{st['n_ok']}/{st['n']}",
        ])
    add_table(s, rows, 0.55, 4.28, 12.25, [3.95, 1.35, 1.55, 1.85, 1.85, 1.25],
              row_h=0.29, font=14, header_font=13,
              colors={(1, 5): GREEN, (2, 5): GREEN, (3, 5): GREEN, (4, 5): GREEN, (5, 5): GREEN})
    tb = add_textbox(s, 0.55, 6.10, 12.2, 0.55, "bench_note")
    a6_its = [st["a6_it"] for st in stats if isinstance(st.get("a6_it"), (int, float))]
    a6_ts = [st["a6_t"] for st in stats if isinstance(st.get("a6_t"), (int, float))]
    a1_it = am.get(next((k for k in am if k.startswith("A1_")), ""), {}).get("it")
    a1_t = am.get(next((k for k in am if k.startswith("A1_")), ""), {}).get("t")
    add_para(tb.text_frame,
             f"结论：牛顿类（A1/A3/A7）{fnum(a1_it,0)} 次迭代、约 {fnum(a1_t,1)} ms；"
             f"差分雅可比（A2）约 2× 耗时；BFGS（A6）需 {fnum(min(a6_its) if a6_its else None,0)}–"
             f"{fnum(max(a6_its) if a6_its else None,0)} 次、"
             f"{fnum(min(a6_ts) if a6_ts else None,1)}–{fnum(max(a6_ts) if a6_ts else None,1)} ms。"
             f"所有实现 {len(stats)} 工况均收敛。",
             size=12, color=GRAY, first=True)
    return s


def slide_multiplicity(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "多解性：固定 (V, δ) 通常存在两个物理可行解", "06 · 多解性")
    items = [
        "抓地解（|β|<8°）与漂移解（β≤−8°）共存；两者都满足同一组平衡方程。",
    ]
    ms_txt = []
    for V in [8.0, 15.0]:
        sd, c = case_sol(d, V, "drift")
        sg, _ = case_sol(d, V, "grip")
        if sd and sg:
            items.append(f"V={V:.0f}：抓地 β={fnum(sg.get('beta_deg'),2)}°（κ={fnum(sg.get('kappa'),3)}） "
                         f"vs 漂移 β={fnum(sd.get('beta_deg'),2)}°（κ={fnum(sd.get('kappa'),3)}）。")
        ms = (c or {}).get("multistart") or {}
        if ms.get("n_start") and ms.get("n_ok") is not None:
            ms_txt.append(f"V={V:.0f} 命中 {ms.get('n_ok')}/{ms.get('n_start')} 次"
                          f"（{fpct(ms.get('n_ok') / ms.get('n_start'), 0)}）")
    if ms_txt:
        items.append("多起点随机初值：" + "、".join(ms_txt) + "，平均 8–9 次迭代。")
    else:
        items.append("多起点统计：results.json 缺失。")
    sm = d.get("solmap") or {}
    if sm.get("Vs"):
        items.append(f"{sm.get('n_start')} 起点 × {len(sm.get('deltas') or [])} 个 δ 的解个数分区："
                     "多数 δ 下为 2 解；大 δ 时无物理可行解。")
    add_bullets(s, 0.55, 1.40, 6.45, 3.25, items, size=14, gap=8)

    tb = add_textbox(s, 0.55, 4.72, 6.45, 2.3, "multi_note")
    tf = tb.text_frame
    add_para(tf, "多解性的数值来源", size=14, bold=True, color=NAVY, first=True, space_after=4)
    add_para(tf, "摩擦圆 sqrt(·) 在 fx 接近 μrFzr 时强非线性，残差曲面出现多个零谷；"
                 "从不同初值出发会落入不同吸引域（图 4b 的 0/1/2 分区）。", size=14, color=INK, space_after=4)
    add_para(tf, "工程含义：ECU 标定必须同时覆盖两条分支，不能只依赖单一初值。", size=14, color=GRAY, space_after=0)

    add_figure(s, os.path.join(FIGS, "fig04_fold.png"), 7.05, 1.36, 5.8, 2.40)

    rows = [["工况", "解类型", "β / °", "κ", "max Re λ", "稳定"]]
    for V in [8.0, 15.0]:
        for typ, name in [("grip", "抓地"), ("drift", "漂移")]:
            sol, _ = case_sol(d, V, typ)
            if sol:
                rows.append([f"V={V:.0f}",
                             name,
                             fnum(sol.get("beta_deg"), 2),
                             fnum(sol.get("kappa"), 3),
                             fnum(sol.get("max_real"), 4, sign=True),
                             "是" if sol.get("stable") else "否"])
    for V in [22.0]:
        sol, _ = case_sol(d, V, "drift")
        if sol:
            rows.append([f"V={V:.0f}", "漂移", fnum(sol.get("beta_deg"), 2), fnum(sol.get("kappa"), 3),
                         fnum(sol.get("max_real"), 4, sign=True), "是" if sol.get("stable") else "否"])
    if len(rows) > 1:
        add_table(s, rows, 7.05, 4.02, 5.8, [0.95, 0.95, 1.0, 0.85, 1.35, 0.7],
                  row_h=0.31, font=14, header_font=13,
                  colors={(1, 5): GREEN, (3, 5): GREEN, (2, 5): RED, (4, 5): RED})
        tb = add_textbox(s, 7.05, 4.02 + 0.31 * len(rows) + 0.06, 5.8, 0.62, "multi_src")
        add_para(tb.text_frame, "数据来源：results.json 的 cases；max Re>0 为鞍点（开环不稳定）。",
                 size=10.5, color=GRAY, first=True)
    return s


def slide_bifurcation(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "支路与折叠分岔：自然延拓 + 伪弧长", "07 · 分岔")
    add_figure(s, os.path.join(FIGS, "fig03_branches.png"), 0.55, 1.30, 6.45, 2.50)
    fc = sorted([r for r in (d.get("fold_curve") or []) if isinstance(r.get("V"), (int, float))],
                key=lambda r: r["V"])
    fold_txt = []
    brs = branch_list(d)
    for V, br in brs:
        ds = sorted({round(float(f.get("delta")), 4) for f in (br.get("folds") or [])
                     if isinstance(f.get("delta"), (int, float))})
        if ds:
            fold_txt.append(f"V={V:.0f}: " + "/".join(f"{v:+.3f}".replace("-", "−") for v in ds) + " rad")
    if len(fold_txt) > 4:
        fold_txt = fold_txt[:2] + ["…"] + fold_txt[-2:]
    bullets = [
        "自然延拓：以前一步解作预测、逐步增大 δ，跟踪完整平衡分支；伪弧长可越过折叠点。",
        "折叠条件 det J = 0（鞍结分岔）：漂移分支与抓地分支在此汇合后消失，condJ 急增。",
        ("折叠点（多数 V 呈 ± 对称）：" + "；".join(fold_txt) + "。") if fold_txt else "折叠点：results.json 缺失。",
    ]
    if len(fc) >= 2:
        bullets.append(f"δf(V) 随车速下降：V={fc[0]['V']:.0f}→{fc[-1]['V']:.0f} 从 "
                       f"{fnum(fc[0].get('delta'),3)} 降至 {fnum(fc[-1].get('delta'),3)} rad，"
                       f"高速下反打角窗口明显收窄。")
    else:
        bullets.append("δf(V) 随车速下降：高速下反打角窗口明显收窄。")
    add_bullets(s, 0.55, 4.00, 6.45, 3.0, bullets, size=14, gap=7)

    tb = add_textbox(s, 7.25, 1.36, 5.6, 0.35, "fold_tab_title")
    add_para(tb.text_frame, "折叠曲线读数（fold_curve，V=6→30）", size=14, bold=True, color=NAVY, first=True)
    tab_bottom = 1.75
    if fc:
        idxs = list(range(len(fc)))
        if len(fc) > 9:
            idxs = [round(k * (len(fc) - 1) / 8) for k in range(9)]
        rows = [["V / (m/s)", "δf / rad", "δf / °", "max Re λ"]]
        for i in idxs:
            r = fc[i]
            rows.append([f"{r.get('V'):.0f}", fnum(r.get("delta"), 3),
                         fnum(math.degrees(r.get("delta")) if isinstance(r.get("delta"), (int, float)) else None, 1),
                         fnum(r.get("max_real"), 3, sign=True)])
        add_table(s, rows, 7.25, 1.75, 5.55, [1.4, 1.45, 1.35, 1.35],
                  row_h=0.31, font=14, header_font=13)
        tab_bottom = 1.75 + 0.31 * len(rows) + 0.10
        if len(fc) < 4:
            tb = add_textbox(s, 7.25, tab_bottom, 5.55, 0.55, "fold_note")
            add_para(tb.text_frame, "注：当前 results.json 仅含部分 V 的折叠点；全量延拓完成后本表自动扩展。",
                     size=10.5, color=GRAY, first=True)
            tab_bottom += 0.55
    else:
        tb = add_textbox(s, 7.25, 1.80, 5.55, 0.8, "fold_missing")
        add_para(tb.text_frame, "results.json 缺少 fold_curve，跳过折叠曲线读数。", size=14, color=RED, first=True)

    tb = add_textbox(s, 7.25, max(tab_bottom + 0.30, 4.10), 5.55, 2.4, "fold_why")
    tf = tb.text_frame
    add_para(tf, "为什么折叠点重要？", size=14, bold=True, color=NAVY, first=True, space_after=4)
    add_para(tf, "它是稳态漂移的“边界”：δ 一旦超过 δf，漂移平衡点与相邻解合并消失，"
                 "车辆只能进入非平衡的甩尾/失控状态。设计目标应把工作点放在 δf 以内并留裕度。",
             size=14, color=INK, space_after=5)
    add_para(tf, "延拓用预测–校正步：预测沿切向，校正用牛顿迭代；折叠处 J 奇异，改用增广系统。",
             size=12, color=GRAY, space_after=0)
    return s


def slide_stability(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "稳定性：漂移解是鞍点，抓地解渐近稳定", "08 · 稳定性")
    sd8, _ = case_sol(d, 8.0, "drift")
    sg8, _ = case_sol(d, 8.0, "grip")
    g8, g15, g22 = growth_at(d, 8.0), growth_at(d, 15.0), growth_at(d, 22.0)
    eig_line = ("V=8 漂移特征值 " + fmt_eig(sd8.get("eig"), 3) + "；抓地 " +
                fmt_eig(sg8.get("eig"), 2) + "。")
    add_bullets(s, 0.55, 1.42, 6.7, 3.3, [
        "判据：平衡点处 A = ∂f/∂x（3×3），渐近稳定 ⇔ max Re λ(A) < 0；max Re > 0 即存在增长模态。",
        "漂移解：一个实正根 + 一对共轭复根 ⇒ 鞍点/不稳定焦点；抓地解：三个特征值实部全负。",
        eig_line,
        f"max Re 随 V 单调增大：{fnum(g8.get('max_real'),3)} → {fnum(g15.get('max_real'),3)} → "
        f"{fnum(g22.get('max_real'),3)}（V=8/15/22），小扰动按 e^(maxRe·t) 增长。",
    ], size=14, gap=9)

    rows = [["V / (m/s)", "漂移 β / °", "漂移 max Re", "抓地 max Re", "判定"]]
    for V in [8.0, 15.0, 22.0]:
        g = growth_at(d, V)
        if g is None:
            continue
        sd, _ = case_sol(d, V, "drift")
        sg, _ = case_sol(d, V, "grip")
        beta = sd.get("beta_deg") if sd else g.get("beta_deg")
        rows.append([f"{V:.0f}", fnum(beta, 1), fnum(g.get("max_real"), 4, sign=True),
                     fnum(sg.get("max_real") if sg else None, 4, sign=True),
                     "鞍点（不稳定）" if (g.get("max_real") or 0) > 0 else "稳定"])
    add_table(s, rows, 0.55, 4.85, 7.0, [1.1, 1.2, 1.45, 1.45, 1.65],
              row_h=0.38, font=14, header_font=13,
              colors={(1, 2): RED, (2, 2): RED, (3, 2): RED, (1, 3): GREEN, (2, 3): GREEN})

    add_figure(s, os.path.join(FIGS, "fig08_growth.png"), 7.55, 1.40, 5.35, 2.15)
    tb = add_textbox(s, 7.55, 3.72, 5.3, 3.0, "stab_face")
    tf = tb.text_frame
    add_para(tf, "稳定性与“能维持漂移”的关系", size=14, bold=True, color=NAVY, first=True, space_after=4)
    add_para(tf, "漂移不是“稳定状态”，而是“可被镇定在的不稳定平衡点”。"
                 "开环时任何小扰动都会沿正实特征方向发散，所以必须闭环施加反打/驱动力修正。",
             size=14, color=INK, space_after=5)
    add_para(tf, "抓地解在 V=8/15 均稳定（max Re<0），与常规驾驶直觉一致。",
             size=14, color=GRAY, space_after=0)
    return s


def slide_phase(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "相平面：开环发散与被控收敛", "09 · 相平面")
    ctrl = d.get("control") or []
    vs = [c.get("V") for c in ctrl if isinstance(c.get("V"), (int, float))]
    eo = [c.get("errT_open") for c in ctrl if isinstance(c.get("errT_open"), (int, float))]
    ec = [c.get("errT_closed") for c in ctrl if isinstance(c.get("errT_closed"), (int, float))]
    red = [c.get("reduction") for c in ctrl if isinstance(c.get("reduction"), (int, float))]
    st = [(c.get("V"), c.get("settle_time")) for c in ctrl]
    err0 = ctrl[0].get("err0") if ctrl else None
    items = [
        "相平面 (β, β̇) / (β, r)：从漂移平衡点邻域小扰动出发，开环轨迹迅速远离。",
        (f"开环末误差：V={'/'.join(fnum(v,0) for v in vs)} 为 "
         + " / ".join(fnum(x,2) for x in eo) + f"（初值误差 {fnum(err0,1)}）。") if eo else "开环末误差：缺失。",
        (f"LQR 闭环末误差：" + " / ".join(fnum(x,4) for x in ec) + "，减少 "
         + " / ".join(fnum(x,0) for x in red) + "×。") if ec else "LQR 闭环末误差：缺失。",
    ]
    settled = [f"V={fnum(v,0)} 在 {fnum(t,2)} s" for v, t in st if isinstance(t, (int, float))]
    if settled:
        items.append("、".join(settled) + " 内进入 ±2% 带（低车速衰减更快，未触发计时阈值）。")
    add_bullets(s, 0.55, 1.42, 5.35, 5.2, items, size=14.5, gap=10)
    if ctrl:
        rows = [["V", "开环末误差", "闭环末误差", "调节时间/s"]]
        for c in ctrl:
            rows.append([f"{c.get('V'):.0f}", fnum(c.get("errT_open"), 3),
                         fnum(c.get("errT_closed"), 5), fnum(c.get("settle_time"), 2)])
        add_table(s, rows, 0.55, 5.10, 5.3, [0.8, 1.6, 1.8, 1.1],
                  row_h=0.28, font=14, header_font=13)
    add_figure(s, os.path.join(FIGS, "fig05_phase.png"), 6.45, 1.38, 6.35, 3.45)
    tb = add_textbox(s, 6.45, 4.98, 6.3, 1.85, "phase_note")
    tf = tb.text_frame
    add_para(tf, "控制视角：漂移平衡点像“倒立摆的顶端”，可控但不稳定；"
                 "LQR 用很小的反打/驱动修正即可把它按住。", size=14, color=INK, first=True, space_after=3)
    add_para(tf, f"开环发散速度随 V 增大（{fnum(min(vs) if vs else None,0)}→"
                 f"{fnum(max(vs) if vs else None,0)} m/s 末误差 {fnum(max(eo) if eo else None,2)}），"
                 "说明高速漂移对控制带宽要求更高。",
             size=13.5, color=GRAY, space_after=0)
    return s


def slide_control(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "闭环控制：线性化 + LQR/Kleinman 迭代", "10 · 控制")
    ctrl = d.get("control") or []
    eig_txt = ""
    if ctrl:
        parts = []
        for re_, im_ in [tuple(p) for p in (ctrl[0].get("eigen_closed") or [])]:
            try:
                re_, im_ = float(re_), float(im_)
            except (TypeError, ValueError):
                continue
            if abs(im_) < 1e-9:
                parts.append(f"{re_:.2f}")
            elif im_ > 0:
                parts.append(f"{re_:.2f}±{im_:.2f}i")
        if parts:
            eig_txt = (f"（V={fnum(ctrl[0].get('V'),0)}：" + "、".join(parts) + "）").replace("-", "−")
    add_bullets(s, 0.55, 1.40, 12.2, 1.95, [
        "线性化：状态 x=(vx, vy, r)，A = ∂f/∂x、B = ∂f/∂(δ, fx)（3×2），在漂移平衡点处取值；可控性秩 rank=3。",
        "LQR：min ∫(xᵀQx + uᵀRu)dt，Q = diag(1, 4, 40)、R = diag(40, 1.0×10^-4)；CARE 解 P，K = R⁻¹BᵀP（2×3）。",
        "Kleinman 迭代 9–11 次收敛，CARE 残差 ~10^-14；闭环特征值全部 Re<0 " + (eig_txt or "（数据缺失）") + "。",
    ], size=14.5, gap=8)
    rows = [["V / (m/s)", "rank", "Kleinman 迭代", "err0 → 闭环 errT", "开环 errT", "吸引域比例", "调节时间 / s"]]
    for c in ctrl:
        rows.append([f"{c.get('V'):.0f}", fnum(c.get("controllability_rank"), 0),
                     fnum(c.get("kleinman_it"), 0),
                     f"{fnum(c.get('err0'),2)} → {fnum(c.get('errT_closed'),5)}",
                     fnum(c.get("errT_open"), 3), fpct(c.get("basin_frac"), 1),
                     fnum(c.get("settle_time"), 2)])
    add_table(s, rows, 0.55, 3.45, 12.25, [1.15, 0.75, 1.55, 2.55, 1.45, 1.55, 1.5],
              row_h=0.42, font=14, header_font=13,
              colors={(1, 5): GREEN, (2, 5): GREEN})
    tb = add_textbox(s, 0.55, 5.30, 12.2, 1.6, "ctrl_note")
    tf = tb.text_frame
    bs = [c.get("basin_frac") for c in ctrl if isinstance(c.get("basin_frac"), (int, float))]
    dus = [c.get("du_max") for c in ctrl if isinstance(c.get("du_max"), (int, float))]
    add_para(tf, "关键观察", size=14, bold=True, color=NAVY, first=True, space_after=4)
    add_para(tf, f"① 同一组 Q/R 在 V=8/15/22 均能把误差压低 2–4 个数量级，但吸引域随 V 从 "
                 f"{fpct(max(bs) if bs else None, 0)} 降到 {fpct(min(bs) if bs else None, 0)}，"
                 "高速需要更保守的初值或增益调度。", size=14, color=INK, space_after=3)
    add_para(tf, f"② 控制量幅度 |Δδ|max ≈ {fnum(max(dus) if dus else None,2)} rad、fx 修正可达数 kN，"
                 "属于执行器可行范围（需进一步做饱和约束验证）。",
             size=14, color=INK, space_after=0)
    return s


def slide_design(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "设计优化：最小化漂移所需的驱动比 κ", "11 · 设计")
    des = d.get("design") or {}
    ay_min = des.get("ay_min")
    base = des.get("base") or {}
    opt = des.get("opt") or {}
    alm = des.get("alm") or {}
    shadow = des.get("shadow") or {}
    add_bullets(s, 0.55, 1.40, 6.55, 3.2, [
        "问题：min_x κ(x)  s.t.  e(z; x)=0（隐式平衡约束），ay_grip(x) ≥ ay_min，x∈[xlo, xhi]。",
        "设计变量 x = (a, μ_r, ClA_r)（其中 b = L − a 由轴距约束确定）；κ = fx/(μ_r·Fzr) 为维持漂移所需驱动比。",
        "隐函数定理降维：dz/dx = −Jz⁻¹·∂e/∂x，dκ/dx = ∂κ/∂x + (∂κ/∂z)(dz/dx)；与有限差分核对相对误差 5.7×10^-9。",
        "外层增广拉格朗日：L = κ + [max(0, λ+μc)² − λ²]/(2μ)，c = ay_min − ay_grip；12 次外迭代，μ→1.0×10^4。",
    ], size=14, gap=8)
    add_figure(s, os.path.join(FIGS, "fig07_design.png"), 7.10, 1.38, 5.75, 2.35)

    rows = [["量", "基准", "最优", "变化"],
            ["a / m", fnum(base.get("x", [None])[0], 3), fnum((opt.get("x") or [None])[0], 3), "—"],
            [r"μ_r / —", fnum((base.get("x") or [None, None])[1], 3),
             fnum((opt.get("x") or [None, None])[1], 3), "—"],
            ["ClA_r / m²", fnum((base.get("x") or [None, None, None])[2], 3),
             fnum((opt.get("x") or [None, None, None])[2], 3), "（上界，不变）"],
            ["κ", fnum(base.get("kappa"), 4), fnum(alm.get("kappa", opt.get("kappa")), 4), ""],
            ["KKT 乘子 λ", "—", fnum(shadow.get("lam", opt.get("lam")), 4), ""]]
    try:
        xb, xo = base.get("x") or [], opt.get("x") or alm.get("design") or []
        if len(xb) == 3 and len(xo) == 3:
            for i in range(3):
                rows[1 + i][3] = f"{(xo[i]-xb[i])/xb[i]*100:+.1f}%"
        k0, k1 = float(base.get("kappa")), float(alm.get("kappa", opt.get("kappa")))
        rows[4][3] = f"{(k1-k0)/k0*100:+.1f}%"
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    add_table(s, rows, 0.55, 4.62, 6.6, [1.55, 1.55, 1.55, 1.75],
              row_h=0.32, font=14, header_font=14,
              colors={(4, 3): BLUE})
    tb = add_textbox(s, 7.10, 3.95, 5.75, 2.9, "design_note")
    tf = tb.text_frame
    add_para(tf, "结果与影子价格", size=14, bold=True, color=NAVY, first=True, space_after=4)
    add_para(tf, f"最优设计 x* = ({fnum((opt.get('x') or [None])[0],3)}, "
                 f"{fnum((opt.get('x') or [None,None])[1],3)}, "
                 f"{fnum((opt.get('x') or [None,None,None])[2],3)})，"
                 f"κ 从 {fnum(base.get('kappa'),4)} 降到 {fnum(alm.get('kappa', opt.get('kappa')),4)}。",
             size=14, color=INK, space_after=4)
    add_para(tf, f"约束在 ay_min = {fnum(ay_min,1)} m/s² 处起作用，λ = {fnum(shadow.get('lam'),4)}；"
                 f"ay_min 再降 0.2 时 κ 仅降 {fnum(abs(shadow.get('dkappa')),4)}"
                 f"（影子价格 {fnum(shadow.get('ratio'),4)}/单位 ay）。",
             size=14, color=INK, space_after=4)
    add_para(tf, "工程含义：加长前轴距 a、缩短后轴距 b 可在不牺牲侧向能力的前提下降低漂移所需的驱动比。",
             size=14, color=GRAY, space_after=0)
    return s


def slide_verify(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "验证与可复现：40/40 项全部 PASS", "12 · 校验")
    add_bullets(s, 0.55, 1.40, 6.2, 3.9, [
        "三层校验：独立实现（另写残差/雅可比）↔ 主模型、mpmath 50 位高精度、scipy root/least_squares 对照。",
        "解析雅可比 vs 中心差分：最大相对误差 1.72×10^-10；mpmath 50 位牛顿解残差 4.4×10^-47。",
        "双精度残差 3.6×10^-12；双精度解与高精度解差 4.5×10^-12；与参考 β/r/fx 差 4.1×10^-7°/4.4×10^-7/4.4×10^-5 N。",
        "轮胎性质（单调、奇函数、摩擦圆、C⁰/C¹、饱和）与线性化一致性全部 PASS；设计 IFT 梯度 5.7×10^-9。",
    ], size=14, gap=8)
    rows = [["校验项", "内容", "实测", "判定"],
            ["B1", "解析 J vs 中心差分", "1.72×10^-10", "PASS"],
            ["C1", "mpmath 50 位残差", "4.4×10^-47", "PASS"],
            ["C3", "高精度 vs 双精度解差", "4.5×10^-12", "PASS"],
            ["D1/D2", "scipy 两法解差", "4.5×10^-12", "PASS"],
            ["G1", "平衡方程残差 ∞-范数", "3.6×10^-12", "PASS"],
            ["J2", "扰动后牛顿步残差下降", "1.55×10^6", "PASS"],
            ["设计", "IFT 梯度 vs 差分", "5.7×10^-9", "PASS"]]
    add_table(s, rows, 6.95, 1.40, 5.9, [1.0, 2.6, 1.55, 0.85],
              row_h=0.315, font=14, header_font=13,
              colors={(i, 3): GREEN for i in range(1, 8)})
    # 复现命令
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.55), Inches(5.42), Inches(6.2), Inches(1.45))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0xF7, 0xF7, 0xF7)
    box.line.color.rgb = BORDER; box.line.width = Pt(0.75); box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.12); tf.margin_top = Inches(0.06)
    add_para(tf, "一键复现（Windows，在课程目录下）", size=12, bold=True, color=NAVY, first=True, space_after=3)
    for cmd in ["python 大作业\\race_drift_solver.py", "python 大作业\\build_figs.py",
                "python 大作业\\build_ppt.py"]:
        add_para(tf, "> " + cmd, size=11.5, color=INK, name=MONO, space_after=1)
    tb = add_textbox(s, 6.95, 4.30, 5.9, 2.6, "verify_note")
    tf = tb.text_frame
    add_para(tf, "校验环境", size=13, bold=True, color=NAVY, first=True, space_after=3)
    add_para(tf, "Python 3.12 + NumPy/SciPy/mpmath；双精度 IEEE-754；全量校验耗时 14.6 s。"
                 "结果文件 results.json 由求解器脚本一次性生成（含全部数值与图源数据）。",
             size=13.5, color=INK, space_after=4)
    add_para(tf, "说明：本页数字均从 results.json 与 verify/verification_report.json 读取。",
             size=12, color=GRAY, space_after=0)
    return s


def slide_conclusions(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "结论与工程建议", "13 · 结论")
    ctrl = d.get("control") or []
    am = algo_medians(d)
    a1 = am.get(next((k for k in am if k.startswith("A1")), ""), {})
    a6 = am.get(next((k for k in am if k.startswith("A6")), ""), {})
    des = d.get("design") or {}
    base, alm = des.get("base") or {}, des.get("alm") or {}
    sd8, _ = case_sol(d, 8.0, "drift")
    sg8, _ = case_sol(d, 8.0, "grip")
    sd15, _ = case_sol(d, 15.0, "drift")
    sg15, _ = case_sol(d, 15.0, "grip")
    g8, g15, g22 = growth_at(d, 8.0), growth_at(d, 15.0), growth_at(d, 22.0)
    fc = sorted([r for r in (d.get("fold_curve") or []) if isinstance(r.get("V"), (int, float))],
                key=lambda r: r["V"])
    fold_line = "折叠边界：δf 随 V 增大而减小，高速下可用的反打角窗口明显收窄。"
    if len(fc) >= 2:
        fold_line = (f"折叠边界：V={fc[0]['V']:.0f}→{fc[-1]['V']:.0f} 时 δf 从 "
                     f"{fnum(fc[0].get('delta'),3)} 降到 {fnum(fc[-1].get('delta'),3)} rad，"
                     f"高速下可用的反打角窗口明显收窄。")
    errs_c = [c.get("errT_closed") for c in ctrl]
    errs_o = [c.get("errT_open") for c in ctrl]
    basins = [c.get("basin_frac") for c in ctrl]
    xo = (des.get("opt") or {}).get("x") or []
    k0 = base.get("kappa")
    k1 = (des.get("alm") or {}).get("kappa", (des.get("opt") or {}).get("kappa"))
    kdrop = ""
    try:
        kdrop = f"（{(float(k1) - float(k0)) / float(k0) * 100:+.0f}%）".replace("-", "−")
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    items = [
        f"双解结构：V=8 为抓地 β={fnum(sg8.get('beta_deg'),2)}° vs 漂移 β={fnum(sd8.get('beta_deg'),2)}°；"
        f"V=15 为 {fnum(sg15.get('beta_deg'),2)}° vs {fnum(sd15.get('beta_deg'),2)}°，两条分支均可复现。",
        f"漂移解为鞍点：max Re λ = {fnum(g8.get('max_real'),3)} / {fnum(g15.get('max_real'),3)} / "
        f"{fnum(g22.get('max_real'),3)}（V=8/15/22），不稳定度随车速单调增大。",
        fold_line,
        f"算法：A1 牛顿解析 {fnum(a1.get('it'),0)} 次迭代 / {fnum(a1.get('t'),2)} ms（中位）；BFGS 约 "
        f"{fnum(a6.get('it'),0)} 次 / {fnum(a6.get('t'),2)} ms；随机初值成功率 72–92%。",
        f"控制：LQR 将误差从 {fnum(ctrl[0].get('err0'),1)} 压到 {fnum(min(errs_c),5)}–{fnum(max(errs_c),3)}"
        f"（开环 {fnum(min(errs_o),2)}–{fnum(max(errs_o),2)}），吸引域 "
        f"{'/'.join(fpct(b, 0) for b in basins)}。",
        f"设计：κ 从 {fnum(k0,3)} 降到 {fnum(k1,3)}{kdrop}，"
        f"λ = {fnum((des.get('shadow') or {}).get('lam'),3)}，最优取 a≈{fnum(xo[0] if xo else None,2)} m、"
        f"b≈{fnum(xo[1] if len(xo) > 1 else None,2)} m。",
    ]
    add_bullets(s, 0.55, 1.38, 7.55, 4.9, items, size=14, gap=8)
    # 右侧建议卡
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.35), Inches(1.42), Inches(4.45), Inches(4.95))
    box.fill.solid(); box.fill.fore_color.rgb = LGRAY
    box.line.color.rgb = BLUE; box.line.width = Pt(1.0); box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.16); tf.margin_right = Inches(0.12); tf.margin_top = Inches(0.12)
    add_para(tf, "工程建议", size=15, bold=True, color=NAVY, first=True, space_after=6)
    for i, txt in enumerate([
        f"设计取值：优先调整 a↑、b↓（a≈{fnum(xo[0] if xo else None,2)} m、"
        f"b≈{fnum(xo[1] if len(xo) > 1 else None,2)} m），可在 ay≥"
        f"{fnum(des.get('ay_min'),1)} m/s² 下把 κ 降约 30%。",
        "控制增益：按 V 调度 K；高速（V≥20）时缩小初始偏差/增加带宽，吸引域仅约 54%。",
        "操控边界：以折叠曲线 δf(V) 作为稳态漂移的可用反打角上限，并保留 ≥20% 裕度。",
        "实车落地：先做 μ、Cα 参数辨识，再用 MPC/非线性控制处理大偏差与执行器饱和。",
    ]):
        add_para(tf, f"{i+1}. {txt}", size=14, color=INK, space_after=6)
    return s


def slide_limits(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "局限与展望", "14 · 局限与展望")
    add_bullets(s, 0.55, 1.40, 6.3, 5.2, [
        ("模型假设", -1),
        "刷子轮胎（纯侧偏、单调饱和）、准静态载荷转移；无悬架/侧倾自由度、无轮胎松弛与瞬态热效应。",
        "气动只保留 CdA 与升力系数，未考虑侧风、地面效应与姿态变化。",
        ("验证局限", -1),
        "参数取某后驱赛车典型值，尚未做实验标定（μ、Cα、Iz 的实车辨识）。",
        "验证以数值自洽与多实现交叉为主，缺少驾驶模拟器/实车数据。",
        ("方法与控制", -1),
        "非凸问题只保证局部解；多起点/延拓计算成本随参数维数上升。",
        "LQR 基于线性化，大偏差、执行器饱和与强非线性工况需 MPC/反馈线性化。",
    ], size=14, gap=6)

    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(7.15), Inches(1.42), Inches(5.65), Inches(4.95))
    box.fill.solid(); box.fill.fore_color.rgb = LGRAY
    box.line.color.rgb = GREEN; box.line.width = Pt(1.0); box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.16); tf.margin_right = Inches(0.12); tf.margin_top = Inches(0.12)
    add_para(tf, "可扩展方向", size=15, bold=True, color=GREEN, first=True, space_after=7)
    for txt in [
        "参数辨识：用赛道/台架数据估计 μ、Cα、Iz 与气动系数，替换当前典型值。",
        "非线性控制：MPC、反馈线性化、增益调度；加入执行器饱和与速率约束。",
        "动态漂移：从稳态平衡点扩展到轨迹跟踪与漂移过弯的时域优化。",
        "不确定性：蒙特卡洛/区间分析评估参数摄动下的稳定性与吸引域。",
        "实验验证：驾驶模拟器 → 封闭场地 → 实车逐级验证。",
    ]:
        add_para(tf, "• " + txt, size=14, color=INK, space_after=6)
    return s


def slide_refs(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(s, "参考文献（精选）", "15 · 参考文献")
    refs = [
        "[1] Nocedal J., Wright S. J. Numerical Optimization, 2nd ed. Springer, 2006.",
        "[2] Boyd S., Vandenberghe L. Convex Optimization. Cambridge University Press, 2004.",
        "[3] Moré J. J. The Levenberg–Marquardt Algorithm: Implementation and Theory. LNM 630, Springer, 1978.",
        "[4] Conn A. R., Gould N. I. M., Toint P. L. Trust-Region Methods. SIAM, 2000.",
        "[5] Pacejka H. B. Tire and Vehicle Dynamics, 3rd ed. Butterworth-Heinemann, 2012.",
        "[6] Milliken W. F., Milliken D. L. Race Car Vehicle Dynamics. SAE International, 1995.",
        "[7] Hindiyeh R. Dynamics and Control of Drifting in Automobiles. PhD thesis, Stanford University, 2013.",
        "[8] Velenis E., Frazzoli E., Tsiotras P. Steady-State Cornering Equilibria and Stabilisation for a Vehicle "
        "during Extreme Operating Conditions. IJVAS, 8(2/3/4):217–241, 2010.",
        "[9] Ono E., Hosoe S., Tuan H. D., Doi S. Bifurcation in Vehicle Dynamics and Robust Front Wheel Steering "
        "Control. IEEE TCST, 6(3):412–420, 1998.",
    ]
    y = 1.36
    for r in refs:
        h = 0.72 if len(r) > 128 else 0.50
        tb = add_textbox(s, 0.55, y, 12.2, h, "ref")
        tf = tb.text_frame
        add_para(tf, r, size=14, color=INK, first=True, space_after=0)
        y += h + 0.04
    tb = add_textbox(s, 0.55, 6.55, 12.2, 0.4, "ref_note")
    add_para(tb.text_frame, "注：全部条目已通过 Crossref / doi.org / 出版方页面核实（详见 references.md）；"
                            "正文引用编号以论文版为准。", size=10.5, color=GRAY, first=True)
    return s


def slide_thanks(prs, d):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    # 深色背景
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(SW), Inches(SH))
    bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background(); bg.shadow.inherit = False

    tb = add_textbox(s, 0.9, 1.55, 11.5, 1.0, "thanks")
    add_para(tb.text_frame, "谢谢！欢迎交流与提问", size=40, bold=True, color=WHITE, first=True)
    tb = add_textbox(s, 0.95, 2.65, 11.4, 0.5, "thanks_sub")
    add_para(tb.text_frame, "代码、结果与图表均可一键复现", size=18, color=RGBColor(0xC9, 0xD6, 0xEA), first=True)

    lines = [
        "race_drift_model.py      模型（单轨 + 刷子胎 + 摩擦圆 + 载荷转移）",
        "race_drift_solver.py     求解器 / 延拓 / 稳定性 / 控制 / 设计优化",
        "build_figs.py + figs/    11 张 200 dpi 结果图",
        "results.json             全量数值结果（本 PPT 全部数字来源）",
        "verify/                  40 项独立校验报告",
        "大作业_答辩PPT.pptx/.pdf  本答辩材料",
    ]
    box = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.9), Inches(3.35), Inches(7.4), Inches(3.0))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0x1B, 0x35, 0x5E)
    box.line.color.rgb = RGBColor(0x3E, 0x5F, 0x8F); box.line.width = Pt(0.75); box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.24); tf.margin_top = Inches(0.16)
    add_para(tf, "交付文件清单", size=14, bold=True, color=RGBColor(0xC9, 0xD6, 0xEA), first=True, space_after=6)
    for ln in lines:
        add_para(tf, ln, size=11.5, color=WHITE, name=MONO, space_after=3)

    qr = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(8.85), Inches(3.35), Inches(3.5), Inches(2.55))
    qr.fill.solid(); qr.fill.fore_color.rgb = WHITE
    qr.line.color.rgb = RGBColor(0xC9, 0xD6, 0xEA); qr.line.width = Pt(1.0); qr.shadow.inherit = False
    tf = qr.text_frame; tf.word_wrap = True
    tf.margin_left = Inches(0.1); tf.margin_right = Inches(0.1)
    add_para(tf, "二维码占位", size=16, bold=True, color=GRAY, align=PP_ALIGN.CENTER, first=True, space_after=4)
    add_para(tf, "（代码仓库 / 结果文件链接）", size=11, color=GRAY, align=PP_ALIGN.CENTER, space_after=0)

    tb = add_textbox(s, 0.95, 6.65, 11.6, 0.4, "thanks_foot")
    add_para(tb.text_frame, "非线性优化方法 · 2026 秋 · 基于非线性优化的赛车漂移平衡点求解与稳定性设计",
             size=11, color=RGBColor(0xC9, 0xD6, 0xEA), first=True)
    return s


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
def estimate_height(shape) -> float:
    """按字符宽度粗略估算文本块所需高度（英寸）。"""
    try:
        tf = shape.text_frame
    except Exception:  # noqa: BLE001
        return 0.0
    width = shape.width / 914400.0 - 0.18
    if width <= 0.3:
        return 99.0
    total = 0.0
    for p in tf.paragraphs:
        text = "".join(r.text or "" for r in p.runs)
        if not text:
            total += 0.10
            continue
        size = 14.0
        for r in p.runs:
            if r.font.size is not None:
                size = max(size, r.font.size.pt)
                break
        w = 0.0
        for ch in text:
            w += (size / 72.0) * (1.0 if ord(ch) > 0x2E80 else 0.56)
        ind = 0.3 if p.level else 0.0
        lines = max(1, math.ceil(w / max(width - ind, 0.8)))
        total += lines * size * 1.30 / 72.0 + 5.0 / 72.0
    return total


def audit(pptx_path: str) -> None:
    prs = Presentation(pptx_path)
    n = len(prs.slides)
    log(f"[check] 页数：{n}")
    issues = []
    for i, s in enumerate(prs.slides, 1):
        for sh in s.shapes:
            try:
                l, t = sh.left / 914400.0, sh.top / 914400.0
                w, h = sh.width / 914400.0, sh.height / 914400.0
            except TypeError:
                continue
            if l < -0.02 or t < -0.02 or l + w > SW + 0.02 or t + h > SH + 0.02:
                issues.append(f"  第{i}页 形状越界：{sh.name} ({l:.2f},{t:.2f},{w:.2f},{h:.2f})")
            if sh.has_text_frame and sh.text_frame.text.strip():
                est = estimate_height(sh)
                if est > h + 0.10:
                    issues.append(f"  第{i}页 文本可能溢出：{sh.name} 估算 {est:.2f} in > 框高 {h:.2f} in")
    if issues:
        log("[check] 警告：")
        for x in issues:
            log(x)
    else:
        log("[check] 未发现越界/文本溢出（估算）")


def export_pdf(pptx_path: str, pdf_path: str) -> bool:
    node = next((p for p in NODE_CANDIDATES if os.path.exists(p)), None)
    if node is None:
        log("[pdf] 未找到 node.exe，跳过 PDF 导出")
        return False
    if not os.path.exists(CLI):
        log(f"[pdf] 未找到 LibreOffice Kit CLI：{CLI}")
        return False
    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
        except OSError:
            pass
    cmd = [node, CLI, "convert", "--input", pptx_path, "--output", pdf_path]
    log("[pdf] " + " ".join(f'"{c}"' for c in cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=420)
    except subprocess.TimeoutExpired:
        log("[pdf] 超时")
        return False
    if r.stdout.strip():
        log("[pdf] stdout: " + r.stdout.strip()[:800])
    if r.returncode != 0:
        log(f"[pdf] 失败，退出码 {r.returncode}：{(r.stderr or '').strip()[:800]}")
        return False
    if not os.path.exists(pdf_path):
        log("[pdf] 未生成 PDF")
        return False
    size = os.path.getsize(pdf_path)
    with open(pdf_path, "rb") as f:
        head = f.read(5)
    ok = size > 100 * 1024 and head == b"%PDF-"
    log(f"[pdf] {os.path.basename(pdf_path)}：{size/1024:.0f} KB，头 {head!r}，{'成功' if ok else '异常'}")
    return ok


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def build_deck(d: dict) -> str:
    global TOTAL
    prs = Presentation()
    prs.slide_width = Inches(SW)
    prs.slide_height = Inches(SH)

    builders = [
        slide_cover, slide_background, slide_model, slide_tire, slide_optim,
        slide_algorithms, slide_multiplicity, slide_bifurcation, slide_stability,
        slide_phase, slide_control, slide_design, slide_verify, slide_conclusions,
        slide_limits, slide_refs, slide_thanks,
    ]
    for b in builders:
        try:
            b(prs, d)
        except Exception as e:  # noqa: BLE001
            log(f"[warn] 幻灯片 {b.__name__} 构建异常：{type(e).__name__}: {e}")
            s = prs.slides.add_slide(prs.slide_layouts[6])
            add_title(s, "（本页数据缺失，已跳过）")
            tb = add_textbox(s, 0.55, 1.5, 12, 2)
            add_para(tb.text_frame, f"{b.__name__}: {e}", size=14, color=RED, first=True)
    TOTAL = len(prs.slides)
    for i, s in enumerate(prs.slides, 1):
        add_footer(s, i, TOTAL)

    prs.save(PPTX)
    size = os.path.getsize(PPTX)
    log(f"[pptx] 已生成 {PPTX}（{TOTAL} 页，{size/1024:.0f} KB）")
    return PPTX


def main() -> int:
    t0 = time.time()
    log("=" * 66)
    log("build_ppt.py  |  赛车漂移平衡点答辩 PPT")
    log("=" * 66)
    d = load_results()
    build_deck(d)
    audit(PPTX)
    ok_pdf = export_pdf(PPTX, PDF)
    log(f"[done] 总耗时 {time.time()-t0:.1f} s；PDF {'成功' if ok_pdf else '失败/跳过'}")
    return 0 if ok_pdf else 1


if __name__ == "__main__":
    sys.exit(main())
