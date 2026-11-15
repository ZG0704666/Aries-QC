# -*- coding: utf-8 -*-
"""给各个视图做一次「样式值普查」：把字号 / 文字色 / 背景色 / 边框色按出现次数排序。

目的：杂乱感的根源是取值太多。先数清楚有多少个不同取值、各自用了多少次，
再决定收敛到哪几个语义 token，而不是凭感觉改。
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
PORT = int(os.environ.get("CENSUS_PORT", "4194"))

JS = r"""
() => {
  const vis = (el) => {
    const st = getComputedStyle(el), r = el.getBoundingClientRect();
    if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) return false;
    return r.width >= 2 && r.height >= 2;
  };
  const bump = (m, k) => { if (!k) return; m[k] = (m[k] || 0) + 1; };
  const fonts = {}, colors = {}, bgs = {}, borders = {};
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el)) continue;
    const st = getComputedStyle(el);
    if ((el.childElementCount === 0 && el.textContent.trim()) || ['H1','H2','H3','H4','P','LI','SPAN','STRONG','TD','TH','BUTTON','LABEL','Q','SMALL'].includes(el.tagName)) {
      if (el.textContent.trim()) { bump(fonts, st.fontSize); bump(colors, st.color); }
    }
    const bg = st.backgroundColor;
    if (bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') bump(bgs, bg);
    const bw = parseFloat(st.borderTopWidth), bbw = parseFloat(st.borderBottomWidth);
    if (bw > 0) bump(borders, 'top ' + st.borderTopWidth + ' ' + st.borderTopStyle + ' ' + st.borderTopColor);
    if (bbw > 0) bump(borders, 'bottom ' + st.borderBottomWidth + ' ' + st.borderBottomStyle + ' ' + st.borderBottomColor);
  }
  const top = (m, n) => Object.entries(m).sort((a, b) => b[1] - a[1]).slice(0, n);
  return { fonts: top(fonts, 20), colors: top(colors, 24), bgs: top(bgs, 16), borders: top(borders, 16) };
}
"""


def clean_env():
    env = dict(os.environ)
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        env.pop(key, None)
    return env


def main():
    tmp = tempfile.mkdtemp(prefix="census_")
    db = os.path.join(tmp, "studio.sqlite3")
    audio = os.path.join(tmp, "audio")
    subprocess.run([sys.executable, os.path.join(BASE, "_fixture.py"), db, audio, "census01"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=BASE, env=clean_env())
    env = clean_env()
    env.update({"STUDIO_DB": db, "STUDIO_AUDIO_DIR": audio, "STUDIO_PORT": str(PORT)})
    log = open(os.path.join(BASE, "_census_server.log"), "w", encoding="utf-8")
    server = subprocess.Popen([sys.executable, "studio_server.py"], cwd=BASE, env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:%d" % PORT
    for _ in range(80):
        try:
            urllib.request.urlopen(base + "/api/studio/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.25)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            merged = {"fonts": {}, "colors": {}, "bgs": {}, "borders": {}}
            for view in ("project", "live", "content", "tests", "voice", "release", "feedback"):
                page.goto(base + "/#project", wait_until="networkidle")
                page.evaluate("v => { location.hash = '#' + v; }", view)
                page.wait_for_timeout(600)
                data = page.evaluate(JS)
                for key in merged:
                    for value, count in data[key]:
                        merged[key][value] = merged[key].get(value, 0) + count
            for key, title in (("fonts", "字号"), ("colors", "文字色"), ("bgs", "背景色"), ("borders", "边框")):
                print("\n== %s（共 %d 种）" % (title, len(merged[key])))
                for value, count in sorted(merged[key].items(), key=lambda kv: -kv[1])[:18]:
                    print("   %-58s %d" % (value, count))
            with open(os.path.join(BASE, "_census.json"), "w", encoding="utf-8") as fh:
                json.dump(merged, fh, ensure_ascii=False, indent=2)
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except Exception:
            server.kill()
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
