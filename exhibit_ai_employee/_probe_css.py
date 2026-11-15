# -*- coding: utf-8 -*-
"""确认浏览器拿到的 studio.css 就是磁盘上那份，并列出 summary::before 的全部命中规则。"""
import json
from playwright.sync_api import sync_playwright

ORIGIN = "http://127.0.0.1:4182"
with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, bypass_csp=True)
    page = ctx.new_page()
    page.route("**/assets/studio.css*", lambda route: route.continue_())
    page.goto(f"{ORIGIN}/?project=6dd33d23da", wait_until="networkidle")
    page.wait_for_timeout(500)
    page.evaluate("location.hash='#release'")
    page.wait_for_timeout(600)
    out = page.evaluate("""async () => {
      const resp = await fetch('/assets/studio.css', {cache: 'no-store'});
      const text = await resp.text();
      const s = document.querySelector('.file-tree summary');
      const bef = getComputedStyle(s, '::before');
      const hits = [];
      for (const sheet of document.styleSheets) {
        let rules;
        try { rules = sheet.cssRules; } catch (e) { continue; }
        for (const r of rules) {
          if (!r.selectorText) continue;
          if (r.selectorText.includes('summary') && r.selectorText.includes('before')) {
            hits.push({sheet: sheet.href, sel: r.selectorText,
                       content: r.style.content || null,
                       display: r.style.display || null});
          }
        }
      }
      return {servedHasSpin: text.includes('ds-spin'),
              servedHasGuard: text.includes('details.file-tree>summary'),
              beforeContent: bef.content,
              beforeBorderLeft: bef.borderLeftColor,
              hits};
    }""")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    b.close()
