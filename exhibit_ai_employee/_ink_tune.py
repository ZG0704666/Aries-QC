# -*- coding: utf-8 -*-
"""在保持色相的前提下，把墨色压到达标对比度：向深色锚点线性插值，取刚好达标的那一档。"""
import io
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def hx(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def lum(c):
    out = []
    for v in c:
        v = v / 255.0
        out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]


def cr(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


BG = {"surface-0": "#ffffff", "surface-1": "#f7f9fc", "surface-2": "#eef2f8"}
ANCHOR = hx("#16283f")  # 同色系深锚点，插值不会跑色

for name, original, target in [("ink-2", "#546a85", 6.5), ("ink-3", "#8296ad", 4.5), ("ink-4", "#aeb9c7", 3.0)]:
    o = hx(original)
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        c = tuple(round(o[i] + (ANCHOR[i] - o[i]) * mid) for i in range(3))
        if cr(c, hx(BG["surface-2"])) >= target:
            hi = mid
        else:
            lo = mid
    c = tuple(round(o[i] + (ANCHOR[i] - o[i]) * hi) for i in range(3))
    hexv = "#%02x%02x%02x" % c
    ratios = "  ".join("%s=%.2f" % (k, cr(c, hx(v))) for k, v in BG.items())
    print("%s  %s -> %s   %s   白底原值=%.2f" % (name, original, hexv, ratios, cr(o, hx("#ffffff"))))
