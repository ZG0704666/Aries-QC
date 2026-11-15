# -*- coding: utf-8 -*-
"""把散落的字面值收敛成一套设计 token（一次性的构建步骤，可重复运行）。

为什么要有这一步：实测七个视图一共用了 18 种字号、52 种文字色、26 种背景色、
32 种边框，其中大量是「差一点点」的近似值（#e3e9f1 / #e0e6ef / #dce4ed …）。
近似值成堆出现，是界面看起来杂乱的直接原因——眼睛分辨不出层级，只看到噪声。

做法：
1. 生成 assets/tokens.css（唯一取值来源，带中文注释）。
2. 把四个设计包样式表 + 接入层 studio.css 里的字面值替换成 var(--token, 原值)：
   颜色按 HSV 色相分组做最近邻（绿还是绿、红还是红），字号 / 圆角 / 间距按阶梯吸附。
3. 写回时保留 LF，避免整文件换行符变化。

跑完用 _census_style.py 复测：字号 ≤ 7 种、文字色 ≤ 10 种、背景 ≤ 10 种、边框 ≤ 6 种。
"""
import colorsys
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")

# 我们的 token 一律加 --ds- 前缀：设计包自己也有 --navy / --line / --ink 这类变量，
# 不加前缀会出现 --navy:var(--navy) 这种自引用，变量直接失效。
PREFIX = "--ds-"


def tk(name):
    return PREFIX + (name[2:] if name.startswith("--") else name)

# ---- token 表：名字 -> (十六进制, 用途) -------------------------------------
TOKENS = [
    # 墨色（文字）：四档都要能读。数值由 _ink_tune.py 在最差底色 surface-2 上反推，
    # 白底对比度依次为 12.24 / 7.31 / 5.08 / 3.38——次级与元信息都过 WCAG 4.5，
    # 最弱档 3.38 只给非正文的图形化文字（未激活步序号、装饰符号）。
    ("--ink-1", "#24364f", "正文"),
    ("--ink-2", "#435871", "次要文字"),
    ("--ink-3", "#5d7087", "元信息、占位"),
    ("--ink-4", "#808d9e", "最弱的一档：未激活步序号、装饰符号"),
    ("--ink-invert", "#eaf1ff", "深底上的文字"),
    # 装饰色：只给示意图渐变、流水线连线、轨道与滚动条、虚线投放框。
    # 它们故意很淡，达不到文字对比度是设计意图，所以绝不许用在 color 上——
    # 文字与装饰共用同一档灰，是「元信息淡到看不见」的根因。
    ("--deco-1", "#8296ad", "仅装饰：示意图渐变、连线、轨道，不作文字"),
    ("--deco-2", "#aeb9c7", "仅装饰：更淡的示意图与虚线框，不作文字"),
    # 线
    ("--line", "#e4e9f0", "常规分隔线、卡片描边"),
    ("--line-2", "#cfd8e4", "需要更明确的描边"),
    # 面
    ("--surface-0", "#ffffff", "卡片、纸张"),
    ("--surface-1", "#f7f9fc", "次级面、区块底"),
    ("--surface-2", "#eef2f8", "凹槽、表头、禁用面"),
    ("--surface-3", "#e3e9f2", "更重的面"),
    ("--navy", "#132541", "顶栏深底"),
    # 强调（绿）
    ("--accent", "#16815f", "主强调、主按钮"),
    ("--accent-deep", "#0f6b4f", "强调的按下/深文字"),
    ("--accent-soft", "#eaf6f1", "强调浅底"),
    ("--accent-line", "#b7dccd", "强调描边"),
    # 状态
    ("--danger", "#a8404f", "错误、阻断"),
    ("--danger-soft", "#fdf1f3", "错误浅底"),
    ("--danger-line", "#f0d2d8", "错误描边"),
    ("--warn", "#9a6b1d", "待确认、警告"),
    ("--warn-soft", "#fdf6e7", "警告浅底"),
    ("--warn-line", "#ecd9b4", "警告描边"),
    ("--info", "#2f5f9e", "进行中、信息"),
    ("--info-soft", "#eef3fb", "信息浅底"),
    ("--info-line", "#cddcf0", "信息描边"),
]

FONT_STEPS = [11, 13, 15, 18, 22, 28]
SPACE_STEPS = [0, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48]
RADIUS_STEPS = [0, 4, 6, 8, 10, 12, 16, 20]

FILES = ["styles.css", "refinement.css", "atelier.css", "workspace-tools.css", "studio.css"]

HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b")
RGB_RE = re.compile(r"rgba?\(\s*[0-9.]+\s*,\s*[0-9.]+\s*,\s*[0-9.]+\s*(?:,\s*[0-9.]+\s*)?\)")
NAMED = {"white": "#ffffff", "black": "#000000"}


def parse_color(text):
    """把 #rgb / #rrggbb / #rrggbbaa / rgb() / rgba() 解析成 (r,g,b,a)。"""
    t = text.strip().lower()
    if t in NAMED:
        return (*hex_to_rgb(NAMED[t]), 1.0)
    if t.startswith("#"):
        h = t[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        elif len(h) == 4:
            r = int(h[0] * 2, 16)
            g = int(h[1] * 2, 16)
            b = int(h[2] * 2, 16)
            return (r, g, b, int(h[3] * 2, 16) / 255.0)
        elif len(h) not in (6, 8):
            return None
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        a = int(h[6:8], 16) / 255.0 if len(h) == 8 else 1.0
        return (r, g, b, a)
    nums = re.findall(r"[0-9.]+", t)
    if not nums:
        return None
    r, g, b = (float(nums[0]), float(nums[1]), float(nums[2]))
    a = float(nums[3]) if len(nums) > 3 else 1.0
    return (r, g, b, a)


def hex_to_rgb(h):
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def hue_of(rgb):
    h, s, v = colorsys.rgb_to_hsv(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
    return h * 360.0, s, v


def nearest_token(color_text):
    """按「色相优先」找最近的 token：绿不会被吸到红，中性灰不会被吸到强调绿。"""
    c = parse_color(color_text)
    if c is None:
        return None
    h, s, v = hue_of(c)
    neutral = s < 0.10 or v < 0.06
    best = None
    best_score = 1e9
    for name, hex_value, _ in TOKENS:
        tr, tg, tb = hex_to_rgb(hex_value)
        th, ts, tv = hue_of((tr, tg, tb))
        tneutral = ts < 0.10 or tv < 0.06
        dr, dg, db = c[0] - tr, c[1] - tg, c[2] - tb
        dist = (dr * dr + dg * dg + db * db) ** 0.5
        # 中性 ↔ 有色：加惩罚，避免把灰吸成绿或反过来
        if neutral != tneutral:
            dist += 60
        else:
            dh = min(abs(h - th), 360 - abs(h - th))
            dist += dh * 0.8
            dist += abs(s - ts) * 90
        if dist < best_score:
            best_score = dist
            best = (name, hex_value)
    return best


def snap(value, steps):
    return min(steps, key=lambda s: (abs(s - value), s))


def replace_colors(value):
    def sub(m):
        parsed = parse_color(m.group(0))
        got = nearest_token(m.group(0))
        if not got:
            return m.group(0)
        name, _hex = got
        alpha = parsed[3] if parsed else 1.0
        # 不写回退值：tokens.css 是唯一取值来源。漏了它整页会明显坏掉，
        # 一眼就能发现，比「看着正常但颜色各自为政」安全。
        if alpha >= 0.95:
            return "var(%s)" % tk(name)
        # 半透明的边与影（如 #16345110、rgba(39,143,116,.18)）不能直接换成 token：
        # token 是不带 alpha 的实色，换过去会变成一坨重色。用 color-mix 保住透明度。
        percent = max(2, min(100, int(round(alpha * 100))))
        return "color-mix(in srgb, var(%s) %d%%, transparent)" % (tk(name), percent)

    value = HEX_RE.sub(sub, value)
    value = RGB_RE.sub(sub, value)
    return value


def snap_lengths(value, steps, use_var=False, var_prefix=None):
    def sub(m):
        num = float(m.group(1))
        picked = snap(num, steps)
        if use_var and picked in steps and picked > 0:
            return m.group(1).replace(m.group(1), "%spx" % (int(picked) if picked == int(picked) else picked))
        return "%spx" % (int(picked) if picked == int(picked) else picked)

    return re.sub(r"(-?\d+(?:\.\d+)?)px\b", sub, value)


SPACING_PROPS = {"padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
                 "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
                 "gap", "row-gap", "column-gap"}


def transform_decl(prop, value):
    new = replace_colors(value)
    if prop == "font-size":
        def fs(m):
            picked = snap(float(m.group(1)), FONT_STEPS)
            return "var(%sfs-%d)" % (PREFIX, picked)
        new = re.sub(r"(\d+(?:\.\d+)?)px\b", fs, new)
    elif prop in ("border-radius", "border-top-left-radius", "border-top-right-radius",
                  "border-bottom-left-radius", "border-bottom-right-radius"):
        nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)px", new)]
        if nums and max(nums) < 100:
            new = re.sub(r"(\d+(?:\.\d+)?)px\b", lambda m: "%dpx" % snap(float(m.group(1)), RADIUS_STEPS), new)
        else:
            new = re.sub(r"(\d+(?:\.\d+)?)px\b",
                         lambda m: "999px" if float(m.group(1)) >= 100 else "%dpx" % snap(float(m.group(1)), RADIUS_STEPS), new)
    elif prop in SPACING_PROPS:
        new = re.sub(r"(?<![\w.-])(\d+(?:\.\d+)?)px\b",
                     lambda m: "%dpx" % snap(float(m.group(1)), SPACE_STEPS), new)
    return new


DECL_RE = re.compile(r"([-a-zA-Z][-a-zA-Z0-9]*)\s*:\s*([^;{}]+)")


def process_css(text):
    def sub(m):
        prop = m.group(1).strip().lower()
        value = m.group(2)
        if prop.startswith("--"):
            # 设计包自带的自定义属性（如 --ink:#25354a）也要接到 token 上，
            # 否则用 var(--ink) 的元素会绕开阶梯，重新长出一套近似色。
            new_value = replace_colors(value)
            return m.group(0) if new_value == value else "%s:%s" % (m.group(1), new_value)
        if prop in ("transition", "animation", "transform", "content"):
            return m.group(0)
        if prop == "font" or prop.startswith("font-family"):
            return m.group(0)
        new_value = transform_decl(prop, value)
        if new_value == value:
            return m.group(0)
        return "%s:%s" % (m.group(1), new_value)

    return DECL_RE.sub(sub, text)


TOKENS_CSS = """/* 设计 token：全站唯一的取值来源。
   由 _design_tokens.py 生成，改取值请改那个脚本再重跑，不要在别处手写字面色。
   阶梯规则：字号 6 档、间距 4 的倍数、圆角 3 档、线两条、面四层、墨四层 + 三组状态色。
   命名统一带 --ds- 前缀，避免与设计包自带的 --navy / --line 撞名（撞名会变成自引用而失效）。 */
:root{
  /* 字号 */
  --ds-fs-11:11px; --ds-fs-13:13px; --ds-fs-15:15px; --ds-fs-18:18px; --ds-fs-22:22px; --ds-fs-28:28px;
  /* 间距 */
  --ds-sp-2:2px; --ds-sp-4:4px; --ds-sp-8:8px; --ds-sp-12:12px; --ds-sp-16:16px; --ds-sp-24:24px; --ds-sp-32:32px;
  /* 圆角 */
  --ds-r-6:6px; --ds-r-8:8px; --ds-r-12:12px; --ds-r-999:999px;
%s}
""" % "\n".join("  %s:%s; /* %s */" % (tk(name), value, why) for name, value, why in TOKENS)


def main():
    dry = "--dry" in sys.argv
    out = os.path.join(ASSETS, "tokens.css")
    if not dry:
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(TOKENS_CSS)
        print("写出 assets/tokens.css（%d 个颜色 token）" % len(TOKENS))

    for name in FILES:
        path = os.path.join(ASSETS, name)
        raw = open(path, encoding="utf-8", newline="").read()
        if name == "tokens.css":
            continue
        stats_before = (len(HEX_RE.findall(raw)), len(re.findall(r"font-size\s*:", raw)))
        new = process_css(raw)
        if new != raw:
            if not dry:
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(new)
            print("  %-22s 颜色字面 %4d → var，字号声明 %d 处吸附" % (name, stats_before[0], stats_before[1]))
        else:
            print("  %-22s 无变化" % name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
