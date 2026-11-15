# -*- coding: utf-8 -*-
"""密度与层级（m04241）：按 _probe_density.py 的实测读数收紧，不凭感觉改。

只追加到 studio.css 末尾（最后加载，可回退），不改前面四层 CSS。
幂等：已带标记则跳过。
"""
from pathlib import Path

p = Path(__file__).resolve().parent / "assets" / "studio.css"
text = p.read_text(encoding="utf-8")
marker = "/* ── 密度与层级"
if marker in text:
    print("already applied")
    raise SystemExit(0)

block = """

/* ── 密度与层级（依据 _probe_density.py 实测）────────────────────
   读数：panel-pad 24px、panel-header 24px、paper 上下 52px、
   exhibit-tray 上下 40px、pipeline 上下 48px，嵌套卡片还要叠两层。
   问题不是「元素太小」，是统一的大 padding 把内容稀释了。
   收紧容器、保住正文：讲解正文的字号行高不动，触控目标仍 >=44px。 */

/* ① 面板内边距 24 → 18；面板标题区跟着收，不再上下各 24 */
#workspace-body .panel-pad{padding:var(--ds-sp-16)}
#workspace-body .panel-header{padding:var(--ds-sp-16) var(--ds-sp-16) var(--ds-sp-8)}
#workspace-body .event-inspector .panel-pad{padding:var(--ds-sp-16)}
#workspace-body .panel h3,#workspace-body .panel-header h3{margin-bottom:var(--ds-sp-12)}
#workspace-body .panel h4{margin:var(--ds-sp-16) 0 var(--ds-sp-8)}

/* ② 讲解正文：把版面还给文本。
   原来 paper 上下 28+24=52px、script-body 限宽 36em，
   一屏读不完一段讲解。内边距收紧，正文限宽放宽到 44em（中文长行仍可读）。 */
#workspace-body .paper,#workspace-body .workspace-body[data-view="live"] .paper,
.workspace-body[data-view="live"] .paper{padding:var(--ds-sp-16) var(--ds-sp-24)}
#workspace-body .paper-heading{margin-bottom:var(--ds-sp-12)}
#workspace-body .script-body{max-width:44em;line-height:1.9;margin-bottom:var(--ds-sp-16)}
#workspace-body .quote,.workspace-body[data-view="live"] .paper .quote{
  margin-top:var(--ds-sp-16);padding:var(--ds-sp-12) var(--ds-sp-16)}

/* ③ 展项托盘：上下 40 → 24，瓦片本身不再撑高 */
#workspace-body .exhibit-tray{margin:0 var(--ds-sp-16) var(--ds-sp-16);padding-top:var(--ds-sp-12)}

/* ④ 阶段条：上下 48 → 32，仍保持等分与 44px 触控 */
#workspace-body .pipeline{padding:var(--ds-sp-8) var(--ds-sp-8);margin-bottom:var(--ds-sp-16)}

/* ⑤ 层级：当前展项 / 当前阻断要一眼能认出来。
   只加强「当前」与「阻断」的对比，不给普通卡片加装饰。 */
#workspace-body .exhibit-tile.active{
  background:var(--ds-accent-soft);border-color:var(--ds-accent);
  box-shadow:inset 3px 0 0 var(--ds-accent)}
#workspace-body .exhibit-tile.active strong{color:var(--ds-accent-deep)}
#workspace-body .notice.red,#workspace-body .event-inspector .notice.red{
  border-left:3px solid var(--ds-danger)}
#workspace-body .notice.green,#workspace-body .event-inspector .notice.green{
  border-left:3px solid var(--ds-accent)}

/* ⑥ 列表行高：门禁/明细/成本行原来 12px 上下 + 1.7 行高，略松。
   收到 8px 上下，行距不变，可读性不动。 */
#workspace-body .gate-list li{padding:var(--ds-sp-8) 0}
#workspace-body .event-list{margin:var(--ds-sp-16) 0 var(--ds-sp-12)}
#workspace-body .event-list li{padding-bottom:var(--ds-sp-16)}

/* ⑦ 卡片圆角统一收到 10px：圆角种类从 5 种降到 3 种（6/10/999），
   16px 的大圆角在密集面板上显得浮肿。 */
#workspace-body .panel{border-radius:10px}
#workspace-body .reading-dialog{border-radius:12px}

/* 窄屏不跟着压：手机优先可读与触控，沿用原 breakpoint 的值 */
@container (max-width:720px){
  #workspace-body .panel-pad{padding:var(--ds-sp-16)}
  #workspace-body .script-body{max-width:none}
}
"""
p.write_text(text + block, encoding="utf-8", newline="\n")
print("density + hierarchy appended")
