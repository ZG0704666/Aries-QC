# -*- coding: utf-8 -*-
"""一次性量尺：每个视图里有几个「填充式主按钮」。

设计规则 primary-action 要求一屏只有一处主行动；如果一屏里有两个以上填充强调按钮，
用户就不知道该先点哪个 —— 这是「杂乱」最直接的来源，比颜色数量更影响观感。
"""
import json
import os
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

PORT = int(os.environ.get("PRIMARY_PORT", "4193"))
TMP = tempfile.mkdtemp(prefix="primary_")
db = os.path.join(TMP, "studio.sqlite3")
audio = os.path.join(TMP, "audio")


def clean_env():
    env = dict(os.environ)
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        env.pop(key, None)
    return env


def main():
    fixture = subprocess.run(
        [sys.executable, "_fixture.py", db, audio, "prime01"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=clean_env())
    if fixture.returncode != 0:
        raise SystemExit("夹具失败：" + (fixture.stderr or "")[-800:])
    info = json.loads(fixture.stdout.strip().splitlines()[-1])

    env = clean_env()
    env["STUDIO_DB"] = db
    env["STUDIO_AUDIO_DIR"] = audio
    env["STUDIO_HOST"] = "127.0.0.1"
    env["STUDIO_PORT"] = str(PORT)
    log = open(os.path.join("_ui_shots", "primary-server.log"), "w", encoding="utf-8")
    server = subprocess.Popen([sys.executable, "studio_server.py"], env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    base = "http://127.0.0.1:%d" % PORT
    try:
        for _ in range(80):
            try:
                import urllib.request
                urllib.request.urlopen(base + "/api/studio/health", timeout=1).read()
                break
            except Exception:
                import time
                time.sleep(0.25)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base + "/", wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            for view in ("project", "live", "content", "tests", "voice", "release", "feedback"):
                page.goto(base + "/#%s" % view, wait_until="domcontentloaded")
                page.wait_for_timeout(700)
                found = page.evaluate("""() => {
                  const out = [];
                  document.querySelectorAll('#workspace-body button, #workspace-body .button, #workspace-body a.button').forEach(el => {
                    const cs = getComputedStyle(el);
                    const bright = cs.backgroundColor;
                    const isFill = !bright.includes('rgba(0, 0, 0, 0)') && !bright.includes('rgb(255, 255, 255)');
                    if (isFill) out.push((el.textContent || '').trim().slice(0, 18) + ' | ' + bright);
                  });
                  return out;
                }""")
                print("%-9s 填充按钮 %d：%s" % (view, len(found), " / ".join(found) or "无"))
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
