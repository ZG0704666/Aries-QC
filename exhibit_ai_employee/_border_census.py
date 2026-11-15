# -*- coding: utf-8 -*-
"""一次性量尺：谁在贡献边框和背景（按 class 归因）。

目标不是知道「有多少种边框」，而是知道「是哪几个组件在堆视觉噪声」——
只有归因到 class，才能决定拆哪几个，而不是全站调色。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("BORDER_PORT", "4192"))
TMP = tempfile.mkdtemp(prefix="border_")
db = os.path.join(TMP, "studio.sqlite3")
audio = os.path.join(TMP, "audio")


def clean_env():
    env = dict(os.environ)
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        env.pop(key, None)
    return env


def main():
    fx = subprocess.run([sys.executable, "_fixture.py", db, audio, "brd01"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=clean_env())
    if fx.returncode != 0:
        raise SystemExit("夹具失败：" + (fx.stderr or "")[-600:])
    env = clean_env()
    env.update({"STUDIO_DB": db, "STUDIO_AUDIO_DIR": audio,
                "STUDIO_HOST": "127.0.0.1", "STUDIO_PORT": str(PORT)})
    log = open(os.path.join("_ui_shots", "border-server.log"), "w", encoding="utf-8")
    server = subprocess.Popen([sys.executable, "studio_server.py"], env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:%d" % PORT
    try:
        for _ in range(80):
            try:
                urllib.request.urlopen(base + "/api/studio/health", timeout=1).read()
                break
            except Exception:
                time.sleep(0.25)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1000)
            tally = {}
            for view in ("project", "live", "content", "tests", "voice", "release", "feedback"):
                page.goto(base + "/#%s" % view, wait_until="domcontentloaded")
                page.wait_for_timeout(600)
                rows = page.evaluate("""() => {
                  const out = [];
                  document.querySelectorAll('#workspace-body *').forEach(el => {
                    const cs = getComputedStyle(el);
                    const sides = ['Top','Right','Bottom','Left'].filter(s =>
                      cs['border'+s+'Width'] !== '0px' && cs['border'+s+'Style'] !== 'none');
                    const bg = cs.backgroundColor;
                    const hasBg = !(bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent');
                    if (sides.length || hasBg) {
                      const cls = (el.className && el.className.toString ? el.className.toString() : '')
                        .split(/\\s+/).filter(Boolean).slice(0, 2).join('.') || el.tagName.toLowerCase();
                      out.push([cls, sides.length, hasBg]);
                    }
                  });
                  return out;
                }""")
                for cls, sides, has_bg in rows:
                    key = (cls, "border" if sides else "", "bg" if has_bg else "")
                    cur = tally.setdefault(key, [0, 0])
                    cur[0] += 1
                    cur[1] += 1 if sides else 0
            top = sorted(tally.items(), key=lambda kv: -kv[1][0])[:18]
            print("%-34s %5s %6s" % ("class", "次数", "带边框"))
            for (cls, _b, _g), (count, bordered) in top:
                print("%-34s %5d %6d" % (cls[:34], count, bordered))
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=6)
        except Exception:
            server.kill()
        log.close()


if __name__ == "__main__":
    os.makedirs("_ui_shots", exist_ok=True)
    main()
