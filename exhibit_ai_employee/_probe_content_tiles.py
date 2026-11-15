# -*- coding: utf-8 -*-
"""content 屏（宽栏）的瓦片列数。"""
import json
from playwright.sync_api import sync_playwright

ORIGIN = "http://127.0.0.1:4182"
PID = "6dd33d23da"

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto(f"{ORIGIN}/?project={PID}", wait_until="networkidle")
    page.wait_for_timeout(400)
    page.evaluate("location.hash = '#content'")
    page.wait_for_timeout(600)
    data = page.evaluate("""() => {
      const tray = document.querySelector('.exhibit-tray');
      if (!tray) return {none: true};
      const tiles = [...document.querySelectorAll('.exhibit-tile')];
      const rows = {};
      tiles.forEach(t => { const y = Math.round(t.getBoundingClientRect().top); rows[y] = (rows[y]||0)+1; });
      return {
        trayWidth: Math.round(tray.getBoundingClientRect().width),
        columns: getComputedStyle(tray).gridTemplateColumns,
        rows,
        tileHeight: Math.round(tiles[0].getBoundingClientRect().height),
      };
    }""")
    print(json.dumps(data, ensure_ascii=False, indent=1))
    page.screenshot(path="_ui_shots/content-tiles.png")
    b.close()
