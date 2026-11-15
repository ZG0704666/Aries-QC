# -*- coding: utf-8 -*-
"""content 屏展项托盘下面有一大块空白，量一下高度是谁撑的。只读。"""
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://127.0.0.1:4182/?project=6dd33d23da", wait_until="networkidle")
    page.wait_for_timeout(500)
    page.evaluate("location.hash = '#content'")
    page.wait_for_timeout(600)
    out = page.evaluate("""() => {
      const tray = document.querySelector('.exhibit-tray');
      const chain = [];
      let e = tray;
      while (e && e.id !== 'workspace-body') {
        const cs = getComputedStyle(e), r = e.getBoundingClientRect();
        chain.push({cls: e.className.toString().slice(0, 40), tag: e.tagName,
                    h: Math.round(r.height), pad: cs.padding, margin: cs.margin,
                    minH: cs.minHeight, display: cs.display, align: cs.alignItems});
        e = e.parentElement;
      }
      const tiles = Array.from(document.querySelectorAll('.exhibit-tile')).map(t => {
        const r = t.getBoundingClientRect();
        return {id: t.querySelector('strong')?.textContent.slice(0, 5), h: Math.round(r.height), top: Math.round(r.top)};
      });
      return {chain, tiles};
    }""")
    import json
    print(json.dumps(out, ensure_ascii=False, indent=1))
    b.close()
