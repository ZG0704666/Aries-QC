"""端到端走查（经典工作台 /classic）：按 studio_classic.html 的真实选择器，
验证定位原文、知识卡、自测、审核、试听的链路。

新前端（studio_web.html + assets/app.js）的走查在 _ui_checks.py / _ui_layout.py。

本脚本自带夹具：临时库 + 临时音频目录 + 自己起的服务（默认端口 4214），
不依赖本机有没有项目，也不往真实 studio.sqlite3 写任何东西。
"""
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

ROOT = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("E2E_PORT", "4214"))
BASE = "http://127.0.0.1:%d" % PORT


def api(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def free_port(port):
    sock = socket.socket()
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def clean_env():
    env = dict(os.environ)
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        env.pop(key, None)
    return env


def wait_health(timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/api/studio/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main():
    if not free_port(PORT):
        print("端口 %d 已被占用，先停掉再用" % PORT)
        return 2
    tmp = tempfile.mkdtemp(prefix="studio_e2e_")
    db_path = os.path.join(tmp, "e2e.sqlite3")
    audio_dir = os.path.join(tmp, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    built = subprocess.run([sys.executable, "_fixture.py", db_path, audio_dir, "e2efix01"],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if built.returncode != 0:
        print("夹具建不起来：\n" + (built.stderr or ""))
        return 2
    project = json.loads(built.stdout.strip().splitlines()[-1])
    print("fixture:", project["id"], project["status"], "展项", len(project["titles"]))

    env = clean_env()
    env.update({"STUDIO_DB": db_path, "STUDIO_AUDIO_DIR": audio_dir, "STUDIO_PORT": str(PORT),
                "STUDIO_HOST": "127.0.0.1", "PYTHONIOENCODING": "utf-8"})
    server = subprocess.Popen([sys.executable, "studio_server.py"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    browser = None
    try:
        if not wait_health():
            print("服务没起来（端口 %d）" % PORT)
            return 2
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1100}, device_scale_factor=2)
            errors = []
            page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
            page.goto(BASE + "/classic", wait_until="networkidle")
            page.wait_for_timeout(2000)

            print("mode:", page.inner_text("#modeText"))
            print("sceneMeta:", page.inner_text("#sceneMeta")[:120].replace("\n", " | "))
            print("projectName:", page.inner_text("#projectName"))
            print("steps:", page.inner_text("#steps")[:200].replace("\n", " / "))

            # 1 定位原文（首条事实上的按钮）
            print("locate buttons:", page.locator('button[data-act="locate"]').count())
            if page.locator('button[data-act="locate"]').count():
                page.locator('button[data-act="locate"]').first.click()
                page.wait_for_timeout(400)
                print("locate visible:", page.is_visible("#locateBox"))
                print("locate head:", page.inner_text("#locateHead"))
                print("locate match:", page.inner_text("#locateMatch"))
                print("highlighted:", page.locator("#locateText mark").count())
                page.screenshot(path=os.path.join(ROOT, "_ui_shots", "classic-locate.png"))
                page.click("#locateClose")
                page.wait_for_timeout(200)
                print("locate closed:", not page.is_visible("#locateBox"))

            # 2 知识卡视图
            page.click('#viewTabs button[data-view="facts"]')
            page.wait_for_timeout(300)
            print("fact cards:", page.locator("#contentBody .fact").count())

            # 3 自测
            page.click('.tab[data-panel="review"]')
            page.wait_for_timeout(400)
            print("approve disabled before tests:", page.get_attribute("#approveBtn", "disabled") is not None)
            page.click("#runTests")
            page.wait_for_timeout(1800)
            print("test rows:", page.locator("#testList .test-row").count())
            print("test summary:", page.inner_text("#testSummary"))
            print("approve disabled after tests:", page.get_attribute("#approveBtn", "disabled") is not None)
            page.screenshot(path=os.path.join(ROOT, "_ui_shots", "classic-review.png"), full_page=True)

            # 4 试听状态（音频走 /api/studio/projects/<id>/audio/<file>）
            if page.locator('.tab[data-panel="voice"]').count():
                page.click('.tab[data-panel="voice"]')
            page.wait_for_timeout(300)
            print("voiceText 长度:", len(page.inner_text("#voiceText")))
            print("voiceState:", page.inner_text("#voiceState"))

            page.screenshot(path=os.path.join(ROOT, "_ui_shots", "classic-e2e.png"), full_page=True)
            real = [e for e in errors if "favicon" not in e]
            print("errors:", real[:8])
            return 0 if not real else 1
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
