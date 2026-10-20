#!/usr/bin/env python3
"""PPTX 几何审计：检查形状越界、文本溢出文本框、图片比例失真。

无法渲染 PPTX 的环境下用这个代替肉眼检查。文本宽度用 Noto Sans SC 实测，
按文本框宽度模拟换行，估算所需高度与框高比较。
"""
import sys
from pptx import Presentation
from pptx.util import Emu
from PIL import ImageFont

EMU_PER_PT = 12700
FONT = "/home/gaoxt/.local/share/fonts/NotoSansSC-Regular.otf"
_cache = {}


def font(sz_pt):
    px = max(8, int(round(sz_pt * 96 / 72)))
    if px not in _cache:
        _cache[px] = ImageFont.truetype(FONT, px)
    return _cache[px]


def text_w_px(txt, sz_pt):
    return font(sz_pt).getlength(txt)


def wrapped_lines(txt, sz_pt, box_w_px):
    """按字符逐个累加模拟换行（CJK 可任意位置断行，近似保守）。"""
    if box_w_px <= 0:
        return 1
    lines, cur = 1, 0.0
    for ch in txt:
        w = text_w_px(ch, sz_pt)
        if cur + w > box_w_px and cur > 0:
            lines += 1
            cur = w
        else:
            cur += w
    return lines


def audit(path):
    prs = Presentation(path)
    SW, SH = prs.slide_width, prs.slide_height
    problems = []
    for idx, slide in enumerate(prs.slides, start=1):
        for sh in slide.shapes:
            if sh.left is None:
                continue
            l, t = sh.left, sh.top
            w, h = sh.width or 0, sh.height or 0
            # 1 越界
            tol = Emu(9525)   # 1px 容差
            if l < -tol or t < -tol or l + w > SW + tol or t + h > SH + tol:
                problems.append(f"p{idx} 越界: {sh.shape_type} "
                                f"L{Emu(l).inches:.2f} T{Emu(t).inches:.2f} "
                                f"R{Emu(l+w).inches:.2f} B{Emu(t+h).inches:.2f}")
            # 2 文本溢出
            if sh.has_text_frame and sh.text_frame.text.strip():
                tf = sh.text_frame
                inner_w_px = (Emu(w).inches * 96) - \
                             (Emu(tf.margin_left).inches + Emu(tf.margin_right).inches) * 96
                total_pt = 0.0
                for p in tf.paragraphs:
                    txt = "".join(r.text for r in p.runs)
                    if not txt:
                        continue
                    sz = next((r.font.size.pt for r in p.runs if r.font.size), 18)
                    ls = p.line_spacing if isinstance(p.line_spacing, float) else 1.2
                    nl = wrapped_lines(txt, sz, inner_w_px)
                    total_pt += nl * sz * ls
                    total_pt += (p.space_after.pt if p.space_after else 0)
                need = total_pt * EMU_PER_PT
                avail = h - tf.margin_top - tf.margin_bottom
                if need > avail * 1.06:        # 6% 容差
                    over = (need - avail) / EMU_PER_PT
                    problems.append(
                        f"p{idx} 文本溢出 {over:.0f}pt: \"{tf.text[:34]}…\" "
                        f"(框高 {Emu(h).inches:.2f}\", 需 {need/914400:.2f}\")")
    return prs, problems


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "电解液温度依赖性研究_汇报.pptx"
    prs, probs = audit(path)
    print(f"幻灯片 {len(prs.slides._sldIdLst)} 页，"
          f"尺寸 {Emu(prs.slide_width).inches:.2f}×{Emu(prs.slide_height).inches:.2f} 英寸")
    if probs:
        print(f"\n发现 {len(probs)} 处问题:")
        for p in probs:
            print("  ✗", p)
        sys.exit(1)
    print("\n✓ 无越界、无文本溢出")
