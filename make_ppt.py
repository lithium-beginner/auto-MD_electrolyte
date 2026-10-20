#!/usr/bin/env python3
"""把流程图与温度研究结果合成汇报用 PPTX。"""
import copy, json, pathlib
from pptx import Presentation
from pptx.util import Inches as In, Pt, Emu
from pptx.dml.color import RGBColor as C
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# ---- 设计令牌（与 HTML 报告同一套）----
SURF   = C(0xFC, 0xFC, 0xFB)
INK    = C(0x0B, 0x0B, 0x0B)
INK2   = C(0x52, 0x51, 0x4E)
MUTED  = C(0x89, 0x87, 0x81)
GRID   = C(0xE1, 0xE0, 0xD9)
AXIS   = C(0xC3, 0xC2, 0xB7)
S1, S2, S3, S4, S5 = (C(0x2A,0x78,0xD6), C(0xEB,0x68,0x34), C(0x1B,0xAF,0x7A),
                      C(0xED,0xA1,0x00), C(0xE8,0x7B,0xA4))
GOOD, WARN, CRIT = C(0x0C,0xA3,0x0C), C(0xFA,0xB2,0x19), C(0xD0,0x3B,0x3B)
WHITE = C(0xFF, 0xFF, 0xFF)

EA_FONT, LAT_FONT = "微软雅黑", "Segoe UI"
W, H = In(13.333), In(7.5)
M = In(0.72)                       # 页边距
ASSETS = pathlib.Path("ppt_assets")
RAW = json.load(open("viz_data.json"))

prs = Presentation()
prs.slide_width, prs.slide_height = W, H
BLANK = prs.slide_layouts[6]


# ---------- 基础工具 ----------
def set_ea(run):
    """python-pptx 只设拉丁字体，东亚字体要直接写 XML。"""
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        e = rPr.find(qn(tag))
        if e is None:
            e = rPr.makeelement(qn(tag), {})
            rPr.append(e)
        e.set("typeface", EA_FONT)


def tb(slide, x, y, w, h, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    tf.paragraphs[0].alignment = align
    return tf


def put(tf, text, size=16, color=INK2, bold=False, space_after=6,
        align=None, first=False, line=1.35):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    if align is not None:
        p.alignment = align
    p.space_after = Pt(space_after)
    p.line_spacing = line
    r = p.add_run(); r.text = text
    r.font.size, r.font.bold, r.font.color.rgb = Pt(size), bold, color
    r.font.name = LAT_FONT
    set_ea(r)
    return p


def bg(slide):
    f = slide.background.fill
    f.solid(); f.fore_color.rgb = SURF


def rect(slide, x, y, w, h, fill=None, line=None, lw=1.0, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
         adj=0.04):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try:
            s.adjustments[0] = adj
        except Exception:
            pass
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid(); s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line; s.line.width = Pt(lw)
    s.shadow.inherit = False
    return s


def head(slide, title, sub=None):
    """统一的页眉：标题 + 可选副标题 + 分隔线"""
    tf = tb(slide, M, In(0.46), W - 2*M, In(0.5))
    put(tf, title, 27, INK, True, 0, first=True)
    y = In(1.06)
    if sub:
        tf2 = tb(slide, M, In(1.03), W - 2*M, In(0.34))
        put(tf2, sub, 14, INK2, False, 0, first=True)
        y = In(1.46)
    ln = rect(slide, M, y, W - 2*M, Emu(9525), fill=GRID, shape=MSO_SHAPE.RECTANGLE)
    return y + In(0.26)


def page_no(slide, n):
    tf = tb(slide, W - M - In(1.0), H - In(0.52), In(1.0), In(0.3), PP_ALIGN.RIGHT)
    put(tf, str(n), 11, MUTED, False, 0, first=True)


def pic(slide, name, cx, top, max_w, max_h):
    """按比例缩放并水平居中于 cx"""
    from PIL import Image
    p = ASSETS / name
    iw, ih = Image.open(p).size
    sc = min(max_w / iw, max_h / ih)
    w, h = int(iw * sc), int(ih * sc)
    slide.shapes.add_picture(str(p), int(cx - w / 2), top, w, h)
    return h


def new(title=None, sub=None):
    s = prs.slides.add_slide(BLANK); bg(s)
    y = head(s, title, sub) if title else In(0.6)
    return s, y


# ---------- 数据 ----------
T = RAW["temps"]; TC = [t["T_C"] for t in T]
mean = lambda a: sum(a)/len(a)
A = RAW["arrhenius"]
g = lambda f: [mean([f(s) for s in t["seeds"]]) for t in T]
rho, sNE = g(lambda s: s["rho"]), g(lambda s: s["sNE"])
DLi, DPF = g(lambda s: s["D"]["Li"]["D"]), g(lambda s: s["D"]["PF6"]["D"])
free = g(lambda s: s["pair"]["0_anions"])
shEC, shPF = g(lambda s: s["shell"].get("EC", 0)), g(lambda s: s["shell"].get("PF6", 0))
tLi = [a/(a+b) for a, b in zip(DLi, DPF)]

n = 0

# ============ 1 封面 ============
s = prs.slides.add_slide(BLANK); bg(s)
rect(s, 0, 0, Emu(int(In(0.16))), H, fill=S1, shape=MSO_SHAPE.RECTANGLE)
tf = tb(s, In(1.15), In(2.25), W - In(2.3), In(1.3))
put(tf, "电解液温度依赖性分子动力学研究", 40, INK, True, 10, first=True)
put(tf, "1 M LiPF₆ in EC:EMC (3:7 w/w) + 2 wt% VC + 1.2 wt% FEC", 19, INK2, False, 0)
rect(s, In(1.15), In(4.32), In(1.3), Emu(28575), fill=S1, shape=MSO_SHAPE.RECTANGLE)
tf = tb(s, In(1.15), In(4.72), W - In(2.3), In(1.1))
put(tf, "0 / 25 / 45 / 60 °C　·　每温度 2 个独立种子　·　生产段 20 ns　·　共 8 次模拟",
    15, INK2, False, 6, first=True)
put(tf, "基于 auto-MD_electrolyte 自动化工作流　|　OpenMM · GAFF2/AM1-BCC · NVIDIA H20 ×8",
    13, MUTED, False, 0)
n += 1

# ============ 2 汇报内容 ============
s, y = new("本次汇报内容")
items = [("1", "工具", "auto-MD_electrolyte 做什么、怎么做", S1),
         ("2", "本次研究", "同一配方在四个温度下的完整对比", S2),
         ("3", "发现", "三条规律，其中一条与直觉相反", S3),
         ("4", "边界", "哪些结果可用、哪些不可用", S4)]
bw = (W - 2*M - In(0.42)) / 4
for i, (num, t1, t2, col) in enumerate(items):
    x = M + i * (bw + In(0.14))
    rect(s, x, y + In(0.3), bw, In(2.5), fill=C(0xF4,0xF4,0xF1), line=GRID)
    rect(s, x, y + In(0.3), bw, Emu(38100), fill=col, shape=MSO_SHAPE.RECTANGLE)
    tf = tb(s, x + In(0.26), y + In(0.62), bw - In(0.52), In(2.0))
    put(tf, num, 30, col, True, 8, first=True)
    put(tf, t1, 17, INK, True, 7)
    put(tf, t2, 13, INK2, False, 0)
tf = tb(s, M, y + In(3.1), W - 2*M, In(0.6))
put(tf, "核心结论：升温让离子跑得更快（扩散 ×9.9），但同时让它们更容易抱团"
        "（自由 Li⁺ 由 16.6% 降到 2.6%），两者相抵后电导只涨 7.3 倍。",
    16, INK, False, 0, first=True)
n += 1; page_no(s, n)

# ============ 3 流程总览 ============
s, y = new("工具：auto-MD_electrolyte 做什么",
           "把一份「配方表」自动变成一份「性质报告」—— 人只需写清楚电解液里有什么、各占多少")
stages = [("输入", "配方 JSON", "组分 · SMILES\n质量分数 · 模拟参数", S1),
          ("步骤 1", "解析与拆盐", "质量分数 → 分子数\nRDKit 按形式电荷拆盐", S2),
          ("步骤 2", "参数化与装箱", "查力场参数库\nPackmol 填充盒子", S3),
          ("步骤 3", "跑 MD", "最小化 → NVT → NPT\n→ 定容生产段", S4),
          ("步骤 4", "性质分析", "RDF · 溶剂化结构\n扩散 · 电导率", S5)]
bw = (W - 2*M - In(4*0.30)) / 5
for i, (tag, name, desc, col) in enumerate(stages):
    x = M + i * (bw + In(0.30))
    rect(s, x, y + In(0.45), bw, In(2.35), fill=C(0xF4,0xF4,0xF1), line=GRID)
    rect(s, x, y + In(0.45), bw, Emu(38100), fill=col, shape=MSO_SHAPE.RECTANGLE)
    tf = tb(s, x + In(0.2), y + In(0.70), bw - In(0.4), In(2.0))
    put(tf, tag, 12, col, True, 5, first=True)
    put(tf, name, 16, INK, True, 8)
    put(tf, desc, 12, INK2, False, 0, line=1.3)
    if i < 4:
        ar = rect(s, x + bw + In(0.055), y + In(1.48), In(0.19), In(0.19),
                  fill=AXIS, shape=MSO_SHAPE.ISOSCELES_TRIANGLE)
        ar.rotation = 90
tf = tb(s, M, y + In(3.15), W - 2*M, In(1.0))
put(tf, "每一步都把产物和校验信息落盘，下一步先验再算。", 16, INK, True, 7, first=True)
put(tf, "跑 MD 前会逐个核对输入文件的 SHA256，被改动过就拒绝运行；"
        "Packmol 的原子顺序要和拓扑逐一对上；单原子离子（如 Li⁺）找不到文献参数时直接报错，"
        "不允许自动生成。—— 保证的是「不悄悄出错」，而不是「结果一定准」。",
    14, INK2, False, 0)
n += 1; page_no(s, n)

# ============ 4 体系与方法 ============
s, y = new("本次研究：体系与方法")
rows = [("配方", "EC 25.29% · EMC 59.01% · VC 2.00% · FEC 1.20% · LiPF₆ 12.50%（质量分数）"),
        ("分子数", "EC 296 · EMC 584 · VC 24 · FEC 11 · Li⁺ 85 · PF₆⁻ 85　＝ 1085 个分子 / 12702 个原子"),
        ("盐浓度", "初始盒 1.0038 mol/L（NPT 松弛后 0.955–1.023）"),
        ("力场", "GAFF2 / AM1-BCC，未做电荷缩放；Li⁺ 取自 Joung–Cheatham TIP3P 模型"),
        ("盒子", "5.2³ nm³，初始密度 1.2164 g/cm³"),
        ("流程", "能量最小化 → NVT 200 ps → NPT 2 ns → 固定末态体积 NVT 生产 20 ns"),
        ("采样", "帧间隔 10 ps（2000 帧）；每温度 2 个独立种子：不同 Packmol 装箱 + 不同初速度"),
        ("算力", "NVIDIA H20 ×8 一对一并行，单卡约 460 ns/day，每任务 63–64 分钟")]
rh = In(0.47)
for i, (k, v) in enumerate(rows):
    yy = y + In(0.12) + i * rh
    if i % 2 == 0:
        rect(s, M, yy, W - 2*M, rh, fill=C(0xF4,0xF4,0xF1), shape=MSO_SHAPE.RECTANGLE)
    tf = tb(s, M + In(0.22), yy + In(0.10), In(1.5), In(0.33))
    put(tf, k, 14, MUTED, False, 0, first=True)
    tf = tb(s, M + In(1.85), yy + In(0.09), W - 2*M - In(2.1), In(0.34))
    put(tf, v, 14.5, INK, False, 0, first=True)
n += 1; page_no(s, n)

# ============ 5 结果总览 ============
s, y = new("结果总览", "± 为 2 个独立种子的半极差，仅反映种子间散布")
hdr = ["温度", "密度 (g/cm³)", "D(Li⁺) (m²/s)", "σ_NE (S/m)", "壳层 EC", "壳层 PF₆⁻", "自由 Li⁺"]
data = [[f"{TC[i]} °C", f"{rho[i]:.4f}", f"{DLi[i]:.2e}", f"{sNE[i]:.3f}",
         f"{shEC[i]:.2f}", f"{shPF[i]:.2f}", f"{free[i]:.1f}%"] for i in range(4)]
cw = [In(1.3)] + [In(1.76)] * 6
tbl = s.shapes.add_table(5, 7, M, y + In(0.3), sum(cw, In(0)), In(2.5)).table
for j, w_ in enumerate(cw):
    tbl.columns[j].width = w_
tbl.rows[0].height = In(0.52)
for j, t in enumerate(hdr):
    c = tbl.cell(0, j); c.text = ""
    c.fill.solid(); c.fill.fore_color.rgb = C(0xF4,0xF4,0xF1)
    c.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = c.text_frame.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = t
    r.font.size, r.font.bold, r.font.color.rgb = Pt(13), True, INK2
    r.font.name = LAT_FONT; set_ea(r)
for i, row in enumerate(data, start=1):
    tbl.rows[i].height = In(0.49)
    for j, t in enumerate(row):
        c = tbl.cell(i, j); c.text = ""
        c.fill.solid(); c.fill.fore_color.rgb = SURF if i % 2 else C(0xF9,0xF9,0xF7)
        c.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = c.text_frame.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = t
        r.font.size, r.font.color.rgb = Pt(13.5), INK
        r.font.bold = (j == 0)
        r.font.name = LAT_FONT; set_ea(r)
tf = tb(s, M, y + In(3.1), W - 2*M, In(0.9))
put(tf, "0 → 60 °C：扩散 ×9.9　|　电导 ×7.3　|　密度 −5.7%　|　"
        "自由 Li⁺ 16.6% → 2.6%", 17, INK, True, 0, first=True)
n += 1; page_no(s, n)


# ---------- 图表页模板 ----------
def chart_slide(title, sub, img, note, note_bold=None):
    global n
    s, y = new(title, sub)
    h = pic(s, img, W // 2, y + In(0.16), int(W - 2*M), int(In(3.95)))
    ty = y + In(0.16) + Emu(h) + In(0.26)
    tf = tb(s, M, ty, W - 2*M, In(1.0))
    if note_bold:
        put(tf, note_bold, 16, INK, True, 6, first=True)
        put(tf, note, 14, INK2, False, 0)
    else:
        put(tf, note, 15, INK2, False, 0, first=True)
    n += 1; page_no(s, n)
    return s


chart_slide("结果 1　密度随温度线性下降",
            "生产段为定容 NVT，密度由 NPT 末帧体积决定；误差杠为种子间半极差",
            "01_density.png",
            "纯热膨胀效应，与实验定性一致。种子间散布 0.2–1.6%，来自「取 NPT 末帧体积而非平均体积」这一实现选择。",
            f"温度系数 −0.00110 g·cm⁻³·°C⁻¹，0 → 60 °C 下降 5.7%")

chart_slide("结果 2　四种组分的扩散系数严格服从 Arrhenius",
            "纵轴对数、横轴 1000/T；四条线近乎平行且笔直，说明该温区内扩散机制一致",
            "02_arrhenius.png",
            "Li⁺ 与 PF₆⁻ 两条线几乎重合（下方），EC 与 EMC 两条线几乎重合（上方）—— "
            "阴阳离子迁移速度相同，这一点在后面会成为「强缔合」的关键证据。",
            "拟合 R² 均 ≥ 0.98")

chart_slide("结果 3　活化能：Li⁺ 的迁移能垒最高之一",
            "由四个温度点拟合 ln X = ln A − Eₐ/RT",
            "04_ea.png",
            "Li⁺ 比 PF₆⁻ 高 1.5 kJ/mol —— 它迁移时要拖着整个溶剂化壳层走。"
            "σ_NE 的活化能最低，因为它同时受到离子缔合加剧的反向影响。")

chart_slide("结果 4　电导率随温度上升，但涨幅小于扩散",
            "Nernst–Einstein 电导率；忽略离子关联，是上限估计",
            "03_sigma.png",
            "扩散涨 9.9 倍而电导只涨 7.3 倍。差额去哪了？—— 被升温同时加剧的离子缔合吃掉了，见下一页。",
            "0 → 60 °C：σ_NE 0.067 → 0.485 S/m（×7.3）")

chart_slide("结果 5　Li⁺ 第一壳层：EC 被 PF₆⁻ 系统性置换",
            "3.2 Å 内按分子种类计数；VC + FEC 合计始终 < 0.07，图中为最窄的那条",
            "05_shell.png",
            "升温过程中 EC 从 1.02 降到 0.53，而 PF₆⁻ 从 1.15 升到 1.67。"
            "壳层总数基本不变（约 4 个分子），发生的是「溶剂让位给阴离子」。")

chart_slide("结果 6　升温促进离子缔合 —— 与直觉相反",
            "有序类别，故采用单色阶：颜色越深代表缔合越强",
            "06_pairing.png",
            "完全无阴离子接触的「自由」Li⁺ 从 16.6% 降到 2.6%；≥2 个阴离子的聚集态从 28% 升到 54%。",
            "通常认为升温促进解离，这里恰好相反")

# ============ 机制解释 ============
s, y = new("为什么升温反而促进缔合？", "在本模型内自洽，有两个相互叠加的驱动力")
boxes = [("熵驱动缔合",
          "Li⁺ 与 PF₆⁻ 成对，会把原先被束缚在溶剂化壳层里的 EC 分子释放到本体，"
          "体系平动熵增加。温度越高，自由能里 −TΔS 项的权重越大，缔合态越有利。", S1),
         ("密度降低削弱屏蔽",
          "升温使盒体积增大约 6%，介质的静电屏蔽能力下降，"
          "裸库仑吸引相对增强，离子更容易靠在一起。", S2)]
bw2 = (W - 2*M - In(0.3)) / 2
for i, (t1, t2, col) in enumerate(boxes):
    x = M + i * (bw2 + In(0.3))
    rect(s, x, y + In(0.3), bw2, In(1.95), fill=C(0xF4,0xF4,0xF1), line=GRID)
    rect(s, x, y + In(0.3), Emu(38100), In(1.95), fill=col, shape=MSO_SHAPE.RECTANGLE)
    tf = tb(s, x + In(0.3), y + In(0.56), bw2 - In(0.6), In(1.5))
    put(tf, t1, 18, INK, True, 9, first=True)
    put(tf, t2, 14, INK2, False, 0)
rect(s, M, y + In(2.55), W - 2*M, In(1.35), fill=C(0xFC,0xF8,0xEC), line=WARN)
rect(s, M, y + In(2.55), Emu(38100), In(1.35), fill=WARN, shape=MSO_SHAPE.RECTANGLE)
tf = tb(s, M + In(0.3), y + In(2.80), W - 2*M - In(0.6), In(1.0))
put(tf, "⚠　趋势方向可取，但绝对程度几乎肯定被夸大了", 17, INK, True, 7, first=True)
put(tf, "60 °C 下仅 2.6% 的自由 Li⁺ 不符合 1 M 碳酸酯电解液的实际解离状况。"
        "本次使用的是未做电荷缩放的全电荷非极化力场，会系统性高估离子缔合。"
        "请引用「随温度升高缔合增强」这个方向，不要引用具体百分比。", 14, INK2, False, 0)
n += 1; page_no(s, n)

# ============ 规律总结 ============
s, y = new("三条规律")
pts = [("输运严格服从 Arrhenius",
        f"R² ≥ 0.98。Li⁺ 活化能 {A['D_Li']['Ea']:.1f} kJ/mol，比 PF₆⁻ 的 "
        f"{A['D_PF6']['Ea']:.1f} 高 1.5 —— Li⁺ 要拖着溶剂化壳层迁移。", S1),
       ("升温促进离子缔合（反直觉）",
        "Li⁺ 第一壳层的 EC 被 PF₆⁻ 置换，自由 Li⁺ 由 16.6% 降至 2.6%。"
        "这也解释了为何电导涨幅（×7.3）小于扩散涨幅（×9.9）。", S2),
       ("迁移数接近 0.5",
        f"t(Li⁺) = {min(tLi):.2f}–{max(tLi):.2f}，即 D(Li⁺) ≈ D(PF₆⁻)。"
        "阴阳离子作为近中性离子对协同迁移 —— 强缔合的直接证据。"
        "实验电化学迁移数通常 0.3–0.4，本模型偏高也指向缔合过强。", S3)]
for i, (t1, t2, col) in enumerate(pts):
    yy = y + In(0.26) + i * In(1.72)
    rect(s, M, yy, W - 2*M, In(1.5), fill=C(0xF4,0xF4,0xF1), line=GRID)
    circ = rect(s, M + In(0.34), yy + In(0.45), In(0.6), In(0.6), fill=col,
                shape=MSO_SHAPE.OVAL)
    ctf = circ.text_frame; ctf.margin_left = ctf.margin_right = 0
    ctf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = ctf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = str(i + 1)
    r.font.size, r.font.bold, r.font.color.rgb = Pt(20), True, WHITE
    r.font.name = LAT_FONT; set_ea(r)
    tf = tb(s, M + In(1.2), yy + In(0.26), W - 2*M - In(1.6), In(1.2))
    put(tf, t1, 18, INK, True, 7, first=True)
    put(tf, t2, 14, INK2, False, 0)
n += 1; page_no(s, n)

# ============ 局限 1 ============
s, y = new("边界一　集体 Einstein 电导率未收敛，已作废",
           "列出以免被误引 —— 这是本次唯一一个计算了但不能用的量")
h = pic(s, "07_sigma_ce.png", W // 2, y + In(0.1), int(W - 2*M - In(1.2)), int(In(3.3)))
tf = tb(s, M, y + In(0.1) + Emu(h) + In(0.22), W - 2*M, In(1.2))
put(tf, "出现负值（0 °C 种子2 = −0.0006，R² = 0.065；45 °C 种子1 = −0.0120）、"
        "种子间差异达 5 倍、随温度非单调。", 15, INK, True, 6, first=True)
put(tf, "原因：集体电荷位移是单一集体变量，不像自扩散那样能对 1085 个分子做统计平均。"
        "要拿到可用值需把生产段延长到 ~100 ns 并增加到 5–10 个独立副本。"
        "因此本次所有电导率讨论只使用 σ_NE。", 14, INK2, False, 0)
n += 1; page_no(s, n)

# ============ 局限 2 ============
s, y = new("边界二　绝对值不可直接对标实验",
           "全电荷非极化力场的典型指纹：密度对、输运错")
hdr = ["量（25 °C）", "本次 MD", "同类电解液实验量级", "偏差"]
rows = [["密度 (g/cm³)", f"{rho[1]:.3f}", "~1.20 – 1.21", "基本吻合"],
        ["D(Li⁺) (m²/s)", f"{DLi[1]:.2e}", "~2 – 3 × 10⁻¹⁰", "低约一个数量级"],
        ["σ (S/m)", f"{sNE[1]:.2f}（σ_NE，上限）", "~0.8 – 1.0", "低 4 – 5 倍"],
        ["t(Li⁺)", f"{tLi[1]:.2f}", "~0.3 – 0.4", "偏高"]]
cw = [In(3.0), In(3.3), In(3.3), In(2.3)]
tbl = s.shapes.add_table(5, 4, M, y + In(0.2), sum(cw, In(0)), In(2.4)).table
for j, w_ in enumerate(cw):
    tbl.columns[j].width = w_
tbl.rows[0].height = In(0.5)
for j, t in enumerate(hdr):
    c = tbl.cell(0, j); c.text = ""
    c.fill.solid(); c.fill.fore_color.rgb = C(0xF4,0xF4,0xF1)
    c.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = c.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER if j else PP_ALIGN.LEFT
    r = p.add_run(); r.text = t
    r.font.size, r.font.bold, r.font.color.rgb = Pt(13), True, INK2
    r.font.name = LAT_FONT; set_ea(r)
for i, row in enumerate(rows, start=1):
    tbl.rows[i].height = In(0.47)
    for j, t in enumerate(row):
        c = tbl.cell(i, j); c.text = ""
        c.fill.solid(); c.fill.fore_color.rgb = SURF if i % 2 else C(0xF9,0xF9,0xF7)
        c.vertical_anchor = MSO_ANCHOR.MIDDLE
        p = c.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER if j else PP_ALIGN.LEFT
        r = p.add_run(); r.text = t
        r.font.size = Pt(13.5)
        r.font.color.rgb = (GOOD if i == 1 else CRIT) if j == 3 else INK
        r.font.bold = (j == 3)
        r.font.name = LAT_FONT; set_ea(r)
tf = tb(s, M, y + In(2.85), W - 2*M, In(1.4))
put(tf, "范德华与体积性质标定得不错，但过强的静电把离子锁在了缔合态。",
    15, INK, True, 9, first=True)
put(tf, "✔　可用：温度趋势、活化能、相对倍数、不同组分之间的相对快慢", 15, GOOD, True, 5)
put(tf, "✘　不可直接用：D 与 σ 的绝对值。对标实验需先引入电荷缩放（约 0.7–0.8×）"
        "或改用极化力场，并重新验证", 15, CRIT, True, 0)
n += 1; page_no(s, n)

# ============ 其他局限 ============
s, y = new("其他需要说明的限制")
lims = [("采样长度", "生产段 20 ns、每温度 2 个种子，属筛选级精度。0 °C 的 MSD 双对数斜率 β 仅 0.89"
                     "（60 °C 为 0.97），低温尚未完全进入扩散区，该点 D 略有高估、活化能略有低估。"),
        ("Li⁺ 模型迁移", "Li⁺ 参数取自针对 TIP3P 水标定的 Joung–Cheatham 模型，"
                        "迁移到碳酸酯体系未经本项目验证。"),
        ("体积选取", "生产段体积取 NPT 最后一帧而非统计平均体积，种子间密度散布 0.2–1.6%，"
                    "会同比例影响浓度与电导。"),
        ("有限尺寸效应", "1085 个分子单盒未做 Yeh–Hummer 修正，会使 D 系统性偏低。"
                        "注意这与前页的低估同向叠加，不能互相抵消。"),
        ("未计算的量", "黏度 —— OpenMM 默认 reporter 不输出完整压力张量，Green–Kubo 积分缺少输入数据。")]
for i, (k, v) in enumerate(lims):
    yy = y + In(0.22) + i * In(0.92)
    rect(s, M, yy + In(0.14), Emu(28575), In(0.62), fill=AXIS, shape=MSO_SHAPE.RECTANGLE)
    tf = tb(s, M + In(0.28), yy + In(0.10), In(2.2), In(0.4))
    put(tf, k, 15, INK, True, 0, first=True)
    tf = tb(s, M + In(2.6), yy + In(0.08), W - 2*M - In(2.8), In(0.8))
    put(tf, v, 13.5, INK2, False, 0, line=1.3)
n += 1; page_no(s, n)

# ============ 结论与下一步 ============
s, y = new("结论与下一步")
tf = tb(s, M, y + In(0.2), W - 2*M, In(1.5))
put(tf, "结论", 19, INK, True, 9, first=True)
put(tf, "· 工作流跑通，8 次模拟全部成功，单卡 ~460 ns/day，4 温度 × 2 种子一轮约 1 小时", 15, INK2, False, 5)
put(tf, "· 温度趋势清晰可信：输运服从 Arrhenius，升温同时加快迁移与加剧缔合，两者部分抵消", 15, INK2, False, 5)
put(tf, "· 绝对值受力场限制偏低，当前结果适合做配方间的相对比较，不适合直接对标实验数值", 15, INK2, False, 0)
tf = tb(s, M, y + In(2.0), W - 2*M, In(0.5))
put(tf, "下一步（按优先级）", 19, INK, True, 0, first=True)
nxt = [("1", "电荷缩放对照组", "用 0.7–0.8× 缩放电荷重跑同一组温度，检验绝对值能否对上实验。"
                              "直指当前最大偏差，成本与本轮相同。", S1),
       ("2", "延长采样补 σ_CE", "生产段延长到 ~100 ns、增加到 5–10 个副本。单卡 468 ns/day，"
                              "100 ns 约 5 小时，8 卡可并行。", S2),
       ("3", "扩展配方矩阵", "改变 EC/EMC 比例、VC/FEC 浓度，或换锂盐（LiTFSI / LiFSI）。", S3)]
bw3 = (W - 2*M - In(0.44)) / 3
for i, (num, t1, t2, col) in enumerate(nxt):
    x = M + i * (bw3 + In(0.22))
    rect(s, x, y + In(2.62), bw3, In(1.75), fill=C(0xF4,0xF4,0xF1), line=GRID)
    rect(s, x, y + In(2.62), bw3, Emu(38100), fill=col, shape=MSO_SHAPE.RECTANGLE)
    tf = tb(s, x + In(0.26), y + In(2.86), bw3 - In(0.52), In(1.4))
    put(tf, f"{num}　{t1}", 15, INK, True, 7, first=True)
    put(tf, t2, 12.5, INK2, False, 0, line=1.3)
n += 1; page_no(s, n)

# ============ 封底 ============
s = prs.slides.add_slide(BLANK); bg(s)
rect(s, 0, 0, Emu(int(In(0.16))), H, fill=S1, shape=MSO_SHAPE.RECTANGLE)
tf = tb(s, In(1.15), In(2.68), W - In(2.3), In(2.3))
put(tf, "谢谢", 40, INK, True, 16, first=True)
put(tf, "交互式报告　temperature_report.html　（含完整数据表与逐种子原始值）", 15, INK2, False, 5)
put(tf, "流程说明　workflow_diagram.html　·　数据　temperature_results.csv", 15, INK2, False, 5)
put(tf, "代码与配方　github.com/lithium-beginner/auto-MD_electrolyte", 15, MUTED, False, 0)

out = "电解液温度依赖性研究_汇报.pptx"
prs.save(out)
print(f"已生成 {out}，共 {len(prs.slides.__iter__.__self__._sldIdLst)} 页")
