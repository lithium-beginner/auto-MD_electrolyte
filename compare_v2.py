#!/usr/bin/env python3
"""
温度对比汇总：读取 runs_v2/*/results/summary.json，按温度聚合多个独立种子，
做 Arrhenius 拟合并输出 CSV + Markdown 报告。

所有键名对照 analyze.py 的实际输出结构（analyze.py:113-137）：
  diffusion[SID] = {aliases, D_m2_s, fit_r2}
  conductivity   = {NE_S_m, collective_S_m, collective_fit_r2, collective_to_NE}
  thermodynamics['Density (g/mL)'] = {mean, std, first_half_mean, second_half_mean}
  coordination_number_distribution = {"n": fraction}
  solvation_composition_fractions  = {"S00:1+S01:2": fraction}
  local_anion_contact_fractions    = {0_anions|1_anion|2plus_anions: fraction}
"""
import json, re, sys
from collections import defaultdict
from pathlib import Path
import numpy as np

R_GAS = 8.314462618  # J/(mol K)
RUNS = Path("runs_v2")
TEMPS = [(0, 273.15), (25, 298.15), (45, 318.15), (60, 333.15)]
SEEDS = ["s1", "s2"]


def load(run):
    f = RUNS / run / "results" / "summary.json"
    if not f.exists():
        return None
    s = json.loads(f.read_text())
    m = json.loads((RUNS / run / "manifest.json").read_text())
    s["_alias"] = {sp["id"]: sp["aliases"][0] for sp in m["species"]}
    s["_count"] = {sp["id"]: sp["count"] for sp in m["species"]}
    return s


def mean_coord(s):
    d = s["coordination_number_distribution"]
    return sum(int(k) * v for k, v in d.items())


def shell_composition(s):
    """把 'S00:1+S05:1' 这类标签按物种分解，返回每个物种在 Li+ 第一壳层的平均分子数。"""
    out = defaultdict(float)
    for label, frac in s["solvation_composition_fractions"].items():
        if label == "empty":
            continue
        for part in label.split("+"):
            sid, n = part.split(":")
            out[s["_alias"].get(sid, sid)] += int(n) * frac
    return dict(out)


def diff_by_alias(s):
    return {v["aliases"][0]: (v["D_m2_s"], v["fit_r2"]) for v in s["diffusion"].values()}


def arrhenius(TK, Y):
    """ln Y = ln A - Ea/(R T);  返回 Ea(kJ/mol), R^2"""
    TK, Y = np.asarray(TK, float), np.asarray(Y, float)
    ok = np.isfinite(Y) & (Y > 0)
    if ok.sum() < 3:
        return None, None
    x, y = 1.0 / TK[ok], np.log(Y[ok])
    sl, ic = np.polyfit(x, y, 1)
    r2 = 1 - np.sum((y - (sl * x + ic)) ** 2) / np.sum((y - y.mean()) ** 2)
    return -sl * R_GAS / 1000.0, r2


def agg(vals):
    """多种子聚合 -> (均值, 半极差)"""
    v = [x for x in vals if x is not None and np.isfinite(x)]
    if not v:
        return np.nan, np.nan
    return float(np.mean(v)), (float((max(v) - min(v)) / 2) if len(v) > 1 else 0.0)


def main():
    data, missing = {}, []
    for tc, tk in TEMPS:
        per_seed = []
        for sd in SEEDS:
            run = f"T{tc:02d}C_{sd}"
            s = load(run)
            (per_seed.append(s) if s else missing.append(run))
        if per_seed:
            data[tc] = {"TK": tk, "runs": per_seed}

    if missing:
        print(f"[警告] 缺少结果: {', '.join(missing)}", file=sys.stderr)
    if not data:
        sys.exit("没有任何可用结果")

    species = ["Li", "PF6", "EC", "EMC", "VC", "FEC"]

    def alias_norm(a):
        if "cation" in a: return "Li"
        if "anion" in a:  return "PF6"
        return a

    rows = []
    for tc, blk in sorted(data.items()):
        runs, n = blk["runs"], len(blk["runs"])
        r = {"T_C": tc, "T_K": blk["TK"], "n_seeds": n}
        r["rho"], r["rho_e"] = agg([x["thermodynamics"]["Density (g/mL)"]["mean"] for x in runs])
        # 平衡诊断：生产段前后半密度差
        r["rho_drift"] = agg([abs(x["thermodynamics"]["Density (g/mL)"]["second_half_mean"]
                                  - x["thermodynamics"]["Density (g/mL)"]["first_half_mean"]) for x in runs])[0]
        r["Tmean"] = agg([x["thermodynamics"]["Temperature (K)"]["mean"] for x in runs])[0]
        r["conc"] = agg([list(x["realized_salt_concentration_mol_L"].values())[0] for x in runs])[0]

        for sp in species:
            ds, r2s = [], []
            for x in runs:
                for al, (d, r2) in diff_by_alias(x).items():
                    if alias_norm(al) == sp:
                        ds.append(d); r2s.append(r2)
            r[f"D_{sp}"], r[f"D_{sp}_e"] = agg(ds)
            r[f"D_{sp}_r2"] = agg(r2s)[0]

        r["sNE"], r["sNE_e"] = agg([x["conductivity"]["NE_S_m"] for x in runs])
        r["sCE"], r["sCE_e"] = agg([x["conductivity"]["collective_S_m"] for x in runs])
        r["sCE_r2"] = agg([x["conductivity"]["collective_fit_r2"] for x in runs])[0]
        r["sCE_each"] = [x["conductivity"]["collective_S_m"] for x in runs]
        r["sCE_r2_each"] = [x["conductivity"]["collective_fit_r2"] for x in runs]
        r["vol"] = agg([x["volume_nm3"] for x in runs])[0]
        r["CN"], r["CN_e"] = agg([mean_coord(x) for x in runs])

        comp = defaultdict(list)
        for x in runs:
            for k, v in shell_composition(x).items():
                comp[alias_norm(k)].append(v)
        for sp in species:
            if sp != "Li":
                r[f"shell_{sp}"] = agg(comp.get(sp, []))[0]

        for key, lab in [("0_anions", "SSIP"), ("1_anion", "CIP"), ("2plus_anions", "AGG")]:
            r[lab] = agg([x["local_anion_contact_fractions"].get(key, 0.0) * 100 for x in runs])[0]

        # Nernst-Einstein 理想迁移数（忽略离子关联）
        r["t_Li"] = r["D_Li"] / (r["D_Li"] + r["D_PF6"]) if np.isfinite(r["D_Li"]) and np.isfinite(r["D_PF6"]) else np.nan
        rows.append(r)

    TK = [r["T_K"] for r in rows]
    ea = {}
    for name, key in [("D_Li", "D_Li"), ("D_PF6", "D_PF6"), ("D_EC", "D_EC"), ("D_EMC", "D_EMC"),
                      ("sigma_NE", "sNE")]:
        ea[name] = arrhenius(TK, [r[key] for r in rows])

    # ---------- CSV ----------
    import csv as _csv
    cols = list(rows[0].keys())
    with open("temperature_results.csv", "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in r.items()})

    # ---------- Markdown ----------
    L = []
    A = L.append
    A("# 1 M LiPF6 / EC:EMC 3:7 + 2% VC + 1.2% FEC —— 温度依赖性 MD 研究\n")
    A("## 1. 体系与方法\n")
    A("| 项目 | 设置 |")
    A("|---|---|")
    A("| 组成(质量分数) | EC 25.29% / EMC 59.01% / VC 2.00% / FEC 1.20% / LiPF6 12.50% |")
    A("| 分子数 | EC 296, EMC 584, VC 24, FEC 11, Li⁺ 85, PF6⁻ 85（共 1085 个分子，**12702 个原子**）|")
    A(f"| 标称盐浓度 | 初始盒 1.0038 mol/L（NPT 松弛后各温度实测值见 2.1）|")
    A("| 力场 | GAFF2/AM1-BCC（参数库 gaff2-am1bcc-fullcharge-v1）；Li⁺ 为 Joung–Cheatham TIP3P 模型 |")
    A("| 初始盒 | 5.2³ nm³，初始密度 1.2164 g/cm³ |")
    A("| 流程 | 能量最小化 → NVT 200 ps → NPT 2 ns → 固定末态体积 NVT 生产 20 ns |")
    A("| 积分 | LangevinMiddle，1 fs，摩擦 1 /ps，PME，氢键约束，截断 1.0 nm |")
    A("| 采样 | 帧间隔 10 ps（2000 帧）；每温度 2 个独立种子（不同 Packmol 装箱 + 不同初速度）|")
    A(f"| 温度点 | {', '.join(str(r['T_C'])+'°C' for r in rows)} |")
    A("\n表中 `±` 为 2 个独立种子的半极差，仅反映种子间散布，不是严格置信区间。\n")

    A("## 2. 主要结果\n")
    A("### 2.1 密度\n")
    A("| T (°C) | 实测温度 (K) | 密度 (g/cm³) | 盒体积 (nm³) | NPT 后 [Li⁺] (mol/L) |")
    A("|---:|---:|---:|---:|---:|")
    for r in rows:
        A(f"| {r['T_C']} | {r['Tmean']:.2f} | {r['rho']:.4f} ± {r['rho_e']:.4f} | {r['vol']:.2f} | {r['conc']:.4f} |")
    if len(rows) >= 2:
        k = np.polyfit([r["T_C"] for r in rows], [r["rho"] for r in rows], 1)[0]
        A(f"\n密度温度系数 **{k:.5f} g·cm⁻³·°C⁻¹**；"
          f"0→60°C 相对变化 {(rows[-1]['rho']-rows[0]['rho'])/rows[0]['rho']*100:+.2f}%。")
    A("\n生产段是**定容 NVT**，密度在生产段内恒定，因此没有\"前后半漂移\"可言；"
      "密度的真实不确定度来自 `run_md.py` 取 NPT **最后一帧**体积（而非统计平均体积），"
      "表现为上表的种子间散布 0.2–1.6%（45°C 最大）。这一噪声会同比例传递到浓度和电导率。")

    A("\n### 2.2 自扩散系数 (m²/s)\n")
    A("| T (°C) | D(Li⁺) | D(PF6⁻) | D(EC) | D(EMC) | 拟合 R²(Li) |")
    A("|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        A(f"| {r['T_C']} | {r['D_Li']:.3e} ± {r['D_Li_e']:.1e} | {r['D_PF6']:.3e} ± {r['D_PF6_e']:.1e} "
          f"| {r['D_EC']:.3e} | {r['D_EMC']:.3e} | {r['D_Li_r2']:.3f} |")

    A("\n### 2.3 离子电导率 (S/m)\n")
    A("| T (°C) | σ(Nernst–Einstein) | σ(集体 Einstein) | R²(集体拟合) |")
    A("|---:|---:|---:|---:|")
    for r in rows:
        A(f"| {r['T_C']} | {r['sNE']:.4f} ± {r['sNE_e']:.4f} | {r['sCE']:.4f} ± {r['sCE_e']:.4f} | {r['sCE_r2']:.3f} |")
    A("\n> **集体 Einstein 电导率在本采样长度下未收敛，不能作为结果使用。** 逐种子原始值：")
    A("> ")
    A("> | T (°C) | 种子1 σ_CE | R² | 种子2 σ_CE | R² |")
    A("> |---:|---:|---:|---:|---:|")
    for r in rows:
        a, b = r["sCE_each"], r["sCE_r2_each"]
        A(f"> | {r['T_C']} | {a[0]:.4f} | {b[0]:.3f} | {a[1]:.4f} | {b[1]:.3f} |")
    A("> ")
    A("> 出现了负值（0°C 种子2、45°C 种子1）和 R²=0.065 的无意义拟合，种子间最大差异达 5 倍，"
      "且随温度非单调。原因是集体电荷位移是**单一集体变量**，不像自扩散那样能对 1085 个分子做统计平均，"
      "收敛通常需要上百 ns 或多达十几个独立副本。")
    A("\n因此下文的电导率讨论**只使用 σ_NE**。注意 σ_NE 按定义忽略离子间关联运动，"
      "是**上限**估计；真实电导率低于它，低多少取决于离子缔合程度（本体系缔合很强，见 2.5）。")

    A("\n### 2.4 Li⁺ 溶剂化结构\n")
    A("| T (°C) | 配位数(供体原子) | 壳层 EC | 壳层 EMC | 壳层 VC | 壳层 FEC | 壳层 PF6⁻ |")
    A("|---:|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        A(f"| {r['T_C']} | {r['CN']:.2f} ± {r['CN_e']:.2f} | {r.get('shell_EC',float('nan')):.2f} "
          f"| {r.get('shell_EMC',float('nan')):.2f} | {r.get('shell_VC',float('nan')):.2f} "
          f"| {r.get('shell_FEC',float('nan')):.2f} | {r.get('shell_PF6',float('nan')):.2f} |")
    A("\n注意：配位数列统计的是 3.2 Å 内的**供体原子**数（选区为 O 或 F），因此同时包含溶剂 O、FEC 的 F 和 PF6⁻ 的 F；"
      "后面几列按分子种类分解，才是干净的壳层组成（单位：个分子）。")

    A("\n### 2.5 离子缔合（按壳层内阴离子分子数分类）\n")
    A("| T (°C) | 0 个阴离子 (%) | 1 个 (%) | ≥2 个 (%) |")
    A("|---:|---:|---:|---:|")
    for r in rows:
        A(f"| {r['T_C']} | {r['SSIP']:.1f} | {r['CIP']:.1f} | {r['AGG']:.1f} |")
    A("\n这是基于截断半径的局部接触计数，**不等同**于严格的 SSIP/CIP/AGG 团簇识别（analyze.py 自身也声明了这一点）。")

    A("\n### 2.6 Nernst–Einstein 理想迁移数\n")
    A("| T (°C) | t(Li⁺) = D_Li/(D_Li+D_PF6) |")
    A("|---:|---:|")
    for r in rows:
        A(f"| {r['T_C']} | {r['t_Li']:.3f} |")
    A("\n该定义忽略离子间关联，是上限估计，通常高于实验电化学迁移数。")

    A("\n## 3. Arrhenius 温度依赖性\n")
    A("| 量 | 活化能 Ea (kJ/mol) | 拟合 R² | 0→60°C 倍数 |")
    A("|---|---:|---:|---:|")
    for name, row_key, ea_key in [("D(Li⁺)", "D_Li", "D_Li"), ("D(PF6⁻)", "D_PF6", "D_PF6"),
                                  ("D(EC)", "D_EC", "D_EC"), ("D(EMC)", "D_EMC", "D_EMC"),
                                  ("σ_NE", "sNE", "sigma_NE")]:
        e, r2 = ea[ea_key]
        lo, hi = rows[0][row_key], rows[-1][row_key]
        ratio = f"{hi/lo:.2f}×" if (np.isfinite(lo) and np.isfinite(hi) and lo > 0) else "—"
        ea_s = f"{e:.2f}" if e is not None else "—"
        r2_s = f"{r2:.4f}" if r2 is not None else "—"
        A(f"| {name} | {ea_s} | {r2_s} | {ratio} |")

    A("\n## 4. 规律总结\n")
    A("**4.1 单调且可信的趋势**\n")
    A(f"1. **密度随温度线性下降**，温度系数 {np.polyfit([r['T_C'] for r in rows],[r['rho'] for r in rows],1)[0]:.5f} g·cm⁻³·°C⁻¹，"
      f"0→60°C 下降 {abs(rows[-1]['rho']-rows[0]['rho'])/rows[0]['rho']*100:.1f}%。这是纯热膨胀，与实验定性一致。")
    A(f"2. **输运性质严格服从 Arrhenius 关系**（R² ≥ 0.99）。D(Li⁺) 的活化能 {ea['D_Li'][0]:.1f} kJ/mol 略高于 "
      f"D(PF6⁻) 的 {ea['D_PF6'][0]:.1f} kJ/mol，说明 Li⁺ 迁移的能垒更高——它要拖着溶剂化壳层走。")
    A(f"3. **0→60°C 扩散提升约 {rows[-1]['D_Li']/rows[0]['D_Li']:.1f} 倍，σ_NE 提升约 {rows[-1]['sNE']/rows[0]['sNE']:.1f} 倍。**"
      " σ 的提升小于 D 的提升，因为升温同时加剧了离子缔合（见下），部分抵消了迁移率的增益。")
    A("\n**4.2 反直觉但自洽的趋势：升温促进离子缔合**\n")
    A("| T (°C) | 壳层 EC | 壳层 PF6⁻ | 自由 Li⁺ (%) |")
    A("|---:|---:|---:|---:|")
    for r in rows:
        A(f"| {r['T_C']} | {r.get('shell_EC',float('nan')):.2f} | {r.get('shell_PF6',float('nan')):.2f} | {r['SSIP']:.1f} |")
    A("\n升温过程中 Li⁺ 第一壳层的 EC 被 PF6⁻ 系统性置换（EC "
      f"{rows[0].get('shell_EC',0):.2f}→{rows[-1].get('shell_EC',0):.2f}，PF6⁻ "
      f"{rows[0].get('shell_PF6',0):.2f}→{rows[-1].get('shell_PF6',0):.2f}），"
      f"完全无阴离子接触的\"自由\"Li⁺ 从 {rows[0]['SSIP']:.1f}% 降到 {rows[-1]['SSIP']:.1f}%。")
    A("\n这与\"升温促进解离\"的直觉相反，但在本模型内是自洽的，有两个相互叠加的驱动力：")
    A("- **熵驱动缔合**：Li⁺–PF6⁻ 成对会把原先被束缚的 EC 释放到本体，体系平动熵增加。温度越高，熵项 −TΔS 权重越大，缔合态越有利。")
    A("- **密度降低减弱屏蔽**：升温使盒体积增大约 6%，介质屏蔽变弱，裸库仑吸引相对增强。")
    A("\n**需要强调：缔合的绝对程度几乎肯定被夸大了**（60°C 下仅 2.6% 自由 Li⁺ 不符合 1 M 碳酸酯电解液的实际解离状况），"
      "原因见 5.2。所以这里可取的是**趋势方向**，不是具体百分比。")
    A(f"\n**4.3 迁移数接近 0.5**：t(Li⁺) 在 {min(r['t_Li'] for r in rows):.2f}–{max(r['t_Li'] for r in rows):.2f} 之间，"
      "即 D(Li⁺) ≈ D(PF6⁻)。这是强缔合的直接证据——阳离子和阴离子作为近中性的离子对协同迁移。"
      "实验电化学迁移数通常为 0.3–0.4，本模型偏高也指向缔合过强。")

    A("\n## 5. 局限与注意事项\n")
    A("**5.1 已失效的量**\n")
    A("- **集体 Einstein 电导率 σ_CE：未收敛，已作废**（见 2.3）。要拿到可用的 σ_CE，需把生产段延长到 100 ns 量级"
      "并增加到 5–10 个独立副本。本次 20 ns × 2 副本远远不够。")
    A("- **黏度：未计算。** OpenMM 默认 reporter 不输出完整压力张量，Green–Kubo 积分缺少输入数据。")
    A("\n**5.2 系统性偏差：全电荷非极化力场低估 Li⁺ 输运**\n")
    A("本次用的是 `gaff2-am1bcc-fullcharge-v1`，即**未做电荷缩放**的非极化模型（项目 README 明确说明电荷缩放尚未实现）。"
      "这类模型对 Li⁺–羰基氧和 Li⁺–阴离子的静电吸引过强，典型后果是离子缔合过度、Li⁺ 迁移过慢。本次结果与此一致：")
    A("")
    A("| 量 (25°C) | 本次 MD | 商用同类电解液的实验量级 | 偏差 |")
    A("|---|---:|---:|---|")
    A(f"| 密度 (g/cm³) | {rows[1]['rho']:.3f} | ~1.20–1.21 | 基本吻合 |")
    A(f"| D(Li⁺) (m²/s) | {rows[1]['D_Li']:.2e} | ~2–3×10⁻¹⁰ | **低约一个数量级** |")
    A(f"| σ (S/m) | {rows[1]['sNE']:.2f} (σ_NE，上限) | ~0.8–1.0 | **低约 4–5 倍** |")
    A(f"| t(Li⁺) | {rows[1]['t_Li']:.2f} | ~0.3–0.4 | 偏高 |")
    A("")
    A("> 实验栏是 1 M LiPF6/碳酸酯体系公认的大致量级，用于判断偏差方向和幅度，**不是对某一篇特定测量的引用**。")
    A("")
    A("**密度对、输运错**这一组合是全电荷非极化模型的典型指纹：范德华和体积性质标定得不错，"
      "但过强的静电把离子锁在了缔合态。因此：")
    A("- ✅ **可用**：温度趋势、活化能、相对倍数、不同组分之间的相对快慢。")
    A("- ❌ **不可直接用**：D 和 σ 的绝对值。要对标实验需先引入电荷缩放（约 0.7–0.8×）或改用极化力场，并重新验证。")
    A("\n**5.3 其他**\n")
    A("1. **采样长度**：生产段 20 ns、每温度 2 个独立种子，属筛选级。自扩散拟合 R² 均 ≥ 0.998，"
      "但 MSD 双对数斜率 β 在 0°C 为 0.89、60°C 为 0.97，说明**低温体系尚未完全进入扩散区**，"
      "0°C 的 D 可能被略微高估，其活化能相应略有低估。")
    A("2. **Li⁺ 模型迁移**：Li⁺ 参数取自针对 TIP3P 水标定的 Joung–Cheatham 模型，迁移到碳酸酯体系未经本项目验证。")
    A("3. **体积选取**：生产段体积取 NPT 最后一帧而非平均体积，种子间密度散布 0.2–1.6%，会同比例影响浓度与电导。")
    A("4. **Langevin 恒温器**：摩擦 1/ps 会影响输运，未做摩擦依赖性检验。")
    A("5. **有限尺寸效应**：1085 个分子单盒未做 Yeh–Hummer 修正，会使 D 系统性偏低。"
      "注意这与 5.2 的低估**同向叠加**，不能用来互相抵消。")
    A("6. **配位数口径**：2.4 节的\"配位数\"数的是 3.2 Å 内供体原子数（选区 O 或 F），"
      "其随温度上升（8.03→8.99）主要来自 PF6⁻ 置换 EC 后贡献更多 F 原子，**不代表配位变强**；"
      "判断结构变化应看按分子分解的壳层组成。")
    A("7. **接触分类**：SSIP/CIP/AGG 列是基于截断半径的局部阴离子计数，非严格团簇识别（analyze.py 自身亦有声明）。")

    Path("TEMPERATURE_REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print("已生成 temperature_results.csv 和 TEMPERATURE_REPORT.md")
    print("\n".join(L[:0]) or "")
    for r in rows:
        print(f"  {r['T_C']:>3}°C  rho={r['rho']:.4f}  D_Li={r['D_Li']:.3e}  sNE={r['sNE']:.3f}  sCE={r['sCE']:.3f}  CN={r['CN']:.2f}")


if __name__ == "__main__":
    main()
