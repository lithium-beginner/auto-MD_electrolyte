#!/usr/bin/env python3
"""生成 PPT 用图表。配色沿用 temperature_report.html 中已通过校验器的那套。"""
import json, pathlib
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# ---- 字体 ----
# Noto Sans SC 覆盖拉丁+希腊+中文，但缺 U+207A/207B/2086/2090（上标正负号、下标 6/a）。
# 因此化学式与带上下标的单位一律走 mathtext（\mathrm，由 DejaVu 数学字体渲染），
# 中文与普通文字走 Noto。² ³ ° ≥ × ← 这些 Noto 有，可直接用。
FONTDIR = "/home/gaoxt/.local/share/fonts"
for f in ("NotoSansSC-Regular.otf", "NotoSansSC-Bold.otf"):
    font_manager.fontManager.addfont(f"{FONTDIR}/{f}")
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Noto Sans SC"]
plt.rcParams["mathtext.fontset"] = "dejavusans"
plt.rcParams["axes.unicode_minus"] = False

LI = r"$\mathrm{Li^+}$"
PF6 = r"$\mathrm{PF_6^-}$"
INVK = r"$\mathrm{K^{-1}}$"
EA = r"$E_\mathrm{a}$"

# ---- 已验证调色板（light 模式）----
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
ORD = ["#86b6ef", "#2a78d6", "#104281"]          # 序数三阶，--ordinal 校验通过
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURF = "#e1e0d9", "#c3c2b7", "#fcfcfb"

OUT = pathlib.Path("ppt_assets"); OUT.mkdir(exist_ok=True)
RAW = json.load(open("viz_data.json"))
T = RAW["temps"]; TC = [t["T_C"] for t in T]; TK = np.array([t["T_K"] for t in T])

mean = lambda a: sum(a) / len(a)
half = lambda a: (max(a) - min(a)) / 2 if len(a) > 1 else 0.0
agg = lambda f: ([mean([f(s) for s in t["seeds"]]) for t in T],
                 [half([f(s) for s in t["seeds"]]) for t in T])

rho, rho_e = agg(lambda s: s["rho"])
sNE, sNE_e = agg(lambda s: s["sNE"])
D = {k: agg(lambda s, k=k: s["D"][k]["D"]) for k in ("Li", "PF6", "EC", "EMC")}
SH = {k: agg(lambda s, k=k: s["shell"].get(k, 0.0))[0] for k in ("EC", "EMC", "PF6")}
SH["VCFEC"] = [mean([(s["shell"].get("VC", 0) + s["shell"].get("FEC", 0))
                     for s in t["seeds"]]) for t in T]
PR = {k: agg(lambda s, k=k: s["pair"][k])[0]
      for k in ("0_anions", "1_anion", "2plus_anions")}


def style(ax, xlab, ylab, grid_axis="y"):
    ax.set_facecolor(SURF)
    ax.figure.patch.set_facecolor(SURF)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(AXIS); ax.spines[sp].set_linewidth(1)
    ax.grid(axis=grid_axis, color=GRID, linewidth=1, linestyle="-", zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, labelsize=15, length=0)
    ax.set_xlabel(xlab, color=INK2, fontsize=16, labelpad=9)
    ax.set_ylabel(ylab, color=INK2, fontsize=16, labelpad=9)


def save(fig, name):
    fig.savefig(OUT / name, dpi=200, bbox_inches="tight", facecolor=SURF)
    plt.close(fig); print("  ", name)


def line(ax, x, y, e, color, label=None):
    """2px 线 + >=8px 标记带 2px surface ring；误差杠用系列色半透明。"""
    if e and any(e):
        ax.errorbar(x, y, yerr=e, fmt="none", ecolor=color, elinewidth=1.6,
                    capsize=4, capthick=1.6, alpha=.55, zorder=2)
    ax.plot(x, y, "-", color=color, linewidth=2, solid_capstyle="round",
            solid_joinstyle="round", zorder=3, label=label)
    ax.plot(x, y, "o", color=color, markersize=9, markeredgewidth=2.4,
            markeredgecolor=SURF, zorder=4)


def legend(ax, **kw):
    kw.setdefault("fontsize", 15)
    lg = ax.legend(frameon=False, **kw)
    for t in lg.get_texts():
        t.set_color(INK2)


print("生成图表:")

# 1 密度
fig, ax = plt.subplots(figsize=(7.4, 4.5))
line(ax, TC, rho, rho_e, S1)
style(ax, "温度 (°C)", "密度 (g/cm³)")
ax.set_xticks(TC); ax.set_ylim(1.14, 1.26)
save(fig, "01_density.png")

# 2 Arrhenius
fig, ax = plt.subplots(figsize=(9.6, 5.3))
inv = 1000 / TK
for k, nm, c in (("Li", LI, S1), ("PF6", PF6, S2), ("EC", "EC", S3), ("EMC", "EMC", S4)):
    line(ax, inv, D[k][0], None, c, nm)
ax.set_yscale("log")
style(ax, f"1000 / T  ({INVK})      ← 向左为升温", "自扩散系数 D (m²/s)")
ax.set_xticks(inv); ax.set_xticklabels([f"{v:.2f}\n{t}°C" for v, t in zip(inv, TC)])
legend(ax, loc="upper right", ncol=4, columnspacing=1.4, handlelength=1.6)
save(fig, "02_arrhenius.png")

# 3 电导率
fig, ax = plt.subplots(figsize=(7.4, 4.5))
line(ax, TC, sNE, sNE_e, S1)
style(ax, "温度 (°C)", "σ_NE  (S/m)")
ax.set_xticks(TC); ax.set_ylim(0, 0.6)
save(fig, "03_sigma.png")

# 4 活化能（名义类别 -> 全部同一 slot-1 色）
fig, ax = plt.subplots(figsize=(7.8, 4.3))
items = [(f"D({LI})", "D_Li"), ("D(EC)", "D_EC"), ("D(EMC)", "D_EMC"),
         (f"D({PF6})", "D_PF6"), ("σ_NE", "sNE")]
names = [n for n, _ in items]; vals = [RAW["arrhenius"][k]["Ea"] for _, k in items]
ypos = np.arange(len(names))[::-1]
ax.barh(ypos, vals, height=.5, color=S1, zorder=3)
for y, v in zip(ypos, vals):
    ax.text(v + .5, y, f"{v:.1f}", va="center", ha="left",
            color=INK2, fontsize=15, fontweight="bold")
ax.set_yticks(ypos); ax.set_yticklabels(names)
style(ax, f"活化能 {EA} (kJ/mol)", "", grid_axis="x")
ax.set_xlim(0, 33)
save(fig, "04_ea.png")

# 5 壳层组成（堆叠柱，2px surface 间隙靠 edgecolor 实现）
fig, ax = plt.subplots(figsize=(7.6, 4.8))
xs = np.arange(len(TC)); bottom = np.zeros(len(TC))
for k, nm, c in (("EC", "EC", S1), ("EMC", "EMC", S2),
                 ("VCFEC", "VC + FEC", S3), ("PF6", PF6, S4)):
    v = np.array(SH[k])
    ax.bar(xs, v, bottom=bottom, width=.5, color=c, label=nm,
           edgecolor=SURF, linewidth=2, zorder=3)
    for x, b, q in zip(xs, bottom, v):
        if q >= .35:                      # 只在放得下时标注，避免裁切
            ax.text(x, b + q / 2, f"{q:.2f}", ha="center", va="center",
                    fontsize=13, color="#fff" if k != "PF6" else INK, fontweight="bold")
    bottom += v
ax.set_xticks(xs); ax.set_xticklabels([f"{t}°C" for t in TC])
style(ax, "温度 (°C)", "第一壳层分子数")
ax.set_ylim(0, 4.6)
legend(ax, loc="upper center", bbox_to_anchor=(.5, 1.16), ncol=4,
       columnspacing=1.5, handlelength=1.3, fontsize=14)
save(fig, "05_shell.png")

# 6 离子缔合（有序类别 -> 单色阶）
fig, ax = plt.subplots(figsize=(7.6, 4.8))
bottom = np.zeros(len(TC))
for k, nm, c in (("0_anions", "0 个阴离子（“自由”）", ORD[0]),
                 ("1_anion", "1 个阴离子", ORD[1]),
                 ("2plus_anions", "≥2 个阴离子", ORD[2])):
    v = np.array(PR[k])
    ax.bar(xs, v, bottom=bottom, width=.5, color=c, label=nm,
           edgecolor=SURF, linewidth=2, zorder=3)
    for x, b, q in zip(xs, bottom, v):
        if q >= 7:
            ax.text(x, b + q / 2, f"{q:.0f}%", ha="center", va="center", fontsize=13,
                    color=INK if k == "0_anions" else "#fff", fontweight="bold")
    bottom += v
ax.set_xticks(xs); ax.set_xticklabels([f"{t}°C" for t in TC])
style(ax, "温度 (°C)", "占比 (%)")
ax.set_ylim(0, 100)
legend(ax, loc="upper center", bbox_to_anchor=(.5, 1.16), ncol=3,
       columnspacing=1.5, handlelength=1.3, fontsize=14)
save(fig, "06_pairing.png")

# 7 sigma_CE 诊断（点图，含零线，展示未收敛）
fig, ax = plt.subplots(figsize=(9.0, 4.2))
ax.axhline(0, color=AXIS, linewidth=1, zorder=2)
for i, (c, nm) in enumerate(((S1, "种子 1"), (S2, "种子 2"))):
    y = [t["seeds"][i]["sCE"] for t in T]
    ax.plot(TC, y, "o", color=c, markersize=11, markeredgewidth=2.4,
            markeredgecolor=SURF, label=nm, zorder=4)
style(ax, "温度 (°C)", "σ_CE  (S/m)")
ax.set_xticks(TC)
legend(ax, loc="upper left", handlelength=0)
ax.text(.985, .06, "收敛的话两个种子应重合并单调上升", transform=ax.transAxes,
        ha="right", fontsize=14, color="#d03b3b", fontweight="bold")
save(fig, "07_sigma_ce.png")

print("完成，共 7 张 ->", OUT)
