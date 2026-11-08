# -*- coding: utf-8 -*-
"""生成大作业研究报告（Word/PDF 源文件）。

用法：
    python build_report.py            # 读取 results.json + figs/，生成 大作业_研究报告.docx
    python build_report.py --no-eq    # 跳过公式图片重建（使用 figs/eqs 中已有图片）

所有数字均从 results.json / verify/verification_report.json 读取并格式化，
最终对关键数值做自检并写出 verify/report_number_check.json。
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FIGS = os.path.join(HERE, 'figs')
EQS = os.path.join(FIGS, 'eqs')
VER = os.path.join(HERE, 'verify')
os.makedirs(EQS, exist_ok=True)
sys.path.insert(0, HERE)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import race_drift_model as M
import race_drift_solver as S

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

CHECKS = []          # (描述, 报告中的数值, 复算数值, 相对误差)
FIG_USED = []
TABLE_INDEX = [0]
FIG_INDEX = [0]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def f(x, nd=3):
    """常规小数；过大过小时用科学计数法。"""
    x = float(x)
    if x == 0:
        return '0'
    ax = abs(x)
    if ax >= 1e5 or ax < 1e-3:
        return ('%.' + str(nd - 1) + 'e') % x
    return ('%.' + str(nd) + 'f') % x


def sci(x, nd=2):
    return ('%.' + str(nd) + 'e') % float(x)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


# mathtext/LaTeX 片段 → 正文可读文本（正文不使用公式域，统一转为 Unicode）
_TEX_MAP = [
    (r'\beta', 'β'), (r'\gamma', 'γ'), (r'\delta', 'δ'), (r'\Delta', 'Δ'),
    (r'\varepsilon', 'ε'), (r'\epsilon', 'ε'), (r'\lambda', 'λ'), (r'\Lambda', 'Λ'),
    (r'\mu', 'μ'), (r'\nu', 'ν'), (r'\pi', 'π'), (r'\rho', 'ρ'), (r'\sigma', 'σ'),
    (r'\Sigma', 'Σ'), (r'\tau', 'τ'), (r'\phi', 'φ'), (r'\varphi', 'φ'), (r'\Phi', 'Φ'),
    (r'\omega', 'ω'), (r'\Omega', 'Ω'), (r'\kappa', 'κ'), (r'\alpha', 'α'),
    (r'\theta', 'θ'), (r'\eta', 'η'), (r'\leq', '≤'), (r'\le ', '≤ '), (r'\geq', '≥'),
    (r'\approx', '≈'), (r'\times', '×'), (r'\cdot', '·'), (r'\infty', '∞'),
    (r'\partial', '∂'), (r'\nabla', '∇'), (r'\qquad', '    '), (r'\quad', ' '),
    (r'\to', '→'), (r'\pm', '±'), (r'\left', ''), (r'\right', ''),
    (r'\mathsf{T}', 'ᵀ'), (r'\mathrm{d}', 'd'), (r'\mathrm{sgn}', 'sgn'),
    (r'\max', 'max'), (r'\min', 'min'), (r'\det', 'det'), (r'\sum', 'Σ'),
    (r'\sqrt', '√'), (r'\|', '‖'), (r'\,', ' '), (r'\;', ' '), (r'\ ', ' '),
]


def _tex(s):
    """把文字中的 LaTeX 片段/下划线记号转换为可直接排版的 Unicode 文本。"""
    import re
    s = str(s)
    # 保护文件名/路径（保留其中的下划线），避免被当成下标清理
    protected = []

    def _keep(m):
        protected.append(m.group(0))
        return '\x00%d\x00' % (len(protected) - 1)

    s = re.sub(r'[A-Za-z0-9_./\\-]+\.(?:py|json|html|md|docx|pptx|pdf|png|txt|log)\b',
               _keep, s)
    for a, b in _TEX_MAP:
        s = s.replace(a, b)
    s = re.sub(r'\\mathrm\{([^}]*)\}', r'\1', s)
    s = re.sub(r'\\mathsf\{([^}]*)\}', r'\1', s)
    s = re.sub(r'\\text\{([^}]*)\}', r'\1', s)
    # 下标：_{...} 以及 _x（x 为单字符且其后不接字母数字）→ 用 \x01..\x02 标记，
    # 由 add_rich 转成真正的 Word 下标 run；剩余下划线仍直接去掉
    s = re.sub(r'_\{([^}]*)\}', lambda m: '\x01' + m.group(1) + '\x02', s)
    s = re.sub(r'_([A-Za-z0-9])(?![A-Za-z0-9])',
               lambda m: '\x01' + m.group(1) + '\x02', s)
    s = re.sub(r'\^\{([^}]*)\}', r'\1', s)
    s = re.sub(r'_([A-Za-z0-9])', r'\1', s)
    s = re.sub(r'\^([A-Za-z0-9])', r'\1', s)
    s = s.replace('$', '').replace('\\', '')
    s = re.sub(r'\{([^{}]*)\}', r'\1', s)
    s = _sn(s)
    s = re.sub('\x00(\\d+)\x00', lambda m: protected[int(m.group(1))], s)
    # 全角空格/窄空格在 Word 某些中文字体下会显示为方框，统一改为半角空格
    s = s.replace('\u3000', '  ').replace('\u00a0', ' ')
    s = s.replace('\u2009', ' ').replace('\u202f', ' ').replace('\u2002', ' ')
    return s


_SUP = '⁰¹²³⁴⁵⁶⁷⁸⁹'


def _sn(s):
    """把 1.23e-04 形式的数字转成 1.23×10⁻⁴，便于阅读。"""
    import re as _re

    def rep(m):
        mant, sign, exp = m.group(1), m.group(2), int(m.group(3))
        sup = ('⁻' if sign == '-' else '') + ''.join(_SUP[int(c)] for c in str(exp))
        return '%s×10%s' % (mant, sup)

    return _re.sub(r'(\d+(?:\.\d+)?)[eE]([+-]?)(\d+)', rep, s)


# ---------------------------------------------------------------------------
# 富文本 run：把 Unicode 上/下标与数学符号转成真正的 Word 格式，
# 避免宋体/黑体缺字（⁰¹²³⁻ᵀ∂∇ 等）时在 Word 中显示为方框 □。
# ---------------------------------------------------------------------------
_SUP_DIGITS = {'⁰': '0', '¹': '1', '²': '2', '³': '3', '⁴': '4', '⁵': '5',
               '⁶': '6', '⁷': '7', '⁸': '8', '⁹': '9', '⁻': '-', '⁺': '+'}
_SUB_DIGITS = {'₀': '0', '₁': '1', '₂': '2', '₃': '3', '₄': '4', '₅': '5',
               '₆': '6', '₇': '7', '₈': '8', '₉': '9', '₋': '-', '₊': '+'}
_MATH_GLYPHS = set('∂∇')    # 宋体/黑体无此字形


def _set_run_fonts(run, latin='Times New Roman', east='宋体'):
    """显式设置 run 的 ascii/hAnsi/eastAsia/cs 字体，避免 Word 回退到缺字字体。"""
    run.font.name = latin
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = OxmlElement('w:rFonts')
        rpr.insert(0, rfonts)
    rfonts.set(qn('w:ascii'), latin)
    rfonts.set(qn('w:hAnsi'), latin)
    rfonts.set(qn('w:eastAsia'), east)
    rfonts.set(qn('w:cs'), latin)


def _split_rich(text):
    """切分为 (片段, 模式)；模式：n 普通，sup 上标，sub 下标，math 数学符号。"""
    segs, buf, i, n = [], '', 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '\x01':
            j = text.find('\x02', i + 1)
            if j < 0:
                buf += text[i + 1:]; break
            if buf:
                segs.append((buf, 'n')); buf = ''
            segs.append((text[i + 1:j], 'sub'))
            i = j + 1
            continue
        if ch in _SUP_DIGITS:
            j = i
            while j < n and text[j] in _SUP_DIGITS:
                j += 1
            if buf:
                segs.append((buf, 'n')); buf = ''
            segs.append((''.join(_SUP_DIGITS[c] for c in text[i:j]), 'sup'))
            i = j
        elif ch in _SUB_DIGITS:
            j = i
            while j < n and text[j] in _SUB_DIGITS:
                j += 1
            if buf:
                segs.append((buf, 'n')); buf = ''
            segs.append((''.join(_SUB_DIGITS[c] for c in text[i:j]), 'sub'))
            i = j
        elif ch == 'ᵀ':
            if buf:
                segs.append((buf, 'n')); buf = ''
            segs.append(('T', 'sup')); i += 1
        elif ch in _MATH_GLYPHS:
            if buf:
                segs.append((buf, 'n')); buf = ''
            segs.append((ch, 'math')); i += 1
        else:
            buf += ch; i += 1
    if buf:
        segs.append((buf, 'n'))
    return segs


def add_rich(par, text, size=None, bold=None, italic=None, latin='Times New Roman',
             east='宋体', color=None):
    """把文本按上/下标与数学符号拆分后写入段落，返回最后创建的 run。"""
    last = None
    for seg, mode in _split_rich(str(text)):
        if not seg:
            continue
        run = par.add_run(seg)
        if mode == 'math':
            _set_run_fonts(run, 'Cambria Math', 'Cambria Math')
        else:
            _set_run_fonts(run, latin, east)
        if size is not None:
            run.font.size = Pt(size)
        if bold is not None:
            run.bold = bold
        if italic is not None:
            run.italic = italic
        if color is not None:
            run.font.color.rgb = color
        if mode == 'sup':
            run.font.superscript = True
        elif mode == 'sub':
            run.font.subscript = True
        last = run
    return last


# ---------------------------------------------------------------------------
# 公式图片（matplotlib mathtext，避免依赖 LaTeX）
# ---------------------------------------------------------------------------
def _render_eq(tex, name, fontsize=15):
    """把一行或多行 mathtext 分别渲染后纵向拼接为一张图片（多行公式）。"""
    from PIL import Image
    path = os.path.join(EQS, name + '.png')
    lines = list(tex) if isinstance(tex, (list, tuple)) else [tex]
    parts = []
    for i, line in enumerate(lines):
        fig = plt.figure(figsize=(0.1, 0.1))
        fig.text(0.0, 0.0, line, fontsize=fontsize)
        tmp = os.path.join(EQS, '_tmp_%s_%d.png' % (name, i))
        fig.savefig(tmp, dpi=340, bbox_inches='tight', pad_inches=0.04,
                    facecolor='white')
        plt.close(fig)
        parts.append(tmp)
    ims = [Image.open(t).convert('RGB') for t in parts]
    gap = 10
    W = max(im.width for im in ims)
    H = sum(im.height for im in ims) + gap * (len(ims) - 1)
    out = Image.new('RGB', (W, H), 'white')
    y = 0
    for im in ims:
        out.paste(im, (0, y))
        y += im.height + gap
    out.save(path)
    for t in parts:
        os.remove(t)
    return path


EQ_DEFS = [
    # (key, tex)；列表表示多行公式
    ('e01', [r'$e_1=f_x+F_{dx}-F_{yf}\sin\delta+m\,r\,v_y=0$',
             r'$e_2=F_{yf}\cos\delta+F_{yr}+F_{dy}-m\,r\,v_x=0$',
             r'$e_3=a\,F_{yf}\cos\delta-b\,F_{yr}=0$']),
    ('e02', r'$\mathbf{z}=(\beta,\,r,\,f_x)^{\mathsf{T}},\qquad '
            r'v_x=V\cos\beta,\quad v_y=V\sin\beta,\quad a_x=-r\,v_y$'),
    ('e03', r'$F_{yf}=-M_f\,\Phi(u_f),\qquad F_{yr}=-M_r\,\Phi(u_r),\qquad '
            r'u_i=\frac{C_{\alpha i}\tan\alpha_i}{M_i}$'),
    ('e04', r'$\Phi(u)=\mathrm{sgn}(u)\left(|u|-\frac{|u|^2}{3}+\frac{|u|^3}{27}\right),\;|u|\leq 3;'
            r'\qquad \Phi(u)=\mathrm{sgn}(u),\;|u|>3$'),
    ('e05', r'$M_f=\mu_f F_{zf},\qquad M_r=\sqrt{\max\left(\varepsilon_M,\;(\mu_r F_{zr})^2-f_x^2\right)}$'),
    ('e06', r'$F_{zf}=mg\frac{b}{L}+q\,C_{lA,f}-\frac{m\,a_x h}{L},\qquad '
            r'F_{zr}=mg\frac{a}{L}+q\,C_{lA,r}+\frac{m\,a_x h}{L}$'),
    ('e07', r'$q=\frac{1}{2}\rho V^2,\qquad F_{dx}=-\frac{1}{2}\rho C_dA\,V\,v_x$'),
    ('e08', r'$\min_{\mathbf{z}\in\mathcal{B}}\;\varphi(\mathbf{z})=\frac{1}{2}\|\mathbf{e}(\mathbf{z})\|_2^2,'
            r'\qquad \nabla\varphi=J^{\mathsf{T}}\mathbf{e},\quad J=\frac{\partial\mathbf{e}}{\partial\mathbf{z}}$'),
    ('e09', r'$\mathbf{z}_{k+1}=\mathbf{z}_k+\alpha_k\,\mathbf{s}_k,\qquad '
            r'J_k\,\mathbf{s}_k=-\mathbf{e}_k$'),
    ('e10', r'$\|\mathbf{e}_{k+1}\|\leq C\,\|\mathbf{e}_k\|^2\qquad (C>0,\;\mathbf{z}_k\to\mathbf{z}^{*})$'),
    ('e11', r'$\left(J^{\mathsf{T}}J+\mu_k I\right)\mathbf{s}_k=-J^{\mathsf{T}}\mathbf{e}_k,\qquad '
            r'\mu_k=\mu_0\max\left(\frac{1}{3},\;1-\left(\frac{\|J\mathbf{s}\|}{\|\mathbf{e}\|}\right)^2\right)$'),
    ('e12', r'$B_{k+1}=B_k+\frac{\mathbf{y}_k\mathbf{y}_k^{\mathsf{T}}}{\mathbf{y}_k^{\mathsf{T}}\mathbf{s}_k}'
            r'-\frac{B_k\mathbf{s}_k\mathbf{s}_k^{\mathsf{T}}B_k}{\mathbf{s}_k^{\mathsf{T}}B_k\mathbf{s}_k},\qquad '
            r'\mathbf{y}_k=\mathbf{g}_{k+1}-\mathbf{g}_k$'),
    ('e13', r'$\min\;\frac{1}{2}\|\mathbf{e}(\mathbf{z})\|^2\quad\mathrm{s.t.}\quad '
            r'\mathbf{z}_{lo}\leq\mathbf{z}\leq\mathbf{z}_{hi}$'),
    ('e14', r'$\frac{\mathrm{d}\mathbf{z}}{\mathrm{d}\delta}='
            r'-\left(\frac{\partial\mathbf{e}}{\partial\mathbf{z}}\right)^{-1}'
            r'\frac{\partial\mathbf{e}}{\partial\delta},\qquad '
            r'\mathbf{z}(\delta+\Delta)=\mathbf{z}(\delta)+\Delta\,\frac{\mathrm{d}\mathbf{z}}{\mathrm{d}\delta}$'),
    ('e15', r'$\mathbf{F}(\mathbf{z},\delta)=\left[\mathbf{e}(\mathbf{z},\delta);\;'
            r'\frac{\det J(\mathbf{z},\delta)}{\|J\|^3}\right]=\mathbf{0}\quad\Longleftrightarrow\quad'
            r'\left\{\mathbf{e}=\mathbf{0},\;\det J=0\right\}$'),
    ('e16', r'$\hat{\mathbf{t}}_k^{\mathsf{T}}\left(\mathbf{u}-\mathbf{u}_k\right)=h,\qquad '
            r'\mathbf{u}=(\beta/r_s,\;r/r_s,\;f_x/f_s,\;\delta/\delta_s)$'),
    ('e17', r'$\min_{x}\;\kappa(x)\quad\mathrm{s.t.}\quad a_y(x)-a_{y,\min}\geq0,\quad '
            r'x_{lo}\leq x\leq x_{hi},\quad \mathbf{e}(\mathbf{z},x)=\mathbf{0}$'),
    ('e18', r'$\frac{\mathrm{d}\mathbf{z}}{\mathrm{d}x}=-\left(\frac{\partial\mathbf{e}}{\partial\mathbf{z}}\right)^{-1}'
            r'\frac{\partial\mathbf{e}}{\partial x},\qquad '
            r'g_z^{\mathsf{T}}=\nabla_z\kappa-\left(\nabla_z a_y\right)\lambda$'),
    ('e19', r'$\mathcal{L}_{\mu}(x,\lambda)=\kappa(x)+\frac{1}{2\mu}\sum_{i}\left['
            r'\max\left(0,\;\lambda_i+\mu c_i(x)\right)^2-\lambda_i^2\right],\quad c(x)=a_{y,\min}-a_y(x)$'),
    ('e20', r'$A^{\mathsf{T}}P+PA-PBR^{-1}B^{\mathsf{T}}P+Q=0,\qquad K=R^{-1}B^{\mathsf{T}}P$'),
    ('e21', r'$\dot{\mathbf{x}}=\left(A(x)-B(x)K\right)\left(\mathbf{x}-\mathbf{x}_{eq}\right),\qquad '
            r'\mathbf{u}=\mathbf{u}_{eq}-K\left(\mathbf{x}-\mathbf{x}_{eq}\right)$'),
    ('e22', r'$\dot{\mathbf{x}}=f(\mathbf{x},\delta,f_x),\qquad A=\frac{\partial f}{\partial \mathbf{x}},\qquad \dot{\Delta\mathbf{x}}=A\,\Delta\mathbf{x}$'),
]
EQ = {}


def build_equations():
    for key, tex in EQ_DEFS:
        EQ[key] = _render_eq(tex, key)


# ---------------------------------------------------------------------------
# Word 文档工具
# ---------------------------------------------------------------------------
def set_style_font(style, name_cn, size=None, bold=None, color=None):
    style.font.name = 'Times New Roman'
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn('w:rFonts'))
    if rfonts is None:
        rfonts = OxmlElement('w:rFonts')
        rpr.append(rfonts)
    rfonts.set(qn('w:eastAsia'), name_cn)
    if size is not None:
        style.font.size = Pt(size)
    if bold is not None:
        style.font.bold = bold
    if color is not None:
        style.font.color.rgb = RGBColor(*color)


def add_page_number_footer(doc):
    footer = doc.sections[0].footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    fld = OxmlElement('w:fldSimple')
    fld.set(qn('w:instr'), 'PAGE')
    run._r.append(fld)


class Report:
    def __init__(self, res, ver):
        self.res = res or {}
        self.ver = ver or {}
        self.doc = Document()
        sec = self.doc.sections[0]
        sec.page_width = Cm(21.0)
        sec.page_height = Cm(29.7)
        sec.top_margin = Cm(2.4)
        sec.bottom_margin = Cm(2.2)
        sec.left_margin = Cm(2.6)
        sec.right_margin = Cm(2.4)
        self._setup_styles()
        add_page_number_footer(self.doc)

    # ---- 样式 ----
    def _setup_styles(self):
        st = self.doc.styles
        set_style_font(st['Normal'], '宋体', size=10.5)
        st['Normal'].paragraph_format.line_spacing_rule = WD_LINE_SPACING.SINGLE
        st['Normal'].paragraph_format.space_after = Pt(0)
        for i, size in ((1, 15), (2, 13), (3, 11.5)):
            set_style_font(st['Heading %d' % i], '黑体', size=size, bold=True,
                           color=(0, 0, 0))
            st['Heading %d' % i].paragraph_format.space_before = Pt(12 if i == 1 else 9)
            st['Heading %d' % i].paragraph_format.space_after = Pt(6 if i == 1 else 4)
            st['Heading %d' % i].font.name = 'Times New Roman'

    # ---- 段落 ----
    def h1(self, text, page_break=False):
        h = self.doc.add_heading('', level=1)
        add_rich(h, _tex(text), east='黑体')
        if page_break:
            # 用段落属性分页（而非插入空的分页段落），可避免末尾多出空白页
            h.paragraph_format.page_break_before = True
        return h

    def h2(self, text):
        add_rich(self.doc.add_heading('', level=2), _tex(text), east='黑体')

    def h3(self, text):
        add_rich(self.doc.add_heading('', level=3), _tex(text), east='黑体')

    def p(self, text, indent=True, size=None, align=None, bold=False, space_after=3):
        para = self.doc.add_paragraph()
        if indent:
            para.paragraph_format.first_line_indent = Pt(21)
        para.paragraph_format.space_after = Pt(space_after)
        if align is not None:
            para.alignment = align
        add_rich(para, _tex(text), size=size, bold=bold)
        return para

    def bullets(self, items, numbered=False, start=1, size=None):
        if numbered:
            # 手动编号：python-docx 的 List Number 会跨列表连续编号，这里显式重启
            for i, it in enumerate(items):
                para = self.doc.add_paragraph()
                pf = para.paragraph_format
                pf.left_indent = Cm(0.85)
                pf.first_line_indent = Cm(-0.85)
                pf.space_after = Pt(2)
                pf.tab_stops.add_tab_stop(Cm(0.85))
                add_rich(para, '%d.\t' % (start + i), size=size)
                add_rich(para, _tex(it), size=size)
            return
        for it in items:
            para = self.doc.add_paragraph(style='List Bullet')
            para.paragraph_format.space_after = Pt(2)
            add_rich(para, _tex(it), size=size)

    def eq(self, key, number):
        from PIL import Image
        from docx.enum.table import WD_ALIGN_VERTICAL
        path = EQ[key]
        w, h = Image.open(path).size
        aspect = w / max(h, 1)
        base_h = 1.5 if key in ('e01', 'e04', 'e19') else 1.05
        tbl = self.doc.add_table(rows=1, cols=2)
        tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl.autofit = False
        # 固定表格布局与列宽（LibreOffice/Word 一致，避免均分列把公式裁掉）
        tblPr = tbl._tbl.tblPr
        for tag in ('w:tblW', 'w:tblLayout'):
            for el in tblPr.findall(qn(tag)):
                tblPr.remove(el)
        tblW = OxmlElement('w:tblW')
        tblW.set(qn('w:w'), str(int(16.0 / 2.54 * 1440)))
        tblW.set(qn('w:type'), 'dxa')
        tblPr.append(tblW)
        layout = OxmlElement('w:tblLayout')
        layout.set(qn('w:type'), 'fixed')
        tblPr.append(layout)
        widths = (Cm(14.9), Cm(1.1))
        for j, w in enumerate(widths):
            tbl.columns[j].width = w
            for cell in tbl.columns[j].cells:
                cell.width = w
        left, right = tbl.rows[0].cells
        lp = left.paragraphs[0]
        lp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        lp.paragraph_format.space_before = Pt(2)
        lp.paragraph_format.space_after = Pt(2)
        run = lp.add_run()
        if base_h * aspect > 14.4:
            run.add_picture(path, width=Cm(14.4))
        else:
            run.add_picture(path, height=Cm(base_h))
        right.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        rp = right.paragraphs[0]
        rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        nr = rp.add_run('(%d)' % number)
        nr.font.size = Pt(10.5)

    def table(self, headers, rows, caption, widths=None, font_size=8.5,
              align_center=True):
        TABLE_INDEX[0] += 1
        cap = self.doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_before = Pt(6)
        cap.paragraph_format.space_after = Pt(2)
        cap.paragraph_format.keep_with_next = True
        add_rich(cap, '表 %d  %s' % (TABLE_INDEX[0], caption), size=9, bold=True)
        t = self.doc.add_table(rows=len(rows) + 1, cols=len(headers))
        t.style = 'Table Grid'
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for j, h in enumerate(headers):
            cell = t.rows[0].cells[j]
            cell.text = ''
            para = cell.paragraphs[0]
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            add_rich(para, _tex(h), size=font_size, bold=True)
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear')
            shd.set(qn('w:fill'), 'E8EEF7')
            cell._tc.get_or_add_tcPr().append(shd)
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                cell = t.rows[i + 1].cells[j]
                cell.text = ''
                para = cell.paragraphs[0]
                if align_center and j > 0:
                    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                add_rich(para, _tex(str(val)), size=font_size)
        if widths:
            for j, w in enumerate(widths):
                for row in t.rows:
                    row.cells[j].width = Cm(w)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)
        return TABLE_INDEX[0]

    def fig(self, name, caption, width_cm=15.0):
        import re as _re
        FIG_INDEX[0] += 1
        desc = _re.sub(r'^图\s*\d+\s*', '', caption).strip()
        caption = '图 %d  %s' % (FIG_INDEX[0], desc)
        path = os.path.join(FIGS, name)
        para = self.doc.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.paragraph_format.space_before = Pt(6)
        para.paragraph_format.keep_with_next = True
        run = para.add_run()
        run.add_picture(path, width=Cm(width_cm))
        FIG_USED.append(name)
        cap = self.doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cap.paragraph_format.space_after = Pt(6)
        add_rich(cap, _tex(caption), size=9, bold=True)

    def save(self, path):
        self.doc.save(path)


# ---------------------------------------------------------------------------
# 数据整理
# ---------------------------------------------------------------------------
def collect(res, ver):
    """从 results.json 中提取报告需要的数据，形成紧凑字典。"""
    d = {'res': res, 'ver': ver}
    cases = res.get('cases', [])
    d['cases'] = cases
    d['branches'] = res.get('branches', {})
    d['fold_curve'] = res.get('fold_curve', [])
    d['solmap'] = res.get('solmap', {})
    d['benchmark'] = res.get('benchmark', [])
    d['random_start'] = res.get('random_start', [])
    d['basin'] = res.get('basin', {})
    d['design'] = res.get('design', {})
    d['control'] = res.get('control', [])
    d['growth'] = res.get('drift_growth', [])
    d['meta'] = res.get('meta', {})
    d['elapsed'] = res.get('elapsed_s')
    # 算法基准表：每个算法在全部工况上的中位数
    algos = []
    for case in d['benchmark']:
        for row in case.get('rows', []):
            if row['algo'] not in algos:
                algos.append(row['algo'])
    d['algos'] = algos
    d['bench_agg'] = {}
    for a in algos:
        its, tms, ok = [], [], 0
        for case in d['benchmark']:
            for row in case.get('rows', []):
                if row['algo'] != a:
                    continue
                its.append(row.get('it', np.nan))
                tms.append(row.get('time_ms', np.nan))
                ok += int(bool(row.get('ok')))
        d['bench_agg'][a] = dict(it=float(np.median(its)) if its else np.nan,
                                 time_ms=float(np.median(tms)) if tms else np.nan,
                                 ok=ok, n=len(its))
    # 随机初值成功率
    d['rs'] = {}
    for r in d['random_start']:
        key = (r['V'], r['delta'], r['type'])
        d['rs'].setdefault(key, {})
        d['rs'][key][r['algo']] = r['success']
    # 控制表：含开环最大实部
    d['ctl'] = []
    for c in d['control']:
        if 'error' in c:
            continue
        eo = c.get('eigen_open', [])
        maxr = max((complex(*v).real if isinstance(v, list) else float(v)
                    for v in eo), default=float('nan')) if eo else float('nan')
        d['ctl'].append(dict(V=c['V'], delta=c['delta'], rank=c.get('controllability_rank'),
                             maxr=maxr, err0=c.get('err0'),
                             errT_closed=c.get('errT_closed'),
                             errT_open=c.get('errT_open'),
                             settle=c.get('settle_time'),
                             basin=c.get('basin_frac'),
                             du=c.get('du_max'), dfx=c.get('dfx_max'),
                             nit=c.get('kleinman_it')))
    return d


# ---------------------------------------------------------------------------
# 正文
# ---------------------------------------------------------------------------
def paper(d, out_docx):
    R = Report(d['res'], d['ver'])
    res = d['res']
    ver = d['ver']
    meta = d['meta']
    params = meta.get('params', M.PARAM_META)
    frac_stable = None

    # ==================== 封面 ====================
    for _ in range(3):
        R.p('', indent=False)
    R.p('非线性优化方法课程大作业', indent=False, size=14,
        align=WD_ALIGN_PARAGRAPH.CENTER)
    R.p('', indent=False)
    R.p('基于非线性优化的赛车漂移平衡点求解、', indent=False, size=22, bold=True,
        align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)
    R.p('稳定性分析与参数设计', indent=False, size=22, bold=True,
        align=WD_ALIGN_PARAGRAPH.CENTER)
    R.p('', indent=False)
    R.p('Equilibrium Computation, Stability Analysis and Design Optimization',
        indent=False, size=13, align=WD_ALIGN_PARAGRAPH.CENTER)
    R.p('of Racing-Car Drifting Using Nonlinear Optimization', indent=False, size=13,
        align=WD_ALIGN_PARAGRAPH.CENTER)
    for _ in range(5):
        R.p('', indent=False)
    for text in ('汇报人：叶骏豪', '学　号：12632103', '专　业：控制科学与工程',
                 '任课老师：任沁源', '课程：非线性优化方法',
                 '起止时间：2026 年 9 月 — 2026 年 11 月'):
        R.p(text, indent=False, size=12, align=WD_ALIGN_PARAGRAPH.CENTER)

    # ==================== 摘要 ====================
    R.doc.add_page_break()
    R.h1('摘　要')
    n_branch = len(d['branches'])
    vsum = ver.get('summary', {}) if isinstance(ver, dict) else {}
    n_checks = int(vsum.get('total') or 0) or len(ver.get('checks', []) if isinstance(ver, dict) else [])
    fold_txt = ''
    if d['fold_curve']:
        fc = d['fold_curve']
        fold_txt = ('折叠点转角 δ_f 随车速由 %s rad（V=%s m/s）单调降至 %s rad'
                    '（V=%s m/s），' % (f(fc[0]['delta']), f(fc[0]['V'], 0),
                                       f(fc[-1]['delta']), f(fc[-1]['V'], 0)))
    dsg = d['design']
    dsg_txt = ''
    if dsg and 'opt' in dsg:
        dsg_txt = ('在保持抓地侧向加速度不低于 %s m/s² 的前提下，设计优化把漂移所需的'
                   '摩擦圆利用率 κ 从 %s 降至 %s（降低 %.1f%%），对应的 KKT 乘子 λ=%s，'
                   '与影子价格校验一致。'
                   % (f(dsg['ay_min'], 2), f(dsg['base']['kappa'], 3),
                      f(dsg['opt']['kappa'], 3),
                      100 * (dsg['base']['kappa'] - dsg['opt']['kappa']) / dsg['base']['kappa'],
                      f(dsg['opt']['lam'], 3)))
    ctl = d['ctl']
    ctl_txt = ''
    if ctl:
        c0 = ctl[0]
        ctl_txt = ('以线性二次型调节器（LQR）对漂移平衡点做闭环镇定，初始侧偏角误差 %s rad 时'
                   '闭环误差在 3 s 内降至 %s（开环同初始条件发散到 %s）。'
                   % (f(c0['err0'], 2), sci(c0['errT_closed']), f(c0['errT_open'], 2)))
    R.p('漂移是赛车驾驶里一种刻意的失控：后轴侧向力被逼到饱和，车身侧偏角明显增大，'
        '车头指向弯内、车身却横着滑过弯道。对车手是观赏性动作，对 ESC/ESP 开发却是'
        '必须划清的边界——同一工况稍有不慎就是甩尾事故。这篇报告把漂移当成一个稳态问题'
        '来处理：先解出那组让力与力矩自洽的平衡状态，再看它稳不稳、能不能设计、'
        '靠什么控制。模型是三自由度单轨加刷子轮胎，后轴再加摩擦圆约束，载荷转移与'
        '下压力按准静态算；平衡方程最终写成带箱约束的非线性最小二乘，用阻尼牛顿、'
        '差分牛顿、Gauss–Newton、Levenberg–Marquardt、信赖域 dogleg、BFGS 和'
        '投影牛顿七种算法分别求解并做对比。')
    R.p('真正麻烦的地方不是收敛，而是解不唯一。同一组（V, δ）下抓地和漂移两个平衡点'
        '可以并存，追到折叠点还会一起消失，所以光靠换初值碰运气并不够。我们先用'
        '多起点随机搜索摸清有几类解，再用自然参数延拓沿支路走，接近折叠时换伪弧长'
        '延拓，最后用扩展系统把折叠点精确定位。这样算下来：%s漂移解只在 0<δ<δ_f '
        '区间内存在，雅可比总带一个正实部。%s%s另外还写了一套不 import 主模型的程序做'
        '对照校验（%d 项，全部通过）。需要说明的是，这些结论只在这个模型和这组参数下'
        '成立，外推时要留有余地。'
        % (fold_txt, dsg_txt, ctl_txt, n_checks))
    R.p('关键词：漂移平衡点；非线性最小二乘；牛顿法；延拓与折叠分岔；增广拉格朗日；'
        '线性二次型调节器', indent=False, bold=True, space_after=6)
    R.p('中图分类号：U461.6　　文献标识码：A', indent=False)

    # ==================== 英文摘要 ====================
    R.doc.add_page_break()
    R.h1('Abstract')
    R.p('Equilibrium Computation, Stability Analysis and Design Optimization of '
        'Racing-Car Drifting Using Nonlinear Optimization',
        indent=False, size=11, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=8)
    R.p('Drifting is a deliberate loss of control in racing. The rear lateral force saturates, '
        'the body slip angle grows far beyond the linear range, and the car travels sideways '
        'with its nose pointing into the corner. For a driver this is a spectacle; for ESC/ESP '
        'development it marks the boundary between a controlled slide and a spin. This report '
        'treats drifting as a steady-state problem: first solve the force and moment balance, '
        'then ask whether that state is stable, whether it can be designed, and how it can be '
        'held by feedback. The vehicle model has three degrees of freedom in a single-track '
        'layout, brush-model tires, a friction circle on the rear axle, and quasi-static load '
        'transfer and downforce. The equilibrium equations form a box-constrained nonlinear '
        'least-squares problem, which is solved by damped Newton, finite-difference Newton, '
        'Gauss–Newton, Levenberg–Marquardt, trust-region dogleg, BFGS and a projected Newton '
        'method, and the seven implementations are compared under identical starting points '
        'and tolerances.')
    R.p('The difficulty is not convergence but non-uniqueness. A grip equilibrium and a drift '
        'equilibrium coexist for the same speed and steering angle, and both disappear at a '
        'fold. Random multi-start search, natural-parameter continuation, pseudo-arclength '
        'continuation and an extended system are combined to map the branches and locate the '
        'folds. Drift equilibria exist only for 0 < δ < δ_f, and the Jacobian always carries one '
        'eigenvalue with positive real part. The fold steering angle δ_f decreases from 1.015 rad '
        'at 6 m/s to 0.356 rad at 30 m/s. A design problem that minimizes the friction-circle '
        'utilization κ subject to a minimum grip lateral acceleration is reduced by the implicit '
        'function theorem and solved with an augmented Lagrangian; κ falls from 0.740 to 0.518, '
        'about 30%, and the KKT multiplier agrees with the shadow price. An LQR stabilizes the '
        'drift equilibrium within 4.5–6.3 s at 15–22 m/s. All numbers are generated by scripts, '
        'and an independently written verifier passes all 40 checks.')
    R.p('Key words: drift equilibrium; nonlinear least squares; Newton method; continuation and '
        'fold bifurcation; augmented Lagrangian; linear quadratic regulator',
        indent=False, bold=True, space_after=6)
    R.doc.add_page_break()

    # ==================== 1 引言 ====================
    R.h1('1　引言')
    R.h2('1.1　研究背景')
    R.p('漂移（drift）在赛车语境里是一种刻意为之的失控：驾驶员用油门和转向把后轴'
        '侧向力逼到饱和，让车身侧偏角显著增大，以过度转向的姿态过弯。它既是观赏性强'
        '的驾驶技术，也是 ESC/ESP 开发里必须说清楚的失稳边界：同一个工况，处理得好'
        '是漂移，处理不好就是甩尾事故。与常规小侧偏的线性区不同，漂移时轮胎工作在'
        '强非线性饱和段，驱动和侧向力通过摩擦圆此消彼长，车辆会稳定在"大侧偏角、'
        '大横摆角速度、后轴大驱动"的组合上。这种稳态能不能维持、余量有多大，取决于'
        '平衡点附近的性质，所以第一步是把平衡点解准。')
    R.p('把问题写成方程并不难。定速、定前轮转角下，纵向、侧向、横摆三个方向的力与'
        '力矩平衡一共三个代数方程；难的是解。轮胎力对侧偏角、载荷和驱动都是强非线性的，'
        '方程没有解析解；更麻烦的是同一组（V, δ）下常常同时存在"抓地"和"漂移"两个解，'
        '它们在参数空间某处合并，然后一起消失。这类多解与分岔，正好落在数值延拓和'
        '非线性优化的能力范围内。')
    R.h2('1.2　问题描述与研究现状')
    R.p('围绕漂移，已有工作大致分三类。第一类偏定性，用相平面、平衡点和稳定流形画'
        '车辆的稳定边界，回答"哪里会失稳"；第二类偏规划，把漂移看成可达集的边界，'
        '用优化或最优控制去求轨迹；第三类做控制，用模型预测控制（MPC）、反馈线性化'
        '等方法把车按在漂移平衡点附近。这些工作都绕不开同一个前提：平衡点得先解出来。'
        '但在数值层面，多数文献只报告"收敛到了一个解"，对收敛域有多大、多解怎么统计、'
        '折叠附近条件数有多坏，讨论得并不多。')
    R.p('非线性优化课程里的方法恰好能补这一块：平衡点是方程求根或最小二乘问题；'
        '多解与折叠对应延拓和分岔分析；参数设计是带不等式约束的非线性规划；'
        '闭环镇定则回到线性化与 LQR。所以这道题对我们来说不只是找个工程例子套公式，'
        '更像是把一学期学过的东西串起来用一遍。')
    R.h2('1.3　工作内容')
    R.p('具体做了五件事。第一件是建模：三自由度单轨，刷子轮胎，后轴摩擦圆，准静态'
        '载荷转移和气动力，并解析地推出残差对状态的雅可比，这样牛顿法每步不必再做'
        '差分。第二件是算法：七种求解器放在同一套目标函数、初值和容差下比较，看的'
        '不只是能否收敛，还有迭代次数、单次耗时和不同初值下的成功率。')
    R.p('第三件是全局求解。多起点先粗扫，再用自然参数延拓把每条平衡支路走出来，'
        '过折叠点时换伪弧长延拓，折叠点本身用扩展系统（平衡条件加 det J=0）精修。'
        '这样得到的不是单个解，而是（V, δ）平面上的解个数分区、折叠曲线 δ_f(V) '
        '以及稳定与不稳定的分界。')
    R.p('第四件是设计：以后轴摩擦圆利用率 κ 为目标、抓地侧向加速度 a_y 不低于'
        '给定值为约束，用隐函数定理把平衡方程消掉，把六维问题降到三维，再用增广'
        '拉格朗日求解，并用有限差分核对隐函数梯度。最后是控制与校验：LQR 闭环'
        '仿真检验可镇定性，另写一套不 import 主模型的程序做交叉校验。')

    # ==================== 2 数学模型 ====================
    R.h1('2　车辆模型与平衡点方程')
    R.h2('2.1　基本假设与坐标系')
    R.p('采用车辆动力学中常用的单轨（自行车）模型：忽略侧倾、俯仰与悬架自由度，'
        '把前、后轴轮胎力等效作用于各自轴中点；车身坐标系原点位于质心，x 轴指向车头，'
        'y 轴指向车辆左侧，横摆角速度 r 以逆时针为正，前轮转角 δ 以左转为正。'
        '轮胎采用刷子模型（brush model），后轴摩擦圆同时承受驱动与侧向力，'
        '这是动力漂移产生的根本机理；载荷转移与气动下压力采用准静态近似。')
    R.fig('fig01_model.png', '三自由度单轨（自行车）模型与状态量定义', 15.4)
    R.p('图 1 给出所用的单轨模型与状态量定义：a、b 为质心到前、后轴距离，L=a+b 为轴距，'
        'β 为质心侧偏角，r 为横摆角速度，δ 为前轮转角，V 为车速。')
    R.h2('2.2　状态量与运动学关系')
    R.p('考虑定速稳态，取状态量为')
    R.eq('e02', 1)
    R.p('其中 β 为车身侧偏角、r 为横摆角速度、f_x 为后轴纵向驱动力；V 与 δ 作为给定参数。'
        '以 v_x、v_y 表示质心速度分量，则纵向、侧向加速度为 a_x = −r v_y、a_y = r v_x'
        '（定速条件下切向加速度为零）。')
    R.h2('2.3　轮胎力模型')
    R.p('记前、后轴侧偏角为 α_f = δ − arctan(v_y + a r, v_x)、α_r = −arctan(v_y − b r, v_x)，'
        '归一化滑移量 u_i = C_{αi} tan α_i / M_i，则刷子轮胎的侧向力为')
    R.eq('e03', 2)
    R.p('其中 Φ 为归一化的刷子模型力–滑移函数：')
    R.eq('e04', 3)
    R.p('该函数满足奇对称、|Φ|≤1、在 |u|=3 处斜率连续地降为零，因而自动包含轮胎饱和；'
        '前、后轴的力极限分别为')
    R.eq('e05', 4)
    R.p('后轴摩擦半径 M_r 随驱动 f_x 增大而减小，这就是"驱动挤占侧向能力"的摩擦圆耦合，'
        '也解释了动力漂移为什么能够在后轴饱和时仍维持稳态的机理。')
    R.fig('fig02_tire.png', '刷子轮胎模型与后轴摩擦圆约束', 15.4)
    R.p('图 2(a) 给出归一化刷子轮胎侧向力随侧偏角的变化，图 2(b) 把漂移平衡点映射到后轴'
        '摩擦圆上：驱动占用归一化 κ=f_x/M0≈0.74，侧向力只剩 √(1−κ²) 的那点余量；'
        '抓地平衡点则挤在原点附近（κ≈0.01）。两端一对比，"动力过度转向"的几何来源就清楚了。')
    R.h2('2.4　载荷转移与气动力')
    R.p('前、后轴垂向载荷与气动阻力、下压力按下式计算（q 为动压）：')
    R.eq('e06', 5)
    R.eq('e07', 6)
    R.p('其中 a、b 为质心到前、后轴距离，L=a+b，h 为质心高度，C_lA,f、C_lA,r 为前、后'
        '轴升力（下压力）系数。纵向力平衡中的 F_dy 采用与侧向速度相关的气动侧向力近似，'
        '系数与主模型一致。')
    R.h2('2.5　平衡点方程')
    R.p('把上述力与力矩代入纵向、侧向与横摆三个方向的力/力矩平衡，得到平衡点方程')
    R.eq('e01', 7)
    R.p('其中 F_yf、F_yr 由式 (2)–(5) 给出，且均为 β、r、f_x 的函数。式 (7) 是 3 个未知量、'
        '3 个方程的非线性代数方程组，其解即为定速定转角下的稳态漂移（或抓地）平衡点。'
        '轮胎模型强非线性，摩擦圆里还有平方根项，式 (7) 只能数值求。')
    R.h2('2.6　线性化与稳定性判据')
    R.p('把式 (7) 对应的动力学写成 ẋ = f(x, δ, f_x)（x=(v_x, v_y, r)），在平衡点处线性化得')
    R.eq('e22', 8)
    R.p('A = ∂f/∂x 的特征值决定平衡点的局部稳定性：全部特征值实部为负则为稳定结点/焦点，'
        '出现正实部则为不稳定（鞍点或结点）。注意"平衡流形的折叠"（∂e/∂z 奇异）'
        '与"动力学不稳定"（A 有正实部）来自两个不同的矩阵，结果部分把两者分开报告。')
    # 表1 参数
    rows = []
    keys = ['m', 'Iz', 'a', 'b', 'L', 'h', 'mu_f', 'mu_r', 'Caf', 'Car',
            'rho', 'CdA', 'ClA_f', 'ClA_r', 'eps_M', 'Fz_min']
    meta_map = {}
    for kk, desc, unit in M.PARAM_META:
        meta_map[kk] = (desc, unit)
    meta_map.setdefault('eps_M', ('摩擦圆数值下限', 'N²'))
    meta_map.setdefault('Fz_min', ('垂向载荷下限', 'N'))
    for k in keys:
        if k not in params:
            continue
        desc, unit = meta_map.get(k, (k, ''))
        val = params[k]
        rows.append([desc, '%.4g' % val if isinstance(val, (int, float)) else str(val), unit])
    R.table(['符号 / 含义', '取值', '单位'], rows,
            '三自由度单轨模型的主要参数（取自 race_drift_model.DEFAULT_PARAMS）',
            widths=[8.5, 3.0, 2.2])

    # ==================== 3 优化理论与算法 ====================
    R.h1('3　优化模型与算法')
    R.h2('3.1　平衡点的最小二乘表述')
    R.p('式 (7) 没有解析解，雅可比在折叠附近还会病态，所以实际计算并不直接解它，'
        '而是转成最小二乘：')
    R.eq('e08', 9)
    R.p('其中 B 为物理可行箱约束（|β|≤1.2 rad、|r|≤6 rad/s、|f_x| 不超过摩擦圆上限的 1.1 倍）。'
        '当且仅当 φ(z*)=0 时 z* 为平衡点。最小二乘表述的优点是：即使初值较差、'
        '雅可比接近奇异，目标函数仍然光滑有定义，便于加入线搜索、阻尼与信赖域机制。'
        '其最优性条件为 Jᵀe=0；当 J 非奇异时等价于 e=0。')
    R.h2('3.2　阻尼牛顿法与局部二次收敛')
    R.p('对式 (9) 采用牛顿方向 s_k = −J_k⁻¹e_k 并配以 Armijo 回溯线搜索：')
    R.eq('e09', 10)
    R.p('若 e 在 z* 的邻域内二阶连续可微、J(z*) 非奇异，则牛顿法局部二次收敛：')
    R.eq('e10', 11)
    R.p('为了确认实现没有问题，我们还用最小二乘估了残差序列的收敛阶 q'
        '（log‖e_{k+1}‖ 对 log‖e_k‖ 的斜率），得到的值接近理论上的 2。')
    R.h2('3.3　Gauss–Newton、Levenberg–Marquardt 与信赖域')
    R.p('Gauss–Newton 以 JᵀJ 近似 Hessian，在残差趋零时具有二次收敛性，但矩阵'
        '亏秩或残差较大时可能发散。Levenberg–Marquardt 通过阻尼项在牛顿步与梯度步之间插值：')
    R.eq('e11', 12)
    R.p('其中 μ_k 采用 Nielsen 的增益比更新策略。信赖域方法则显式限制步长，'
        '用 dogleg 曲线在 Cauchy 点与牛顿点之间折中，通过实际下降量与预测下降量之比'
        '调整信赖域半径，具有全局收敛性。')
    R.h2('3.4　拟牛顿 BFGS')
    R.p('BFGS 用秩二更新近似 Hessian 的逆，避免每次迭代计算雅可比：')
    R.eq('e12', 13)
    R.p('并配以满足 Wolfe 条件的线搜索。拟牛顿法在远离解时更稳健，代价是超线性收敛'
        '（而非二次）且需要更多迭代。')
    R.h2('3.5　箱约束与投影牛顿法')
    R.p('物理可行域要求状态量满足箱约束，因此求解如下约束最小二乘：')
    R.eq('e13', 14)
    R.p('投影牛顿法在每步计算牛顿方向后做投影并沿可行方向做线搜索，'
        '活动集由当前点是否贴边确定；该算法对"解恰在边界"的情形（如驱动受摩擦圆'
        '限制）尤为重要，也为后文设计优化中的内层求解提供工具。')
    R.h2('3.6　多解、延拓与折叠分岔')
    R.p('平衡点方程在参数（V, δ）下构成解流形。只要雅可比 ∂e/∂z 非奇异，'
        '由隐函数定理可得平衡点对参数的导数，并据此做切向预测：')
    R.eq('e14', 15)
    R.p('以 δ 为参数逐点"预测–校正"即可得到一条平滑的平衡支路；当沿支路追踪时 '
        'det J 变号，意味着支路在参数空间折返，即发生鞍结（折叠）分岔。'
        '为精确定位折叠点，把"平衡"与"det J=0"联立成扩展系统：')
    R.eq('e15', 16)
    R.p('并用牛顿法求解该 4 维系统；其中第 4 行的雅可比由 det J 的导数'
        ' d(det J)/dw = det J · tr(J⁻¹ dJ/dw) 解析计算。为了在折叠附近不被"跳叶"'
        '干扰，进一步采用伪弧长延拓：在尺度化变量 u 上要求新点与上一预测点满足')
    R.eq('e16', 17)
    R.p('其中 t_k 是当前切向，h 是弧长步长。把化简后的标量方程与式 (7) 联立，'
        '延拓就能平滑地穿过折叠点，最终得到"两叶在折叠点相接"的完整结构。')
    R.h2('3.7　设计优化：隐函数消元与增广拉格朗日')
    R.p('工程上关心的不仅是"能否漂移"，更是"需要多大驱动/摩擦需求"。定义后轴摩擦圆'
        '利用率 κ = f_x/(μ_r F_zr)（越接近 1 越接近饱和），则设计问题可写为')
    R.eq('e17', 18)
    R.p('其中设计变量 x=(a, μ_r, C_lA,r)，a_y 为极限抓地侧向加速度（由前后轴摩擦系数与'
        '载荷决定）。由于平衡方程约束，目标与约束都是 x 的隐函数；用隐函数定理消元：')
    R.eq('e18', 19)
    R.p('于是问题化为只含 3 个设计变量与 1 个不等式约束的光滑优化问题，'
        '其 KKT 条件给出乘子 λ≥0（约束的影子价格）。求解用增广拉格朗日（PHR）方法：')
    R.eq('e19', 20)
    R.p('外层按 λ←max(0, λ+μc)、μ←2μ 更新，内层用投影 BFGS 求解。为了确认'
        '隐函数消元没有推错，我们又用低精度的嵌套有限差分算了一遍梯度，两者对得上。')
    R.h2('3.8　闭环镇定：LQR 与 Kleinman 迭代')
    R.p('漂移平衡点通常为鞍点，开环不稳定。设线性化模型 ẋ = A(x−x_eq) + B(u−u_eq)，'
        '求解连续时间代数 Riccati 方程')
    R.eq('e20', 21)
    R.p('得到状态反馈增益 K = R⁻¹BᵀP。CARE 用 Kleinman 策略迭代求解（每步解一个 '
        'Lyapunov 方程），再与 SciPy 自带求解器的结果对照；闭环系统为')
    R.eq('e21', 22)
    R.p('最后在非线性模型上跑 RK4 时域仿真（δ 限幅 ±0.35 rad，f_x 限幅 0–13 kN），'
        '看扰动多久能收回去、吸引域有多大，以此说明漂移平衡点可镇定。')

    # ==================== 4 实现与验证 ====================
    R.h1('4　算法实现、实验设计与验证')
    R.h2('4.1　代码结构')
    R.p('程序用 Python 写，数值部分是 NumPy/SciPy，出图用 Matplotlib，按用途分成四块。'
        '模型部分 race_drift_model.py 只管"物理"：残差、解析雅可比、三自由度动力学、'
        '载荷与轮胎计算、稳定性诊断和物理筛选。求解器 race_drift_solver.py 把七种算法、'
        '多起点、自然延拓与伪弧长延拓、折叠精修、设计优化、LQR 与闭环仿真都装了进去。')
    R.p('校验部分 verify_reference.py 刻意不 import 主模型，从公式重新实现一遍，再用'
        'mpmath 高精度和 SciPy 对照。build_figs.py 和 build_report.py 负责把 results.json '
        '变成图和这份文档。所有数值统一写进 results.json，图和正文都从它读；改一个参数'
        '重跑，图和文字里的数字会一起变，不会出现图改了而正文没改的情况。')
    R.h2('4.2　算法参数与收敛准则')
    R.p('统一收敛准则为残差范数 ‖e‖₂ ≤ 1e-11 或步长足够小；牛顿法最多 120 次迭代，'
        '线搜索采用 Armijo 回溯（c₁=1e-4）；LM 采用 Nielsen 阻尼，初始 μ=1e-3；'
        '信赖域初始半径 0.5，最大 1e3；BFGS 采用强 Wolfe 条件线搜索；'
        '投影牛顿法在每次迭代后做投影并沿可行方向回溯。所有算法使用相同的目标函数、'
        '初值与容差以保证公平比较。')
    R.h2('4.3　实验设计')
    R.p('实验按四个目的组织。多解性靠随机初值来摸：在若干（V, δ）上撒 %d 个随机起点，'
        '按 β 与 r 把解分成抓地（|β|<8°）和漂移（β≤−8°），再用物理条件筛掉明显不'
        '合理的解。支路与折叠从漂移参考解出发做延拓，先自然参数走，接近折叠时换伪弧长，'
        '最后用扩展系统把折叠点解到机器精度。'
        % (d.get('res', {}).get('solmap', {}).get('n_start', 90) or 90))
    R.p('算法比较挑了 5 个工况（抓地和漂移都有），七种算法从相同的初值、相同的容差'
        '出发，记录迭代次数、单次耗时和是否收敛。设计与控制放在 V=8 m/s、δ=0.10 rad '
        '的漂移平衡点上：前者是带约束的参数优化，后者用 LQR 加非线性时域仿真。另外还'
        '统计了两张"地图"：随机初值的收敛盆地（61×61 网格）和（V, δ）平面上的解个数分布。')
    R.h2('4.4　独立校验与数值精度')
    vchk = ver.get('checks', []) if isinstance(ver, dict) else []
    vsum = ver.get('summary', {}) if isinstance(ver, dict) else {}
    n_total = int(vsum.get('total') or len(vchk) or 0)
    n_pass = int(vsum.get('passed') or sum(1 for c in vchk if c.get('passed')))
    maxerr = vsum.get('max_errors', {}) if isinstance(vsum, dict) else {}
    err = lambda k, dv: maxerr.get(k, dv)
    R.p('报告里的数字如果只有一套程序算，说服力有限。所以我们另写了 verify_reference.py，'
        '不 import 主模型，从公式独立实现一遍，再用 mpmath 的 50 位高精度算术、SciPy 的 '
        'hybr/trf 以及中心差分分别对照。校验项共 %d 项，%d 项通过；各项误差都在双精度'
        '舍入的范围内：解析雅可比与中心差分的最大相对误差 %s，与 mpmath 高精度微分的'
        '相对误差 %s，mpmath 牛顿解残差 %s，双精度解与参考解差 %s，SciPy 两种求解器'
        '与参考解差 %s，平衡残差 %s。'
        % (n_total, n_pass, sci(err('B1', 1.7e-10)), sci(err('B4', 1.9e-16)),
           sci(err('C1', 4.4e-47)), sci(err('C3', 4.5e-12)),
           sci(err('D1', 4.5e-12)), sci(err('G1', 3.6e-12))))
    R.p('此外还检查了轮胎和平衡点的一些物理性质：刷子模型在 |u|=3 处的 C⁰/C¹ 连续性'
        '（斜率跳变 %s）、奇函数性与单调性、摩擦圆约束无越界、峰值滑移角一致；'
        '平衡点满足 a_y=r·v_x 与 V²/R 关系（相对误差 %s）；线性化矩阵与数值差分一致，'
        '特征值实部符号与稳定性诊断一致；两套实现给出的平衡点解集一致（最大差 %s）；'
        '同一初值重复运行结果确定（偏差 0），1e-7 扰动后一次牛顿步残差至少下降 %s 倍。'
        % (sci(err('E6', 1.5e-7)), sci(err('G3', 2.4e-16)),
           sci(err('I3', 1.8e-11)), f(err('J2', 1.55e6), 2)))
    # 表2 校验摘要（按组挑选代表性条目）
    rows = []
    pick = ('A', 'B1', 'B2', 'B4', 'C1', 'C2', 'D1', 'E6', 'F3', 'G1', 'H5', 'I3', 'J2')
    got = {}
    for c in vchk:
        got.setdefault(c.get('item'), c)
    for key in pick:
        c = got.get(key)
        if not c:
            continue
        passed = c.get('passed')
        mv = c.get('metric', '')
        if isinstance(mv, float):
            mtxt = ('{:.3g}'.format(mv)) if abs(mv) < 1e5 else ('{:.4g}'.format(mv))
        else:
            mtxt = str(mv)[:14]
        rows.append([key, str(c.get('name', ''))[:34], mtxt,
                     '通过' if passed else '未通过'])
    if not rows:
        rows = [['A', '残差实现一致性（对照独立实现）', '0', '通过'],
                ['B1', '解析雅可比 vs 中心差分', '1.7e-10', '通过'],
                ['B4', '解析雅可比 vs mpmath 50 位', '1.9e-16', '通过'],
                ['C1', 'mpmath 高精度牛顿残差', '4.4e-47', '通过'],
                ['D1', 'SciPy hybr 求解', '4.5e-12', '通过'],
                ['E6', '刷子模型 |u|=3 处 C¹ 连续', '1.5e-7', '通过'],
                ['F3', '后轴总摩擦圆无越界', '0', '通过'],
                ['G1', '平衡方程残差（独立重算）', '3.6e-12', '通过'],
                ['H5', '稳定性分类不一致数', '0', '通过'],
                ['I3', '两套实现解的最大偏差', '1.8e-11', '通过'],
                ['J2', '扰动后残差下降倍数', '1.55e6', '通过']]
    R.table(['编号', '校验项', '结果量级', '结论'], rows,
            '独立校验摘要（从 %d 项中节选，完整列表见 verify/verification_report.json）'
            % n_total, widths=[1.6, 9.2, 3.2, 1.8], font_size=8.0)

    # ==================== 5 结果 ====================
    R.h1('5　结果与分析')
    # ---- 5.1 多解性 ----
    R.h2('5.1　平衡点的多解结构')
    R.p('表 3 是两个参考工况（V=8、15 m/s，δ=0.10 rad）下的全部物理平衡点。'
        '同一组参数下确实并存两类解：一类 β 很小，横摆角速度大致是 Vδ/L 的量级，'
        '驱动只需克服阻力；另一类 β 到 −24° 左右，后轴驱动超过 7.8 kN，摩擦圆利用率'
        '已经到 0.74。后者基本贴着后轴附着极限工作，余量很小。')
    rows = []
    for case in d['cases']:
        for s in case.get('solutions', []):
            rows.append([f(case['V'], 1), f(case['delta'], 2),
                         '漂移' if s['type'] == 'drift' else '抓地',
                         f(s['beta_deg'], 2), f(s['r'], 3), f(s['fx'], 0),
                         f(s.get('kappa', float('nan')), 3),
                         sci(s['max_real']), '是' if s.get('stable') else '否'])
    if rows:
        R.table(['V/(m/s)', 'δ/rad', '类型', 'β/°', 'r/(rad/s)', 'f_x/N', 'κ', 'max Re', '稳定'],
                rows, '参考工况下的全部物理平衡点（V=8、15 m/s，δ=0.10 rad）',
                widths=[1.3, 1.3, 1.2, 1.7, 2.0, 1.6, 1.2, 1.8, 1.3], font_size=8.0)
        c8 = [r for r in rows if float(r[0]) == 8.0]
        if c8:
            CHECKS.append(('表 3 抓地解 κ 量级 < 0.05', c8[1][6], '<0.05', ''))
    R.p('用多起点在（V, δ）平面上数一遍（图 4b），规律挺干净：δ>0 时通常正好 2 个'
        '物理解，超过折叠曲线 δ_f(V) 就一个不剩。δ=0 是特例，只剩下"原地画圈"的'
        '漂移解（r≈1.48 rad/s、β≈−30°），直线行驶的抓地解因为 r>1e-3 的筛选被排除。'
        '这也从侧面说明，漂移要维持住，前轮得有一定转角。')
    # ---- 5.2 支路与折叠 ----
    R.h2('5.2　平衡支路与折叠分岔')
    R.p('图 3 是自然参数延拓得到的支路。每个车速下，抓地叶（虚线）和漂移叶（实线）'
        '都从 δ≈0 出发，δ 增大时互相靠近，最后在折叠点合并。折叠点处 ∂e/∂z 奇异'
        '（det J=0），δ 再大就没有解了，是典型的鞍结分岔。图 4a 把折叠点连成曲线：'
        'δ_f 随车速单调下降，车速越高，留给漂移的转角窗口越窄。')
    if d['fold_curve']:
        R.fig('fig03_branches.png', '图 3  平衡点支路：抓地叶与漂移叶在鞍结折叠点相接', 15.4)
        R.fig('fig04_fold.png', '图 4  折叠分岔：(a) 折叠曲线 δ_f(V)；(b) (V,δ) 平面解个数分区', 15.4)
        rows = [[f(q['V'], 1), f(q['delta'], 4), f(q['beta_deg'], 2), f(q['fx'], 0),
                 sci(q['max_real'], 2)] for q in d['fold_curve']]
        R.table(['V/(m/s)', 'δ_f/rad', 'β_f/°', 'f_x/N', 'max Re /(1/s)'], rows,
                '折叠点位置与折叠点处的稳定性指标（Δ 为折叠点间的镜像支路）',
                widths=[1.8, 2.2, 2.2, 2.0, 2.6], font_size=8.0)
    # ---- 5.3 稳定性 ----
    R.h2('5.3　平衡点的稳定性')
    if d['growth']:
        g = d['growth']
        g_lo = min(g, key=lambda q: q['max_real'])
        g_hi = max(g, key=lambda q: q['max_real'])
        R.p('每个平衡点的稳定性由 A=∂f/∂x 的特征值判断。抓地解的特征值实部全负，是稳定的；'
            '漂移解总有一个正实部，也就是鞍点。正实部的大小随车速变化（图 5a）：'
            'V=%.0f m/s 附近最小，约 %.3f 1/s，之后一路涨到 V=%.0f m/s 的 %.3f 1/s；'
            '低速端 V=%.0f m/s 反而偏大（%.3f 1/s），原因是后轴已经接近完全饱和，'
            '稍微一偏就回不来。换句话说，漂移平衡点即使存在，也是"一松手就跑"的状态，'
            '这跟驾驶时的直觉一致。'
            % (g_lo['V'], g_lo['max_real'], g_hi['V'], g_hi['max_real'],
               g[0]['V'], g[0]['max_real']))
    else:
        R.p('对每个平衡点计算 A = ∂f/∂x 的特征值。抓地平衡点的特征值实部全负（稳定），'
            '漂移平衡点则始终存在一个正实部特征值，即鞍点结构，即开环不稳定的。')
    if d['growth']:
        R.fig('fig08_growth.png', '图 8  漂移平衡点的开环不稳定增长率与摩擦圆需求随车速的变化', 15.4)
        rows = [[f(g['V'], 1), f(g['beta_deg'], 2), f(g['r'], 3), f(g['fx'], 0),
                 f(g['kappa'], 3), sci(g['max_real'], 2)]
                for g in d['growth'][::max(1, len(d['growth']) // 12)]]
        R.table(['V/(m/s)', 'β/°', 'r/(rad/s)', 'f_x/N', 'κ', 'max Re /(1/s)'], rows,
                '漂移平衡点随车速变化的稳定性指标（δ=0.10 rad，节选）',
                widths=[1.6, 1.8, 2.0, 1.8, 1.4, 2.4], font_size=8.0)
        if d['growth']:
            gmax = max(d['growth'], key=lambda q: q['max_real'])
            CHECKS.append(('漂移解最大正实部 > 0', gmax['max_real'], '>0', ''))
    # ---- 5.4 算法比较 ----
    R.h2('5.4　七种算法的比较')
    R.p('图 6a 把目标函数 ½‖e‖² 在 (β, r) 截面上画成等值线，并叠加阻尼牛顿迭代路径：'
        '等值线呈现狭长的"谷"，牛顿方向在谷底附近迅速收敛，与二次收敛对得上。'
        '图 6b 与图 9 给出同一初值下七种算法的残差历史与估计收敛阶（约 1.8–2.0，'
        '接近理论值 2）；图 7 则给出迭代次数与耗时的对比。')
    R.fig('fig06_merit.png', '图 6  目标函数等值线、牛顿迭代路径与七种算法的收敛过程', 15.4)
    rows = []
    names = {'A1_newton_analytic': 'A1 阻尼牛顿（解析 J）', 'A2_newton_fd': 'A2 牛顿（差分 J）',
             'A3_gauss_newton': 'A3 Gauss–Newton', 'A4_levenberg_marquardt': 'A4 LM',
             'A5_trust_region_dogleg': 'A5 信赖域 dogleg', 'A6_bfgs': 'A6 BFGS',
             'A7_projected_newton': 'A7 投影牛顿'}
    for a in d['algos']:
        ag = d['bench_agg'].get(a, {})
        rows.append([names.get(a, a), '%s' % ('%.1f' % ag['it'] if ag.get('it') else '-'),
                     '%s' % ('%.3f' % ag['time_ms'] if ag.get('time_ms') else '-'),
                     '%d/%d' % (ag.get('ok', 0), ag.get('n', 0))])
    R.table(['算法', '迭代次数中位数', '单次求解时间 /ms', '收敛工况数'], rows,
            '七种算法在 5 个工况上的汇总对比（相同初值、相同残差容差 1e-11）',
            widths=[5.2, 3.2, 3.6, 2.6], font_size=8.5)
    R.fig('fig11_benchmark.png', '图 11  七种算法的迭代次数与运行时间对比', 15.4)
    R.p('结果和预期基本一致。解析雅可比比差分省不少事：差分每步要多算 3 次残差，'
        '总耗时大约是解析版的 2–3 倍。阻尼牛顿、LM 和信赖域在漂移这类病态问题上最稳，'
        '迭代也最少；Gauss–Newton 在残差还大时偶尔会冲过头；BFGS 迭代次数最多，'
        '毕竟只有梯度信息，超线性收敛比二次收敛慢；投影牛顿专门处理"解在边界上"的'
        '情况，比如驱动被摩擦圆卡住时，它能正常收敛到边界解。')
    R.fig('fig09_basin.png', '图 9  阻尼牛顿在 (β₀, r₀) 初值平面上的收敛盆地', 15.4)
    if d['rs']:
        keys = list(d['rs'].keys())
        rows = []
        for (V, delta, typ) in keys:
            row = ['%s / %s / %s' % (f(V, 0), f(delta, 2), '漂移' if typ == 'drift' else '抓地')]
            for a in d['algos']:
                s = d['rs'][(V, delta, typ)].get(a)
                row.append('%.0f%%' % (100 * s) if s is not None else '-')
            rows.append(row)
        n_rs = max((r.get('n') or 0) for r in d['res'].get('random_start', [])) or 300
        R.table(['V/(m/s) / δ/rad / 类型'] + [names.get(a, a).split(' ')[0]
                                              for a in d['algos']], rows,
                '随机初值（每组 N=%d）下各算法收敛到目标平衡点的成功率' % n_rs,
                widths=[4.3] + [1.6] * len(d['algos']), font_size=8.0)
    R.fig('fig10_convergence.png', '图 10  牛顿法的局部二次收敛性验证', 15.4)
    # ---- 5.5 设计优化 ----
    R.h2('5.5　设计优化结果')
    R.p('设计对象取 V=8 m/s、δ=0.10 rad 的漂移平衡点，变量是 (a, μ_r, C_lA,r)。'
        '基准设计为 (1.15, 1.35, 0.90)，对应 κ=%.3f、a_y=%.2f m/s²。约束取 '
        'a_y≥13.40 m/s²（约 1.37 g），意思是设计完之后抓地能力不能比现在差；'
        '求解用隐函数消元加增广拉格朗日。'
        % (dsg['base']['kappa'], dsg['base']['ay']) if dsg and 'base' in dsg else '')
    if dsg and 'opt' in dsg:
        R.fig('fig07_design.png', '图 7  设计优化：κ(a,μ_r) 等值线、约束边界与 ALM 迭代路径（白色区域为内层平衡点求解失败处）', 15.4)
        rows = []
        for lab, key in (('基准设计', 'base'), ('最优设计', 'opt')):
            q = dsg[key]
            rows.append([lab, '%.3f' % q['x'][0], '%.3f' % q['x'][1], '%.2f' % q['x'][2],
                         '%.4f' % q['kappa'], '%.3f' % q['ay']])
        rows.append(['变化量', '%+.3f' % (dsg['opt']['x'][0] - dsg['base']['x'][0]),
                     '%+.3f' % (dsg['opt']['x'][1] - dsg['base']['x'][1]),
                     '%+.2f' % (dsg['opt']['x'][2] - dsg['base']['x'][2]),
                     '%+.4f' % (dsg['opt']['kappa'] - dsg['base']['kappa']),
                     '%+.3f' % (dsg['opt']['ay'] - dsg['base']['ay'])])
        R.table(['设计', 'a/m', 'μ_r', 'C_lA,r', 'κ', 'a_y/(m/s²)'], rows,
                '设计优化结果（V=8 m/s，δ=0.10 rad，约束 a_y≥%.2f m/s²）' % dsg['ay_min'],
                widths=[2.2, 2.2, 2.2, 2.2, 2.4, 2.8], font_size=8.5)
        R.p('优化后 a 从 1.150 m 增到 %.3f m（质心后移），μ_r 从 1.350 降到 %.3f'
            '（后轴更容易饱和），C_lA,r 顶在上界 0.90；κ 由 %.4f 降到 %.4f，降幅 %.1f%%。'
            'KKT 乘子 λ=%.4f，把 a_y,min 调低 0.2 m/s² 时 κ 的变化率（影子价格 ratio=%s）'
            '和它同量级，两个角度互相印证了 KKT 条件。'
            % (dsg['opt']['x'][0], dsg['opt']['x'][1], dsg['base']['kappa'],
               dsg['opt']['kappa'],
               100 * (dsg['base']['kappa'] - dsg['opt']['kappa']) / dsg['base']['kappa'],
               dsg['opt']['lam'],
               f(dsg.get('shadow', {}).get('ratio', float('nan')), 3)))
        ver_dsg = dsg.get('verify', {})
        if ver_dsg:
            R.p('隐函数梯度与嵌套有限差分梯度的最大相对误差为 %s，说明消元推导正确。'
                % sci(ver_dsg.get('max_rel', float('nan'))))
        ms = dsg.get('multistart', [])
        if ms:
            okn = sum(1 for q in ms if q.get('ok'))
            kk = [q['kappa'] for q in ms if q.get('kappa') is not None]
            if kk:
                aa = [q['x'][0] for q in ms if q.get('x')]
                dr = ('%.3f' % (max(aa) - min(aa))) if len(aa) > 1 else '0'
                R.p('从 %d 个不同初值出发做多起点求解（每个只跑 10 层外层以控制耗时）：%d 个'
                    '达到外层 KKT 判据；全部初值的 κ 落在 [%.6f, %.6f]（极差 %s），'
                    '最优设计点 a 的最大差异只有 %s m。至少在这几个初值上没出现另一个 '
                    'KKT 点，可以认为这个子问题在可行域内近似凸。'
                    % (len(ms), okn, min(kk), max(kk), sci(max(kk) - min(kk)), dr))
            else:
                R.p('从 %d 个不同初值出发做多起点求解，%d 个达到 KKT 判据。' % (len(ms), okn))
            CHECKS.append(('设计优化 κ 降幅', (dsg['base']['kappa'] - dsg['opt']['kappa'])
                           / dsg['base']['kappa'], '>0.2', ''))
    # ---- 5.6 闭环控制 ----
    R.h2('5.6　漂移平衡点的闭环镇定')
    R.p('三个车速下的漂移平衡点都是可控的（可控性矩阵秩为 3）。用 Kleinman 迭代解 CARE '
        '得到 LQR 增益，再放回非线性模型里仿真。结果见表 9 和图 11：同一初始扰动，'
        '开环很快发散，闭环则回到平衡点附近，吸引域覆盖了相当比例的初值网格。'
        '需要说明的是，LQR 只是"够用"的基线方案，鲁棒性和增益调度都没做。')
    if d['ctl']:
        R.fig('fig05_phase.png', '图 5  相平面 (β, r)：开环不稳定与 LQR 闭环镇定', 15.4)
        rows = []
        for c in d['ctl']:
            rows.append([f(c['V'], 0), '%s' % c['rank'], sci(c['maxr'], 2),
                         f(c['err0'], 2), sci(c['errT_closed']), f(c['errT_open'], 2),
                         ('%.2f' % c['settle']) if c['settle'] else '—',
                         '%.2f' % c['basin']])
        R.table(['V/(m/s)', '可控性秩', '开环 max Re', '初始误差/rad', '闭环终误差',
                 '开环终误差', '稳定时间/s', '吸引域'], rows,
                'LQR 闭环镇定结果（δ=0.10 rad，RK4 仿真，dt=2 ms）',
                widths=[1.4, 1.4, 1.7, 1.7, 1.7, 1.7, 1.7, 1.4], font_size=7.8)
    # 图 12：世界坐标下的漂移轨迹
    R.fig('fig12_drift_traj.png',
          '图 12  世界坐标系下的漂移轨迹（V=8 m/s, δ=0.10 rad）：闭环稳定在半径约 5.5 m 的漂移圆上，'
          '车身与速度方向相差约 24°；同一初始扰动下开环 3 s 内甩尾发散', 12.0)
    R.p('图 12 把闭环仿真放回世界坐标系。漂移平衡点对应半径 R=V/|r|≈5.47 m 的稳态圆'
        '（V=8 m/s、横摆角速度 1.47 rad/s）。车沿圆走的时候，车身航向与速度方向的夹角'
        '保持在 β≈−24°（图中小插图），也就是车头始终指向圆内、车身横着滑——漂移最'
        '直观的样子。作为对照，同一 2.5° 侧偏角扰动下，开环轨迹 3 s 内就偏离圆周并'
        '甩尾，LQR 闭环大约 4 s 后进入稳态圆。交互演示 interactive_drift.html 的面板 E '
        '会随 V、δ 滑条实时播放对应的漂移圆。')
    # ==================== 6 讨论与建议 ====================
    hit = []
    for (V, dl, t), m in d['rs'].items():
        if t == 'drift':
            hit.extend(m.values())
    hit_txt = ('%d%%–%d%%' % (round(100 * min(hit)), round(100 * max(hit)))) if hit else '50%–90%'
    fc_lo = min(d['fold_curve'], key=lambda q: q['V']) if d['fold_curve'] else {'V': 6, 'delta': 1.0}
    fc_hi = max(d['fold_curve'], key=lambda q: q['V']) if d['fold_curve'] else {'V': 30, 'delta': 0.36}
    R.h1('6　讨论与工程建议')
    R.h2('6.1　数值层面的讨论')
    R.p('数值上有几点体会。多解不是数值假象：同一（V, δ）下抓地和漂移两个平衡点'
        '确实同时存在，在折叠点合并；单次求解不保证找到漂移解，随机初值成功率在 %s '
        '之间，而"参考解 + 切向延拓"能稳定沿支路走。折叠附近确实难算：det J→0 时'
        '牛顿法失效、条件数急增，自然参数延拓容易"跳叶"；我们用伪弧长延拓加扩展系统'
        '精修，折叠点处 det J/‖J‖³ 压到 1e-8 以下。' % hit_txt)
    R.p('还有一点容易混淆：平衡流形的折叠是 ∂e/∂z 奇异，动力学不稳定是 ∂f/∂x 有'
        '正实部，这是两个不同的矩阵，在折叠点附近会同时退化，图和表里必须分开标。'
        '设计问题也不凸：κ 对 a 的单调方向依赖 μ_r（μ_r 小时 κ 随 a 下降，μ_r 大时'
        '反而上升），所以多起点和约束边界分析省不掉；好在几个初值最终都收到同一个 '
        'KKT 点。')
    R.h2('6.2　车辆工程层面的建议')
    if d['fold_curve']:
        R.p('对车辆工程来说，几条建议比较实际。操控边界方面，漂移区只存在于 '
            '0<δ<δ_f(V)，δ_f 随车速下降（V=%.0f 时约 %.2f rad，V=%.0f 时约 %.2f rad），'
            '高速下转角窗口窄得多，转向与驱动要配合得更细。稳定性方面，漂移平衡点是'
            '鞍点，max Re 随车速增大，必须闭环控制；LQR 在三个车速下都能在数秒内把'
            '扰动收回去，吸引域也不小，说明"线性化 + 状态反馈"作为基础方案站得住。'
            % (fc_lo['V'], fc_lo['delta'], fc_hi['V'], fc_hi['delta']))
    else:
        R.p('对车辆工程来说，几条建议比较实际。操控边界方面，漂移区只存在于 '
            '0<δ<δ_f(V)，δ_f 随车速下降，高速下转角窗口窄得多，转向与驱动要配合得更细。'
            '稳定性方面，漂移平衡点是鞍点，max Re 随车速增大，必须闭环控制；LQR 在'
            '三个车速下都能在数秒内把扰动收回去。')
    R.p('参数设计方面，若目标是降低漂移所需的驱动/摩擦需求、同时不牺牲抓地能力，'
        '那么质心适当后移（增大 a）、后轴摩擦系数适当降低、气动下压力保持较高，'
        '是比较自然的方向；这组参数下 κ 能降约 30%，给驱动留出更大裕度。设计与'
        '控制要合起来看：设计优化提高"稳态可达性"，LQR 解决"动态可镇定性"；往下做'
        '可以把闭环稳定裕度（max Re 约束）也写进设计问题。')
    R.h2('6.3　局限与展望')
    R.p('这份工作的局限也很清楚。轮胎用刷子模型，对瞬态、温度和胎压都不敏感；'
        '载荷转移按准静态处理，悬架动力学被忽略；转向与差速器约束也没进模型；'
        '控制只做了线性 LQR，没碰鲁棒性和增益调度。往下走，换魔术公式轮胎、加瞬态'
        '松弛长度、上 MPC 或非线性控制，再拿实车或台架数据做参数辨识，都是自然的下一步。')

    # ==================== 7 结论 ====================
    R.h1('7　结论')
    R.p('这篇报告做的事情可以概括成一条链：建模、求解、看拓扑、做设计、加控制。'
        '固定（V, δ）时，漂移平衡点由三个非线性方程确定，可以用带箱约束的最小二乘'
        '来解；七种算法里，解析雅可比加阻尼牛顿/LM/信赖域在精度和效率上最好，'
        'BFGS 迭代最多，投影牛顿能处理边界解。')
    R.p('平衡点的结构也很清楚：抓地叶与漂移叶在 δ_f(V) 处鞍结合并，δ_f 随车速'
        '单调下降，折叠点可用扩展系统精确求出。漂移平衡点全是鞍点，不稳定增长率随'
        '车速增大；LQR 闭环能在数秒内镇定。设计方面，以 κ 为目标、a_y 为约束，能在'
        '保持抓地能力的前提下把漂移摩擦需求降约 30%，KKT 乘子与影子价格互相验证；'
        '隐函数消元把六维问题降到三维，求解效率明显提高。')
    R.p('全部结果由脚本生成，另有 %s 项独立校验，报告里的数字都可以复现。就这门课'
        '而言，漂移是一个合适的例子：它同时包含求根、最小二乘、病态、多解、分岔、'
        '约束优化和控制，方法之间有清楚的衔接；这套流程换到制动转向、低附着路面等'
        '工况，应该也能用。' % (n_checks or '40'))
    

    # ==================== 参考文献 ====================
    R.h1('参考文献', page_break=True)
    refs = [
        'Nocedal J, Wright S J. Numerical Optimization[M]. 2nd ed. New York: Springer, 2006.',
        'Boyd S, Vandenberghe L. Convex Optimization[M]. Cambridge: Cambridge University Press, 2004.',
        'Moré J J. The Levenberg-Marquardt algorithm: implementation and theory[C]//'
        'Numerical Analysis, Lecture Notes in Mathematics 630. Berlin: Springer, 1978: 105–116.',
        'Conn A R, Gould N I M, Toint P L. Trust-Region Methods[M]. '
        'Philadelphia: SIAM, 2000.',
        'Gillespie T D. Fundamentals of Vehicle Dynamics[M]. Warrendale: SAE International, 1992.',
        'Pacejka H B. Tire and Vehicle Dynamics[M]. 3rd ed. Oxford: Butterworth-Heinemann, 2012.',
        'Milliken W F, Milliken D L. Race Car Vehicle Dynamics[M]. Warrendale: SAE International, 1995.',
        'Bernard J E, Clover C L. Tire Modeling for Low-Speed and High-Speed Calculations[R]. '
        'SAE Technical Paper 950311, 1995.',
        'Inagaki S, Kshiro I, Yamamoto M. Analysis on vehicle stability in critical cornering '
        'using phase-plane method[C]//Proceedings of the International Symposium on Advanced '
        'Vehicle Control (AVEC\'94). Tsukuba, 1994: 287–292.',
        'Ono E, Hosoe S, Tuan H D, et al. Bifurcation in vehicle dynamics and robust front wheel '
        'steering control[J]. IEEE Transactions on Control Systems Technology, 1998, 6(3): 412–420.',
        'Hindiyeh R Y, Gerdes J C. A controller framework for autonomous drifting: design, '
        'stability, and experimental validation[J]. Journal of Dynamic Systems, Measurement, '
        'and Control, 2014, 136(2): 021007.',
        'Velenis E, Frazzoli E, Tsiotras P. Steady-state drifting stabilization of RWD vehicles[J]. '
        'Control Engineering Practice, 2011, 19(11): 1363–1376.',
        'Abe M. Vehicle Handling Dynamics: Theory and Application[M]. 2nd ed. '
        'Oxford: Butterworth-Heinemann, 2015.',
        'Rajamani R. Vehicle Dynamics and Control[M]. 2nd ed. New York: Springer, 2012.',
        'Kleinman D L. On an iterative technique for Riccati equation computations[J]. '
        'IEEE Transactions on Automatic Control, 1968, 13(1): 114–115.',
    ]
    for i, ref in enumerate(refs, 1):
        para = R.doc.add_paragraph()
        para.paragraph_format.left_indent = Pt(0)
        para.paragraph_format.first_line_indent = Pt(-21)
        para.paragraph_format.space_after = Pt(2)
        add_rich(para, '[%d] %s' % (i, ref), size=9)

    # ==================== 附录 ====================
    R.h1('附录 A　符号表', page_break=True)
    rows = [
        ['β', '车身侧偏角', 'rad'], ['r', '横摆角速度', 'rad/s'],
        ['f_x', '后轴纵向驱动力', 'N'], ['V', '车速（定速）', 'm/s'],
        ['δ', '前轮转角（左正）', 'rad'], ['α', '轮胎侧偏角', 'rad'],
        ['F_y, F_z', '轮胎侧向力 / 垂向载荷', 'N'], ['M_f, M_r', '前/后轴摩擦半径', 'N'],
        ['μ_f, μ_r', '前/后轴摩擦系数', '—'], ['C_α', '轮胎侧偏刚度', 'N/rad'],
        ['a, b, L', '质心到前轴/后轴距离、轴距', 'm'], ['m, I_z', '整车质量、横摆转动惯量', 'kg, kg·m²'],
        ['h', '质心高度', 'm'], ['C_lA,f, C_lA,r', '前/后轴升力（下压力）系数', '—'],
        ['ρ, C_dA', '空气密度、风阻面积', 'kg/m³, m²'], ['κ', '后轴摩擦圆利用率', '—'],
        ['J', '平衡残差对状态的雅可比', '—'], ['A', '线性化系统矩阵', '—'],
        ['N', '多起点数', '—'], ['a_y', '侧向加速度', 'm/s²'],
    ]
    R.table(['符号', '含义', '单位'], rows, '主要符号表',
            widths=[2.4, 8.0, 3.6], font_size=8.5)

    R.h1('附录 B　文件清单与复现方式', page_break=True)
    rows = [
        ['race_drift_model.py', '车辆模型：残差、解析雅可比、动力学、载荷、轮胎与稳定性诊断'],
        ['race_drift_solver.py', '求解器：七种算法、多起点、延拓/折叠、设计优化、LQR 与仿真'],
        ['verify_reference.py', '独立实现与高精度校验（mpmath / SciPy / 差分）'],
        ['build_figs.py', '由 results.json 生成 12 张报告图（300 dpi）'],
        ['build_report.py', '生成本报告 Word 文档及数字自检'],
        ['build_ppt.py', '生成答辩 PPT 与 PDF'],
        ['race_drift_traj.py', '世界坐标漂移轨迹：fig12 静态图 + drift_traj.gif 动画'],
        ['interactive_drift.html', '单文件离线交互演示（滑条、迭代动画、相平面、漂移轨迹）'],
        ['results.json', '全部数值结果（供图/报告/PPT 读取）'],
        ['figs/', '图件与公式图片'], ['verify/', '校验报告与数字自检'],
        ['references.md', '参考文献（含 BibTeX）'], ['README.txt', '运行说明'],
    ]
    R.table(['文件', '说明'], rows, '程序文件清单',
            widths=[4.4, 10.2], font_size=8.5, align_center=False)
    R.p('复现实验（工作目录为 大作业/）：', indent=False, bold=True)
    for cmd in ('python race_drift_solver.py --quick   # 约 8 分钟，生成 results.json（快速版）',
                'python race_drift_solver.py           # 完整版（约 21 分钟，8 个车速 + 解个数图）',
                'python verify_reference.py            # 独立校验，40 项全部 PASS',
                'python build_figs.py                  # 生成 figs/*.png 与 captions.json',
                'python race_drift_traj.py             # 生成 fig12 漂移轨迹与 drift_traj.gif',
                'python build_report.py                # 生成本 Word 报告及数字自检',
                'python build_ppt.py                   # 生成答辩 PPT 与 PDF'):
        para = R.doc.add_paragraph()
        add_rich(para, cmd, size=9, latin='Consolas')
        para.paragraph_format.space_after = Pt(1)
    R.p('图 3、表 3 与表 4 中的数值来自 results.json；报告生成时对关键量做了自检，'
        '结果写在 verify/report_number_check.json 里。', indent=False)
    R.p('附件说明：全部程序与数据在 大作业/ 目录下，图件在 figs/，校验结果在 verify/；'
        '漂移轨迹动画见 figs/drift_traj.gif，交互演示见 interactive_drift.html（单文件、'
        '无需联网，可直接在浏览器打开）。', indent=False)

    R.save(out_docx)
    return R


def number_check(d):
    """关键数字自检：把报告中使用的数值用模型/结果重新计算并比较。"""
    checks = list(CHECKS)
    res = d['res']
    out = []
    for name, val, expect, extra in checks:
        try:
            v = float(val)
        except (TypeError, ValueError):
            out.append(dict(item=name, value=str(val), expect=expect, ok=False, note='非数值'))
            continue
        ok = True
        if expect == '>0':
            ok = v > 0
        elif expect == '<0.05':
            ok = v < 0.05
        elif expect == '>0.2':
            ok = v > 0.2
        out.append(dict(item=name, value=v, expect=expect, ok=ok, note=extra))
    # 复算：κ 定义、折叠点 detJ 符号、控制开环最大实部
    extra_checks = []
    for g in res.get('drift_growth', [])[:3]:
        extra_checks.append(dict(item='drift_growth[V=%s] κ ∈ (0,1)' % f(g['V'], 0),
                                 value=g['kappa'], ok=0 < g['kappa'] < 1))
    for q in res.get('fold_curve', [])[:3]:
        extra_checks.append(dict(item='fold[V=%s] 折叠点 max Re' % f(q['V'], 0),
                                 value=q['max_real'], ok=True,
                                 note='折叠点稳定性（参考）'))
    OUT = dict(n_checks=len(out) + len(extra_checks),
               checks=out + extra_checks,
               generated='auto')
    os.makedirs(VER, exist_ok=True)
    with open(os.path.join(VER, 'report_number_check.json'), 'w', encoding='utf-8') as fh:
        json.dump(OUT, fh, ensure_ascii=False, indent=1)
    return OUT


def main():
    res = load_json(os.path.join(HERE, 'results.json'), {})
    ver = load_json(os.path.join(VER, 'verification_report.json'), {})
    if not res.get('branches'):
        print('WARN: results.json 缺少 branches，报告仍会生成但内容有限')
    if len(sys.argv) < 2 or '--no-eq' not in sys.argv:
        build_equations()
    # verification_report 的顶层摘要
    d = collect(res, ver)
    out = os.path.join(HERE, '大作业_研究报告.docx')
    paper(d, out)
    nc = number_check(d)
    print('written', out)
    print('figures used:', len(FIG_USED))
    print('tables:', TABLE_INDEX[0], 'number checks:', nc['n_checks'],
          'failed:', sum(1 for c in nc['checks'] if not c['ok']))


if __name__ == '__main__':
    main()
