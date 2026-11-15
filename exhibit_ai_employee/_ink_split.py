# -*- coding: utf-8 -*-
"""把「文字用的灰」和「装饰用的灰」拆开（一次性迁移，可重复跑，幂等）。

背景：_visual_audit.py 实测 ink-3 在白底只有 3.04、ink-4 只有 1.99，
而它们同时承担着 36 处 / 10 处文字色 —— 元信息淡到读不出来。
但同一组 token 也用在示意图渐变、流水线连线、虚线框上，直接压深会让装饰变重。

所以：装饰整体平移到 --ds-deco-1 / --ds-deco-2（数值 = 旧 ink-3 / ink-4，外观不变），
文字回到压深后的 --ds-ink-3 / --ds-ink-4。
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
FILES = ["styles.css", "refinement.css", "atelier.css", "workspace-tools.css", "studio.css"]

# 这些是交互/焦点态，不是纯装饰：要跟着文字一起变清晰。
KEEP_DARK = [
    (r"outline:3px solid var\(--ds-deco-1\)", "outline:3px solid var(--ds-ink-3)"),
    (r"border-color:var\(--ds-deco-1\);background:var\(--ds-accent-soft\)",
     "border-color:var(--ds-ink-3);background:var(--ds-accent-soft)"),  # button.outline-green
    (r"border-left:3px solid var\(--ds-deco-1\)", "border-left:3px solid var(--ds-ink-3)"),  # feedback-item.active
    (r"border-color:var\(--ds-deco-2\)", "border-color:var(--ds-ink-3)"),  # text-button:hover
]
# 这些是完整句子，不能只到 3.38 那一档，提到 5.08。
UPGRADE_TO_INK3 = [".subtle", ".event-list p", ".exhibit-tile small", ".audio-controls",
                   ".audio-controls button", ".exhibit-tile .meta"]


def main():
    total = 0
    for name in FILES:
        path = os.path.join(ASSETS, name)
        raw = open(path, encoding="utf-8", newline="").read()
        t = raw
        # 1) 全部先平移到装饰档（外观不变）
        t = t.replace("var(--ds-ink-3)", "var(--ds-deco-1)")
        t = t.replace("var(--ds-ink-4)", "var(--ds-deco-2)")
        # 2) 只有 color 声明回到文字档
        t = re.sub(r"color:\s*var\(--ds-deco-1\)", "color:var(--ds-ink-3)", t)
        t = re.sub(r"color:\s*var\(--ds-deco-2\)", "color:var(--ds-ink-4)", t)
        # 3) --muted 是文字别名
        t = t.replace("--muted:var(--ds-deco-1)", "--muted:var(--ds-ink-3)")
        # 4) 交互与焦点态跟着变清晰
        for pat, rep in KEEP_DARK:
            t = re.sub(pat, rep, t)
        # 5) 整句的弱文字提到 ink-3
        for sel in UPGRADE_TO_INK3:
            t = re.sub(r"(" + re.escape(sel) + r"\{[^{}]*?)color:var\(--ds-ink-4\)",
                       lambda m: m.group(1) + "color:var(--ds-ink-3)", t)
        if t != raw:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(t)
            print("%-22s 装饰 %d 处 / 文字 %d 处" % (
                name, t.count("var(--ds-deco-"), t.count("color:var(--ds-ink-")))
            total += 1
        else:
            print("%-22s 无变化" % name)
    print("改动文件数:", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
