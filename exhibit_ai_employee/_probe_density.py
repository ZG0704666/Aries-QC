# -*- coding: utf-8 -*-
"""把「空间都花在哪」量出来：面板 padding / 外边距 / 行高占了多少高度。

不改样式，只读计算样式与几何。目标是为收紧密度提供依据，
不是凭感觉把 padding 改小。
"""
import json
from playwright.sync_api import sync_playwright

ORIGIN = "http://127.0.0.1:4182"
PID = "6dd33d23da"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto(f"{ORIGIN}/?project={PID}", wait_until="networkidle")
    page.wait_for_timeout(600)

    for view in ["live", "content", "project", "release"]:
        page.evaluate("v => location.hash = '#' + v", view)
        page.wait_for_timeout(550)
        out = page.evaluate("""() => {
          const pick = (sel) => {
            const e = document.querySelector(sel);
            if (!e) return null;
            const cs = getComputedStyle(e), r = e.getBoundingClientRect();
            return {sel, pad: cs.padding, margin: cs.margin, gap: cs.gap,
                    radius: cs.borderRadius, w: Math.round(r.width), h: Math.round(r.height)};
          };
          const body = document.querySelector('#workspace-body');
          const br = body ? body.getBoundingClientRect() : {height: 0};
          // 版面内最大的几块空白来源
          const pads = Array.from(document.querySelectorAll('#workspace-body *'))
            .filter(e => e.getBoundingClientRect().height > 40)
            .map(e => {
              const cs = getComputedStyle(e);
              const pt = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
              const mt = parseFloat(cs.marginTop) + parseFloat(cs.marginBottom);
              return {cls: e.className.toString().slice(0, 42), tag: e.tagName,
                      vertical: Math.round(pt + mt), pad: pt, margin: mt};
            })
            .filter(x => x.vertical >= 40)
            .sort((a, b) => b.vertical - a.vertical).slice(0, 8);
          return {
            bodyH: Math.round(br.height),
            items: ['.page-head', '.panel', '.panel-pad', '.panel-header',
                    '.exhibit-tray', '.exhibit-tray .panel-pad', '.pipeline',
                    '.reader', '.reader-body', '.event-inspector', '.event-inspector .panel-pad',
                    '.field input', '.inline-actions button'].map(pick).filter(Boolean),
            biggestVertical: pads,
          };
        }""")
        print("\n===== " + view + " =====")
        print(json.dumps(out, ensure_ascii=False, indent=1))
    b.close()
