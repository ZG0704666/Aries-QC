# -*- coding: utf-8 -*-
"""量 summary 子元素的位置，看清左边那两个符号各自是谁、在哪。"""
import os
import sys
import json
from playwright.sync_api import sync_playwright

PID = sys.argv[1] if len(sys.argv) > 1 else "6dd33d23da"
ORIGIN = "http://127.0.0.1:4182"
with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto(f"{ORIGIN}/?project={PID}", wait_until="networkidle")
    page.wait_for_timeout(600)
    page.evaluate("location.hash='#release'")
    page.wait_for_timeout(700)
    out = page.evaluate("""() => {
      const s = document.querySelector('.file-tree summary');
      if (!s) return null;
      const cs = getComputedStyle(s);
      const bef = getComputedStyle(s, '::before');
      const aft = getComputedStyle(s, '::after');
      const r = s.getBoundingClientRect();
      return {
        text: s.textContent,
        display: cs.display, columns: cs.gridTemplateColumns, padding: cs.padding,
        before: {content: bef.content, width: bef.width, display: bef.display,
                 border: bef.border, flex: bef.flex},
        after: {content: aft.content, width: aft.width, display: aft.display},
        rect: {x: r.x, y: r.y, h: r.height},
        kids: Array.from(s.childNodes).map(n => ({
          type: n.nodeType, name: n.nodeName,
          text: n.nodeType === 3 ? JSON.stringify(n.textContent) : n.textContent,
          rect: n.getBoundingClientRect ? {x: n.getBoundingClientRect().x, w: n.getBoundingClientRect().width} : null
        }))
      };
    }""")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    b.close()
