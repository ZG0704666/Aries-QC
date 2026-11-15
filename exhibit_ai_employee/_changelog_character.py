# -*- coding: utf-8 -*-
"""CHANGELOG 顶部追加「内容气质」一节。幂等。"""
from pathlib import Path

p = Path(__file__).resolve().parent / "CHANGELOG.md"
text = p.read_text(encoding="utf-8")
marker = "## 内容气质"
if marker in text:
    print("already present")
    raise SystemExit(0)

block = """## 内容气质：展签式正文 · 图录式引用 · 阶段条仪式感 — 2026-11-15

方向：记忆点不靠装饰，靠给「内容」一套区别于「界面」的排版语言。界面保持 sans-serif，展品文字用宋体族——这是展览图录的做法。

### 落地（只在 studio.css 末尾追加，不改 JS）
- **内容字体分家**：`.script-body` / `.quote p` / `.fact-item p` 用宋体族（Songti SC / STSong / SimSun / Noto Serif CJK SC / serif），UI 其余保持 sans。界面是界面，展品文字是另一套字体。
- **展签式正文**：首行缩进 2em、行高 2.05、左对齐（中文不 justify——窄栏两端对齐会拉散字距）；标题下一道细展签线。
- **图录式引用**：左侧 2px 绿色竖线、大号衬线引号、斜体引用文、「原文引用」小字大写感；来源编号保持等宽与斜体形成材质对比。
- **阶段条仪式感**：当前段（`.pipeline li.current`）下缘一道短刻度线。

### 判据修正
- 正文原设 `text-align:justify + inter-ideograph`，窄栏字距被拉散 → 改回左对齐，保留首行缩进即可表达展签气质。
- 阶段条类名是 `.current`/`.done`（非 `.is-current`/`[aria-current]`），选择器先查实际类名再写。

### 回归
`_audit_full` 77/77（F49 A12 D16）、`_ui_layout` 25/25、`_ui_checks` 51/51、`_check_skill_applied` 14/14。

"""
p.write_text(block + text, encoding="utf-8", newline="\n")
print("changelog updated")
