# -*- coding: utf-8 -*-
"""把「真正使用 ui-ux-pro-max skill」这一段记进 CHANGELOG。幂等。"""
from pathlib import Path

p = Path(__file__).resolve().parent / "CHANGELOG.md"
text = p.read_text(encoding="utf-8")
marker = "## 真正使用 ui-ux-pro-max skill"
if marker in text:
    print("already recorded")
    raise SystemExit(0)

block = """## 真正使用 ui-ux-pro-max skill — 2026-11-15（CODE_REV studio-2026-11-15-n）

上一轮只用了它的规则表当尺子，没跑数据库，被问「设计 skill 用了吗」时答不上来。
这一轮先查清楚为什么跑不了，再真跑、真落地、真验证。

### 缺文件的原因

`~/.agents/skills/ui-ux-pro-max/` 下的 `data`（31 字节）和 `scripts`（34 字节）
**不是目录，是两个纯文本文件**，内容分别写着 `../../../src/ui-ux-pro-max/data` 和
`../../../src/ui-ux-pro-max/scripts`——Git 符号链接在 Windows 未启用 `core.symlinks=true`
时被 checkout 成了文本指针。之前用 `Get-ChildItem -Recurse` 看到「空」就当成空目录，是误判；
要看 `Mode` 列（`-a----` 是文件，`d-----` 才是目录）。

### 恢复方式

上游是 `nextlevelbuilder/ui-ux-pro-max-skill`（MIT）。本机只有 api.github.com 通，
用 tarball 端点拉源码，把真正的 `scripts/`（search.py / core.py / design_system.py）
和 `data/`（16 个 CSV：styles / colors / typography / products / ux-guidelines …）
复制进技能目录，替换掉两个占位文本文件。`search.py --help` 与 `--design-system` 均跑通。

### 真实输出与取舍

- `--design-system` 给出 **Data-Dense Dashboard**：行 hover 高亮、数据加载 spinner、
  hover 150–300ms、cursor-pointer、对比度 4.5:1、reduced-motion。
- `--domain ux`：可点元素要有 hover 反馈、长内容截断+展开、input 必须配 label、
  表格用 overflow-x-auto 包裹、大数字加千分位、正文行高 1.5–1.75。
- `--domain color` 首推 **navy `#1E3A5F` + green `#16A34A`**，与现有
  `--ds-navy #132541` / `--ds-accent #16815f` 同族，**配色方向确认，不换**。
- 不照抄的部分：返回的 Pattern 是「Enterprise Gateway」营销官网结构，与工作台形态不符；
  推荐字体 Fira Code / Fira Sans 不适合中文正文。只取可量化的交互与排版规则。

### 落地（assets/studio.css 末尾，全部走 token）

1. 行 hover 高亮：表格行、反馈项、展项瓦片、门禁行、成本行、运行事件，
   150ms 过渡，包在 `@media (hover:hover)` 里，触屏不依赖 hover。
2. 等宽数字：金额、指标、时长、编号统一 `font-variant-numeric: tabular-nums`。
3. 折叠指示：summary 统一 CSS 三角，随开合旋转。
4. 生成中反馈：`pendingRun` 时主按钮显示 spinner，pending 气泡头像慢转，
   `prefers-reduced-motion` 下全部静止。

### 过程中修掉的一个真缺陷

折叠箭头第一次上线后出现**双箭头 + 换行**：`styles.css` 给
`.file-tree summary::before` 写过字符 `'›'`、展开时是 `'⌄'`，
`workspace-tools.css` 给 `.event-history > summary::before` 也写过 `'›'`。
这些选择器比 `details > summary::before` 更具体，**后加载也压不住**，
新画的 CSS 三角和旧字符叠在一起。修法是对这两处用同等级或更具体的选择器把
`content` 一并收回；`.file-tree summary` 的 grid 三列布局单独保留，不能被改成 flex。
同时删掉 `app.js` 里文件树 summary 手写的 `▤` 装饰字符。

教训：改组件级样式前先把**命中同一伪元素的全部规则**列出来
（遍历 `document.styleSheets` 的 `cssRules`），别只看自己新增的那份文件。

### 验证

新增 `_check_skill_applied.py`（14 条）：真的 hover 量背景色变化、量过渡时长、
量等宽数字、量箭头边框宽度与旋转矩阵、量 summary 单行高度、量文件树 display 仍是 grid、
量 spinner 的 animationName，七视图无横向溢出、零 JS 错误。
全量回归：`_audit_full.py` 77/77、`_ui_layout.py` 25/25、`_ui_checks.py` 51/51。
"""
text = text.replace("# CHANGELOG\n\n", "# CHANGELOG\n\n" + block + "\n", 1)
p.write_text(text, encoding="utf-8", newline="\n")
print("changelog updated")
