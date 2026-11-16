# -*- coding: utf-8 -*-
"""元宝网页版 v4：按用户截图（登录态 + 底部“用户戴9527”）。"""
import html, re, sys
sys.path.insert(0, r"F:\deepseek\_work")
from md import render_md

CSS = r"""
:root{--bg:#1b1b1c;--side:#161617;--line:#2b2b2e;--text:#e9e9ec;--muted:#8c8c93;--blue:#3a5bd9}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:"PingFang SC","Microsoft YaHei",sans-serif;
 font-size:15px;line-height:1.75;-webkit-font-smoothing:antialiased}
.app{display:flex;height:100vh;overflow:hidden}
.side{width:250px;background:var(--side);display:flex;flex-direction:column;flex:0 0 250px;padding:12px 10px 10px}
.icons{display:flex;gap:14px;color:#c9c9cf;padding:4px 6px 8px}
.icons svg{width:18px;height:18px;stroke:currentColor;fill:none;stroke-width:1.7}
.brand{font-size:21px;font-weight:700;letter-spacing:.5px;padding:6px 6px 16px;display:flex;align-items:center;gap:8px}
.logo{width:24px;height:24px;border-radius:7px;background:linear-gradient(135deg,#5b7cfa,#8a5bfa);display:flex;align-items:center;justify-content:center;font-size:13px}
.row{display:flex;align-items:center;gap:10px;padding:9px 11px;border-radius:9px;font-size:14px;color:#e2e2e6;margin-bottom:3px}
.row svg{width:17px;height:17px;stroke:currentColor;fill:none;stroke-width:1.6;flex:0 0 17px}
.row.act{background:#2a2a2c}
.hlabel{color:#7d7d85;font-size:12px;padding:16px 11px 6px}
.hist{flex:1;overflow:hidden;padding:0 2px}
.hitem{padding:7px 10px;border-radius:8px;font-size:13px;color:#c9c9d0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-bottom:1px}
.hitem.on{background:#26262a;color:#fff}
.dl{display:flex;align-items:center;justify-content:center;gap:8px;border:1px solid #2b2b2e;border-radius:10px;
 padding:10px;font-size:13px;color:#d8d8dc;margin-top:6px}
.dl svg{width:15px;height:15px;stroke:currentColor;fill:none;stroke-width:1.7}
.acct{display:flex;align-items:center;gap:9px;padding:9px 8px 2px;margin-top:4px}
.acct .ava{width:28px;height:28px;border-radius:50%;background:#3b3b41;display:flex;align-items:center;justify-content:center;font-size:12px;color:#e8e8ec;flex:0 0 28px}
.acct .nm{font-size:13px;color:#dcdce2}
.main{flex:1;display:flex;flex-direction:column;min-width:0;position:relative}
.top{height:56px;display:flex;align-items:center;gap:10px;padding:0 20px;flex:0 0 56px}
.top .right{margin-left:auto;display:flex;align-items:center;gap:10px}
.ghost{border:1px solid #3a3a3d;border-radius:8px;padding:6px 14px;font-size:12.5px;color:#d6d6da}
.inst{display:flex;align-items:center;gap:6px;background:#f2f2f2;color:#1c1c1c;border-radius:8px;padding:6px 12px;font-size:12.5px;font-weight:600}
.inst svg{width:14px;height:14px;stroke:#12b886;fill:none;stroke-width:2}
.scroll{flex:1;overflow:hidden;position:relative}
.thread{width:840px;max-width:calc(100% - 110px);margin:0 auto;padding:16px 0 170px}
.msg{display:flex;gap:12px;margin-bottom:24px}
.msg.user{flex-direction:row-reverse}
.msg.user .body{text-align:right}
.who2{flex:0 0 30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:600;color:#fff}
.who2.ai{background:linear-gradient(135deg,#5b7cfa,#8a5bfa)}
.who2.user{background:#3b3b41;color:#e8e8ec}
.body{flex:1;min-width:0}
.meta{display:flex;gap:8px;margin-bottom:5px}
.meta .n{font-size:14px;font-weight:700}
.bubble{display:inline-block;max-width:76%;background:var(--blue);color:#fff;border-radius:14px;padding:11px 15px;text-align:left;box-shadow:0 1px 2px rgba(0,0,0,.18)}
.plain{color:#e6e6e8}
.plain h3{font-size:15px;margin:13px 0 7px;color:#fff}
.plain p{margin:7px 0}
.plain ol,.plain ul{margin:7px 0 9px;padding-left:22px}
.plain li{margin:4px 0}
.plain code{background:#2b2b2e;color:#ffd48a;border-radius:5px;padding:1px 6px;font-size:13px;font-family:Consolas,monospace}
.plain pre{background:#141415;border:1px solid #2c2c30;border-radius:10px;padding:12px 14px;margin:9px 0;
 font-family:Consolas,monospace;font-size:13px;line-height:1.6;color:#cfd6e6}
.plain table{border-collapse:collapse;margin:11px 0;font-size:13.5px;width:100%}
.plain th,.plain td{border:1px solid #34343a;padding:6px 10px;text-align:left}
.plain th{background:#26262b;color:#fff}
.plain blockquote{border-left:3px solid #e0a83c;background:#242320;color:#e3d7b9;padding:9px 13px;border-radius:0 8px 8px 0;margin:11px 0;font-size:13.5px}
.think{display:inline-flex;gap:6px;color:#8c8c93;font-size:12.5px;background:#232326;border:1px solid #2e2e33;border-radius:999px;padding:3px 10px;margin-bottom:8px}
.actions{display:flex;gap:18px;color:#75757d;font-size:12.5px;margin-top:10px;align-items:center}
.actions span{display:flex;align-items:center;gap:4px}
.actions svg{width:14px;height:14px;stroke:currentColor;fill:none;stroke-width:1.6}
.composer{position:absolute;left:0;right:0;bottom:0;background:var(--bg);padding:18px 0 10px}
.box{width:840px;max-width:calc(100% - 110px);margin:0 auto;background:#242426;border:1px solid #323236;border-radius:18px;padding:14px 18px 10px}
.box .ph{color:#6d6d74;font-size:15px;min-height:38px}
.box .tools{display:flex;align-items:center;gap:16px;margin-top:6px;color:#a9a9b2;font-size:13px;flex-wrap:nowrap}
.tool{display:flex;align-items:center;gap:5px;white-space:nowrap}
.tool svg{width:16px;height:16px;stroke:currentColor;fill:none;stroke-width:1.6}
.plus{width:26px;height:26px;border-radius:50%;background:#2e2e32;display:flex;align-items:center;justify-content:center;font-size:16px}
.send{margin-left:auto;width:32px;height:32px;border-radius:50%;background:#3a3a3e;display:flex;align-items:center;justify-content:center;color:#e6e6ea}
.disc{text-align:center;color:#5c5c63;font-size:11px;margin-top:8px}
"""

IC = {
 "panel":'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/></svg>',
 "search":'<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/></svg>',
 "refresh":'<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 1 0-2 6"/><path d="M20 5v6h-6"/></svg>',
 "new":'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/></svg>',
 "ai":'<svg viewBox="0 0 24 24"><path d="M4 20l6-16 4 9 4-4 2 11z"/></svg>',
 "plus":'<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
 "dl":'<svg viewBox="0 0 24 24"><path d="M12 4v10M8 10l4 4 4-4M5 19h14"/></svg>',
 "install":'<svg viewBox="0 0 24 24"><path d="M12 4v10M8 10l4 4 4-4M5 19h14"/></svg>',
 "pic":'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M4 18l5-5 4 4 3-3 4 4"/></svg>',
 "pen":'<svg viewBox="0 0 24 24"><path d="M4 20l4-1 10-10-3-3L5 16z"/></svg>',
 "solve":'<svg viewBox="0 0 24 24"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 9h6M9 13h4"/></svg>',
 "deep":'<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 3v4M12 17v4M3 12h4M17 12h4"/></svg>',
 "ppt":'<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
 "data":'<svg viewBox="0 0 24 24"><path d="M4 20V10M10 20V5M16 20v-7M22 20H2"/></svg>',
 "more":'<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/></svg>',
 "spark":'<svg viewBox="0 0 24 24"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/></svg>',
 "chev":'<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
 "copy":'<svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>',
 "regen":'<svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 14-5M20 12a8 8 0 0 1-14 5"/></svg>',
 "up":'<svg viewBox="0 0 24 24"><path d="M7 21V9l5-6 5 6v12"/></svg>',
 "down":'<svg viewBox="0 0 24 24"><path d="M7 3v12l5 6 5-6V3"/></svg>',
}

def build(spec, turns, username, out_path, history=None):
    ini = username[0] if username else "我"
    hist = history or []
    hhtml = "".join(f'<div class="hitem{" on" if k==0 else ""}">{html.escape(h)}</div>' for k,h in enumerate(hist[:7]))
    msgs=[]
    for idx,t in enumerate(turns):
        if t["role"]=="user":
            msgs.append('<div class="msg user"><div class="who2 user">' + ini + '</div><div class="body">'
                        f'<div class="bubble">{html.escape(t["text"])}</div></div></div>')
        else:
            body=render_md(t["text"])
            msgs.append('<div class="msg"><div class="who2 ai">元</div><div class="body">'
                        '<div class="meta"><span class="n">元宝</span></div>'
                        + ('<div class="think">已深度思考（用时 8 秒）</div>' if idx%3==0 else '')
                        + f'<div class="plain">{body}</div>'
                        + f'<div class="actions"><span>{IC["copy"]} 复制</span><span>{IC["regen"]} 重新生成</span>'
                        + f'<span>{IC["up"]}</span><span>{IC["down"]}</span></div></div></div>')
    page=f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><style>{CSS}
.side{{position:fixed;left:0;top:0;bottom:0}}
.main{{margin-left:250px;height:100vh}}
.top{{position:absolute;left:0;right:0;top:0;z-index:6;background:var(--bg)}}
.scroll{{position:absolute;left:0;right:0;top:56px;bottom:0;overflow:hidden}}
</style></head><body><div class="app">
<aside class="side">
  <div class="icons">{IC['panel']}{IC['search']}{IC['refresh']}</div>
  <div class="brand"><span class="logo">元</span>元宝</div>
  <div class="row act">{IC['new']}新建对话</div>
  <div class="row">{IC['ai']}AI创作</div>
  <div class="hlabel">分组</div>
  <div class="row">{IC['plus']}创建分组</div>
  <div class="hist">{hhtml}</div>
  <div class="dl">{IC['dl']}前往下载中心</div>
  <div class="acct"><span class="ava">{ini}</span><span class="nm">{html.escape(username)}</span></div>
</aside>
<div class="main">
  <div class="top"><div class="right"><span class="ghost">登录</span>
    <span class="inst">{IC['install']}安装电脑版{IC['chev']}</span></div></div>
  <div class="scroll"><div class="thread">{''.join(msgs)}</div></div>
  <div class="composer"><div class="box"><div class="ph">发送消息</div>
    <div class="tools"><span class="plus">＋</span>
      <span class="tool">{IC['spark']}快速回答{IC['chev']}</span>
      <span class="tool">{IC['pic']}AI生图</span>
      <span class="tool">{IC['pen']}写作</span>
      <span class="tool">{IC['solve']}解题</span>
      <span class="tool">{IC['deep']}深度研究</span>
      <span class="tool">{IC['ppt']}PPT生成</span>
      <span class="tool">{IC['data']}数据分析</span>
      <span class="tool">{IC['more']}更多</span>
      <span class="send">↑</span></div></div>
    <div class="disc">内容由 AI 生成，仅供参考</div>
  </div>
</div></div>
<script>
function go(){{const q=new URLSearchParams(location.search);const i=parseFloat(q.get('i')||'0');const n=parseFloat(q.get('n')||'7');
const s=document.querySelector('.scroll');const m=Math.max(0,s.scrollHeight-s.clientHeight);s.scrollTop=Math.round(m*i/n);}}
document.addEventListener('DOMContentLoaded',go);window.addEventListener('load',go);setTimeout(go,80);setTimeout(go,400);
</script></body></html>"""
    open(out_path,"w",encoding="utf-8").write(page)
    return out_path

