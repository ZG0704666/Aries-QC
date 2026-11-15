# -*- coding: utf-8 -*-
"""密度与层级这一轮记进 CHANGELOG。幂等。"""
from pathlib import Path

p = Path(__file__).resolve().parent / "CHANGELOG.md"
text = p.read_text(encoding="utf-8")
marker = "## 密度与层级"
if marker in text:
    print("already recorded")
    raise SystemExit(0)

block = """## 密度与层级 — 2026-11-15（CODE_REV studio-2026-11-15-n）

承接「前端如何」的自评：工程扎实但视觉只是干净——信息密度低、层级平。
这一轮不加装饰，只收紧容器、把版面还给内容。

### 先量后改

新增 `_probe_density.py`：对 live / content / project / release 四屏量
panel / panel-pad / panel-header / exhibit-tray / pipeline / paper 的
padding、margin、宽高，并列出垂直方向 padding+margin ≥40px 的元素。

读数：`panel-pad` 24px、`panel-header` 24px、paper 上下 52px、
exhibit-tray 上下 40px、pipeline 上下 48px，嵌套卡片还要叠两层。
问题不是元素太小，是**统一的大 padding 把内容稀释了**。

### 改动（全部只追加到 assets/studio.css 末尾，可回退）

1. 面板内边距 24 → 16，标题区 24/10 → 16/8。
2. 讲解正文：paper 上下 52 → 32，正文限宽 36em → 44em，行高 1.9。
   字号不动，触控目标仍 ≥44px。
3. 展项托盘上下 40 → 24。
4. 阶段条上下 48 → 32，等分不变。
5. 层级只加强「当前」与「阻断」：当前展项绿描边 + 左侧 3px 色条 + 标题深色；
   阻断通知左侧 3px 红条、通过通知左侧 3px 绿条。普通卡片不加装饰。
6. 门禁/明细/成本行上下 12 → 8。
7. 面板圆角 16/12 → 10。

### 过程中发现并解决的一个布局问题

展项托盘原来是 `minmax(180px,1fr)`，806px 宽只够 4 列，
5 个展项排成 4+1，第二行只有 EX05 一个，右侧四分之三空着。
降到 `minmax(150px,1fr)` 后 5 张一行：

- 托盘高度 251 → 148px，面板 301 → 198px，**省出 103px**。
- 代价是瓦片标题折成三行（「EX01 她是/谁：乔孔多的/妻子丽莎」）。
  信息完整、选中态明确，比孤行浪费半屏好，**保留这个取舍**。

### 一个指标教训

`_visual_audit.py` 的「留白率」在改动前后几乎没变（88~90%）。
原因是它把顶栏、侧栏、卡片底色全算进留白，padding 收 8px 在整屏像素里看不出。
**有意义的指标是内容高度与一屏能否读完正文**，不是全屏留白百分比。
以后评估密度改动，量目标容器的高度变化，不看全屏留白率。

### 验证

- `_audit_full.py` 77/77（功能 49、对齐 12、设计 16）
- `_check_skill_applied.py` 14/14
- `_ui_layout.py` 25/25（五宽度无横向溢出、字号仍在 6 档阶梯）
- `_ui_checks.py` 51/51 零 JS 错误、`_probe_empty.py` 34/34
- 真实项目「蒙娜丽莎」截图复核：live 正文一屏读完、content 五张瓦片一行、
  project 表单与报价一屏放下。
"""
text = text.replace("# CHANGELOG\n\n", "# CHANGELOG\n\n" + block + "\n", 1)
p.write_text(text, encoding="utf-8", newline="\n")
print("changelog updated")
