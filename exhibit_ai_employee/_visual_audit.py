# -*- coding: utf-8 -*-
"""像素级视觉体检：不走 DOM，直接读渲染出来的截图。

上一轮只量了 DOM 的取值（字号/颜色/间距）；这一轮量「实际画出来的像素」：
  - WCAG 对比度：每个文字色 × 每个底色，标出不合格的组合
  - 颜色分布：主色/强调色/墨色各占多少画面
  - 留白率、深色像素密度分区（找出过挤或过空的区域）
  - 结构灰度图：把截图降采样成字符画，用来看整体版面骨架

    python _visual_audit.py
"""
import io
import math
import os
import sys
from collections import Counter

from PIL import Image

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ui_shots")
VIEWS = ["project", "live", "content", "tests", "voice", "release", "feedback"]
RAMP = " .:-=+*#%@"

# 与 assets/tokens.css 保持一致
INK = {
    "ink-1": "#24364f", "ink-2": "#546a85", "ink-3": "#8296ad", "ink-4": "#aeb9c7",
    "ink-invert": "#eaf1ff",
}
SURFACE = {
    "surface-0": "#ffffff", "surface-1": "#f7f9fc", "surface-2": "#eef2f8",
    "surface-3": "#e3e9f2", "navy": "#132541", "accent": "#16815f",
    "accent-soft": "#eaf6f1", "danger-soft": "#fdf1f3", "warn-soft": "#fdf6e7",
    "info-soft": "#eef3fb",
}


def rgb(hexv):
    h = hexv.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def lum(c):
    def f(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (f(x) for x in c)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = lum(rgb(a)), lum(rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def classify(c):
    r, g, b = c
    mx, mn = max(c), min(c)
    if mx - mn < 18 and mx > 235:
        return "white"
    if r < 90 and g < 100 and b < 130:
        return "navy"
    if g > r + 22 and g > b + 8 and g > 90:
        return "accent"
    if r > 130 and g < 110 and b < 130:
        return "danger"
    if r > 140 and g > 110 and b < 90:
        return "warn"
    if b > r + 25 and b > 120:
        return "info"
    if mx < 150:
        return "ink"
    if mx - mn < 22:
        return "gray"
    return "other"


def structure_map(im, cols=96, rows=30):
    small = im.convert("L").resize((cols, rows), Image.BOX)
    out = []
    for y in range(rows):
        line = []
        for x in range(cols):
            v = small.getpixel((x, y))
            line.append(RAMP[min(9, int((255 - v) / 25.6))])
        out.append("".join(line))
    return out


def density(im, gx=6, gy=4):
    w, h = im.size
    im2 = im.convert("L").resize((gx * 8, gy * 8), Image.BOX)
    grid = []
    for j in range(gy):
        row = []
        for i in range(gx):
            vals = [im2.getpixel((i * 8 + a, j * 8 + b)) for a in range(8) for b in range(8)]
            row.append(round(sum(1 for v in vals if v < 160) / 64, 2))
        grid.append(row)
    return grid


def main():
    # 1. 对比度矩阵（不依赖截图，直接算 token 组合）
    print("=" * 78)
    print("WCAG 对比度（正文需 ≥4.5，大字/图形 ≥3.0）")
    pairs = [
        (k, s) for k in INK for s in ["surface-0", "surface-1", "surface-2"]
    ] + [
        ("ink-invert", "navy"), ("ink-invert", "accent"),
        ("ink-1", "accent-soft"), ("ink-1", "danger-soft"),
        ("ink-1", "warn-soft"), ("ink-1", "info-soft"),
    ]
    bad = []
    for k, s in pairs:
        c = contrast(INK[k], SURFACE[s])
        flag = "OK  " if c >= 4.5 else ("BIG " if c >= 3.0 else "FAIL")
        if c < 4.5:
            bad.append("%s/%s=%.2f" % (k, s, c))
        print("  %s %-10s / %-12s %5.2f" % (flag, k, s, c))
    print("  低于 4.5 的组合 %d 个: %s" % (len(bad), ", ".join(bad)))

    # 2. 逐屏像素分布
    for view in VIEWS:
        path = os.path.join(SHOTS, "vis-%s-view.png" % view)
        if not os.path.exists(path):
            print("缺截图", path)
            continue
        im = Image.open(path).convert("RGB")
        w, h = im.size
        q = im.resize((240, 150), Image.BOX)
        classes = Counter(classify(q.getpixel((x, y))) for y in range(150) for x in range(240))
        total = 240 * 150
        def pct(name):
            return round(classes.get(name, 0) * 100.0 / total, 1)
        print()
        print("=" * 78)
        print("%s  %dx%d  留白(白+浅灰)=%.1f%%  墨=%.1f%%  深底=%.1f%%  强调绿=%.1f%%" % (
            view.upper(), w, h, pct("white") + pct("gray"), pct("ink"),
            pct("navy"), pct("accent")))
        print("  密度分区（6x4，值=深色像素占比）:")
        for row in density(im):
            print("    " + "  ".join("%.2f" % v for v in row))
        print("  结构图（96x30，越黑字符越重）:")
        for line in structure_map(im):
            print("   |" + line + "|")


if __name__ == "__main__":
    main()
