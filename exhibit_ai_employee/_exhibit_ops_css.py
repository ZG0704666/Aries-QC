# -*- coding: utf-8 -*-
"""展项瓦片从「一整颗按钮」改成「标题可点 + 独立操作」后的样式。幂等。"""
from pathlib import Path

p = Path(__file__).resolve().parent / "assets" / "studio.css"
text = p.read_text(encoding="utf-8")
marker = "/* ── 展项独立操作"
if marker in text:
    print("already applied")
    raise SystemExit(0)

block = """

/* ── 展项独立操作（每个展项是独立执行单元，不必都走对话框）────
   瓦片从一整颗 <button> 改成 <div>：标题区切换展项，底部两个按钮
   分别是「重做」（只重新生成这个展项）和「合成」（只合成这个展项的音频）。
   button 不能嵌套 button，所以结构必须拆开。 */
#workspace-body .exhibit-tile{display:flex;flex-direction:column;gap:0;padding:0;overflow:hidden;text-align:left}
#workspace-body .exhibit-pick{display:flex;gap:10px;align-items:flex-start;width:100%;
  padding:var(--ds-sp-12);border:0;background:transparent;text-align:left;cursor:pointer;
  border-radius:0;box-shadow:none;min-height:0}
#workspace-body .exhibit-pick:hover{background:color-mix(in srgb, var(--ds-accent-soft) 55%, transparent);box-shadow:none}
#workspace-body .exhibit-pick:active{transform:none}
#workspace-body .exhibit-pick>span:last-child{min-width:0;flex:1}
#workspace-body .exhibit-pick strong{display:block;font-size:var(--ds-fs-13);line-height:1.55;
  margin-bottom:6px;overflow-wrap:anywhere;font-weight:600;color:var(--ds-ink-1)}
#workspace-body .exhibit-pick small{display:block;font-size:var(--ds-fs-11);color:var(--ds-ink-2);margin-top:4px}

/* 操作行：两个轻量按钮，不抢主行动。只在这个展项自己的卡片里生效。 */
#workspace-body .exhibit-ops{display:flex;gap:0;border-top:1px solid var(--ds-line);margin-top:auto}
#workspace-body .exhibit-ops button{flex:1;min-height:36px;padding:6px 4px;border:0;background:transparent;
  font-size:var(--ds-fs-11);color:var(--ds-ink-2);border-radius:0;cursor:pointer;box-shadow:none;
  transition:background .15s ease,color .15s ease}
#workspace-body .exhibit-ops button+button{border-left:1px solid var(--ds-line)}
#workspace-body .exhibit-ops button:not(:disabled):hover{background:var(--ds-accent-soft);color:var(--ds-accent-deep);box-shadow:none}
#workspace-body .exhibit-ops button:disabled{opacity:.5;cursor:not-allowed}

/* 生成中的瓦片：边框呼吸，一眼知道是哪一张在跑 */
#workspace-body .exhibit-tile.is-running{border-color:var(--ds-warn);background:var(--ds-warn-soft)}
@keyframes ds-tile-pulse{0%,100%{box-shadow:0 0 0 0 color-mix(in srgb,var(--ds-warn) 0%,transparent)}
  50%{box-shadow:0 0 0 3px color-mix(in srgb,var(--ds-warn) 22%,transparent)}}
#workspace-body .exhibit-tile.is-running{animation:ds-tile-pulse 1.4s ease-in-out infinite}
@media (prefers-reduced-motion:reduce){#workspace-body .exhibit-tile.is-running{animation:none}}

/* 瓦片变高后，150px 的列宽仍然够：标题折行由 exhibit-pick strong 的 overflow-wrap 保证 */
"""
p.write_text(text + block, encoding="utf-8", newline="\n")
print("exhibit ops styles appended")
