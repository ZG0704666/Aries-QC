# -*- coding: utf-8 -*-
"""测量各个视图的「杂乱度」：不是靠看图，而是靠 DOM 几何与计算样式。

指标口径：
- boxes     屏幕内带边框/背景的独立块数量（视觉噪声的主要来源）
- borders   不同的边框色数量（颜色越多越碎）
- fonts     不同字号数量（超过 3 档就说明层级没收敛）
- buttons   可见按钮数量 + 其中有几个看起来是「主按钮」
- colors    可见元素上出现的不同文字色 / 背景色数量
- chars     首屏可见文字量（每千平方像素的字数）
- actions   首屏可点元素数（超过 5 个就太挤）
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("AUDIT_PORT", "4195"))


def clean_env():
    env = dict(os.environ)
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        env.pop(key, None)
    return env


JS = r"""
() => {
  const vis = (el) => {
    const st = getComputedStyle(el), r = el.getBoundingClientRect();
    if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) return false;
    if (r.width < 2 || r.height < 2) return false;
    return r.top < window.innerHeight && r.bottom > 0 && r.left < window.innerWidth && r.right > 0;
  };
  const area = window.innerWidth * window.innerHeight;
  const fonts = new Set(), borders = new Set(), colors = new Set(), bgs = new Set();
  let boxes = 0, chars = 0, actions = 0, pills = 0, tables = 0, notes = 0;
  const big = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el)) continue;
    const st = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const bw = parseFloat(st.borderTopWidth) + parseFloat(st.borderLeftWidth);
    const bg = st.backgroundColor;
    const hasBg = bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent';
    const hasBorder = parseFloat(st.borderTopWidth) > 0 || parseFloat(st.borderBottomWidth) > 0;
    if ((hasBg && r.width * r.height > 4000) || (hasBorder && r.width > 40 && r.height > 24)) {
      if (el.tagName !== 'BODY' && el.tagName !== 'HTML' && !el.classList.contains('app-shell')) {
        boxes += 1;
        if (r.width * r.height > 20000) big.push({tag: el.tagName, cls: el.className && el.className.toString().slice(0, 40), area: Math.round(r.width * r.height)});
      }
    }
    if (hasBorder) borders.add(st.borderTopColor + '/' + st.borderTopWidth);
    if (hasBg) bgs.add(bg);
    const text = (el.childElementCount === 0 && el.textContent) ? el.textContent.trim() : '';
    if (text.length) { chars += text.length; fonts.add(st.fontSize); colors.add(st.color); }
    if (el.matches('button, a[href], select, input:not([type=hidden]), label.choice-card, label.file-input, [data-action]')) actions += 1;
    if (el.classList.contains('pill') || el.classList.contains('micro-tag') || el.classList.contains('tag')) pills += 1;
    if (el.classList.contains('table-wrap') || el.tagName === 'TABLE') tables += 1;
    if (el.classList.contains('subtle') || el.classList.contains('notice') || el.classList.contains('small')) notes += 1;
  }
  const main = document.querySelector('.workspace-body');
  const mainChars = main ? main.innerText.replace(/\s+/g, '').length : 0;
  return {
    boxes, borders: borders.size, fonts: fonts.size, colors: colors.size, bgs: bgs.size,
    actions, pills, tables, notes,
    charsPerKpx: Math.round(chars / (area / 1000)),
    mainChars,
    scrolled: main ? main.scrollHeight : 0,
    big: big.sort((a, b) => b.area - a.area).slice(0, 6)
  };
}
"""


def main():
    tmp = tempfile.mkdtemp(prefix="audit_ui_")
    db = os.path.join(tmp, "studio.sqlite3")
    audio = os.path.join(tmp, "audio")
    fixture = subprocess.run([sys.executable, os.path.join(BASE, "_fixture.py"), db, audio, "audit99"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=BASE, env=clean_env())
    if fixture.returncode != 0:
        print(fixture.stderr[-2000:]); return 1
    env = clean_env()
    env["STUDIO_DB"] = db
    env["STUDIO_AUDIO_DIR"] = audio
    env["STUDIO_PORT"] = str(PORT)
    log = open(os.path.join(BASE, "_audit_ui_server.log"), "w", encoding="utf-8")
    server = subprocess.Popen([sys.executable, "studio_server.py"], cwd=BASE, env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:%d" % PORT
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/api/studio/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.25)
    rows = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            for view in ("project", "live", "content", "tests", "voice", "release", "feedback"):
                page.goto(base + "/#project", wait_until="networkidle")
                page.evaluate("v => { location.hash = '#' + v; }", view)
                page.wait_for_timeout(700)
                data = page.evaluate(JS)
                data["view"] = view
                rows.append(data)
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except Exception:
            server.kill()
        log.close()

    print("%-9s %5s %6s %5s %6s %6s %7s %5s %5s %5s %8s %7s" %
          ("view", "boxes", "border", "font", "color", "bg", "chars/K", "act", "pill", "tab", "mainChr", "scroll"))
    for r in rows:
        print("%-9s %5d %6d %5d %6d %6d %7d %5d %5d %5d %8d %7d" %
              (r["view"], r["boxes"], r["borders"], r["fonts"], r["colors"], r["bgs"],
               r["charsPerKpx"], r["actions"], r["pills"], r["tables"], r["mainChars"], r["scrolled"]))
        for b in r["big"][:3]:
            print("           └ %-8s %s  area=%s" % (b["tag"], b["cls"], b["area"]))
    with open(os.path.join(BASE, "_audit_ui.json"), "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
