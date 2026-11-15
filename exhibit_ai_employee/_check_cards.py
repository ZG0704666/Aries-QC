# -*- coding: utf-8 -*-
"""看一眼「空来源」页：两张可选卡片是否真在、够不够大、点了有没有反应。

自带临时空库服务（默认 4196），不碰 studio.sqlite3。

    python _check_cards.py
"""

import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("CARDS_PORT", "4196"))
BASE = "http://127.0.0.1:%d" % PORT
SHOTS = os.path.join(HERE, "_ui_shots")


def free(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def clean_env():
    env = dict(os.environ)
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def main():
    if not free(PORT):
        print("端口 %d 被占用，换个 CARDS_PORT" % PORT)
        return 2
    os.makedirs(SHOTS, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="cards-")
    db = os.path.join(tmp, "studio.sqlite3")
    audio = os.path.join(tmp, "audio")
    env = clean_env()
    env["STUDIO_DB"] = db
    env["STUDIO_AUDIO_DIR"] = audio
    env["STUDIO_PORT"] = str(PORT)
    env["STUDIO_HOST"] = "127.0.0.1"

    log = open(os.path.join(tmp, "server.log"), "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, os.path.join(HERE, "studio_server.py")],
                            cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/studio/health", timeout=1).read()
                break
            except Exception:
                time.sleep(0.3)
        else:
            print("服务没起来")
            return 1

        req = urllib.request.Request(
            BASE + "/api/studio/projects",
            data=json.dumps({"name": "卡片验证", "audience": "亲子观众", "language": "中文"}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        pid = json.loads(urllib.request.urlopen(req, timeout=10).read().decode())["project"]["id"]
        print("建了空项目", pid)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(BASE + "/#content", wait_until="networkidle")
            page.wait_for_timeout(900)

            cards = page.eval_on_selector_all(".choice-card", """els => els.filter(e => e.offsetParent !== null)
                .map(e => {const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                return {text: e.innerText.replace(/\\s+/g, ' ').trim(), w: Math.round(r.width),
                        h: Math.round(r.height), border: s.borderStyle, cursor: s.cursor};})""")
            for card in cards:
                print("卡片:", card)
            left = page.eval_on_selector(".workspace-body", "e => e.scrollWidth <= e.clientWidth + 1")
            page.screenshot(path=os.path.join(SHOTS, "content-empty-cards.png"))
            print("无横向溢出:", left, "| pageerror:", errors)
            browser.close()
        return 0 if len(cards) == 2 and all(c["h"] >= 44 for c in cards) and left and not errors else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:
            proc.kill()
        log.close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
