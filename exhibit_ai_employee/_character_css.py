# -*- coding: utf-8 -*-
"""内容气质层：展签式正文 + 图录式引用 + 阶段条仪式感。

只在最后加载的 studio.css 末尾追加，不动前四层、不改 JS。
核心：界面保持 sans，「展品文字」（讲解正文、原文引用）用宋体族，
形成「界面 vs 内容」的层次——这是展览图录的做法。幂等。
"""
from pathlib import Path

p = Path(__file__).resolve().parent / "assets" / "studio.css"
text = p.read_text(encoding="utf-8")
marker = "/* ── 内容气质"
if marker in text:
    print("already applied")
    raise SystemExit(0)

block = """

/* ── 内容气质：展签式正文 · 图录式引用 · 阶段条仪式感 ────────────
   原则：不加花哨装饰，只给「内容」一套区别于「界面」的排版语言。
   界面（按钮、导航、表单）保持 sans-serif；
   展品文字（讲解正文、原文引用）用宋体族，像真正的展签与图录。 */

/* 内容字体栈：宋体优先，跨平台回退到衬线。只用于内容，不碰 UI。 */
#workspace-body .script-body,
#workspace-body .paper .quote p,
#workspace-body .fact-item p{
  font-family:"Songti SC","STSong","SimSun","Noto Serif CJK SC",Georgia,serif;
}

/* ① 展签式正文：首行缩进两字，段间距靠行高而非大 margin。
   展签的特征是克制——细线、呼吸感、文字本身是主角。 */
#workspace-body .paper .script-body{
  font-size:var(--ds-fs-15);
  line-height:2.05;
  letter-spacing:.01em;
  color:var(--ds-ink-1);
  text-indent:2em;
  text-align:justify;
  text-justify:inter-ideograph;
}
/* 展签正文上方一道极细的「展签线」，把标题与正文轻轻分开 */
#workspace-body .paper .paper-heading{
  padding-bottom:var(--ds-sp-12);
  border-bottom:1px solid var(--ds-line);
}
#workspace-body .paper .paper-heading strong{font-weight:600;letter-spacing:.02em}

/* ② 图录式引用：大号衬线引号、左侧一道竖线、来源编号等宽。
   图录（catalogue raisonné）的引用永远是斜体衬线 + 竖线。 */
#workspace-body .paper .quote{
  position:relative;
  background:var(--ds-surface-1);
  border:0;
  border-left:2px solid var(--ds-accent);
  border-radius:0;
  padding:var(--ds-sp-16) var(--ds-sp-24) var(--ds-sp-16) var(--ds-sp-24);
  margin-top:var(--ds-sp-24);
}
#workspace-body .paper .quote .quote-head{
  display:flex;align-items:center;justify-content:space-between;gap:8px;
  margin-bottom:var(--ds-sp-8);
}
#workspace-body .paper .quote .quote-mark{
  font-family:Georgia,serif;
  font-size:28px;line-height:1;color:var(--ds-accent);
  margin-right:4px;vertical-align:-2px;
}
#workspace-body .paper .quote .quote-head>span:first-child{
  font-size:var(--ds-fs-11);letter-spacing:.12em;color:var(--ds-ink-2);
  text-transform:uppercase;font-weight:600;
}
#workspace-body .paper .quote p{
  font-size:var(--ds-fs-15);line-height:1.95;font-style:italic;
  color:var(--ds-ink-1);margin:0;text-indent:0;
}
/* 引用的来源编号（F-001 等）保持等宽，与斜体正文形成材质对比 */
#workspace-body .paper .mono,#workspace-body .fact-item .fact-meta .mono{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-style:normal;letter-spacing:.02em;
}

/* ③ 阶段条仪式感：完成的段落是「已归档」，当前段落是「正在此」。
   不靠更亮的颜色，靠细节：完成段的勾加一圈细环，当前段下缘一道短刻度线。 */
#workspace-body .pipeline li{position:relative}
#workspace-body .pipeline li.is-current::after,
#workspace-body .pipeline li[aria-current]::after{
  content:"";position:absolute;left:50%;bottom:-2px;transform:translateX(-50%);
  width:24px;height:2px;background:var(--ds-accent);border-radius:2px;
}

/* 展签编号（EX01 / F-001 / WEB-001）给一点字距，像真正的馆藏编号 */
#workspace-body .eyebrow,#workspace-body .artifact-heading .mono,
#workspace-body .exhibit-pick strong{
  letter-spacing:.03em;
}

/* 屏幕较窄时取消首行缩进与 justify，避免窄栏里字距被拉散 */
@media(max-width:760px){
  #workspace-body .paper .script-body{text-indent:0;text-align:left}
}
"""
p.write_text(text + block, encoding="utf-8", newline="\n")
print("content character styles appended")
