# -*- coding: utf-8 -*-
"""量展项瓦片：列数、每个按钮文字是否折行（高度异常）。"""
import json
from playwright.sync_api import sync_playwright

ORIGIN = "http://127.0.0.1:4182"
PID = "6dd33d23da"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto(f"{ORIGIN}/?project={PID}", wait_until="networkidle")
    page.wait_for_timeout(500)
    data = page.evaluate("""() => {
      const tray = document.querySelector('.exhibit-tray');
      const tiles = [...document.querySelectorAll('.exhibit-tile')];
      const rows = {};
      tiles.forEach(t => { const y = Math.round(t.getBoundingClientRect().top); rows[y] = (rows[y]||0)+1; });
      return {
        trayWidth: Math.round(tray.getBoundingClientRect().width),
        columns: getComputedStyle(tray).gridTemplateColumns,
        rows,
        buttons: tiles.slice(0,2).flatMap(t => [...t.querySelectorAll('.exhibit-ops button')].map(btn => ({
          text: btn.innerText.replace(/\\n/g,'|'),
          w: Math.round(btn.getBoundingClientRect().width),
          h: Math.round(btn.getBoundingClientRect().height),
          whiteSpace: getComputedStyle(btn).whiteSpace,
        }))),
      };
    }""")
    print(json.dumps(data, ensure_ascii=False, indent=1))
    b.close()
