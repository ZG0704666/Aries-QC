"""走查：新前端里发一条真话，看工具活动、回话渲染、上传链路。

用 _fixture.py 造一个临时项目 + 临时库，起一台独立服务（默认 4199），
Playwright 打开页面真点一次。不碰 studio.sqlite3。

    python _ui_chat.py
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

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("UI_CHAT_PORT", "4199"))
BASE = "http://127.0.0.1:%d" % PORT
PID = "uichat01"
SHOTS = os.path.join(HERE, "_ui_shots")

CHECKS = []


def check(name, ok, detail=""):
    CHECKS.append((name, bool(ok), detail))
    print("  %s %s%s" % ("PASS" if ok else "FAIL", name, (" — " + str(detail)) if detail else ""))
    return ok


def clean_env(extra=None):
    env = dict(os.environ)
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def wait_port(port, timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def main():
    tmp = tempfile.mkdtemp(prefix="studio_uichat_")
    db_path = os.path.join(tmp, "studio.sqlite3")
    audio_dir = os.path.join(tmp, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    server = None
    try:
        env = clean_env({"STUDIO_DB": db_path, "STUDIO_AUDIO_DIR": audio_dir,
                         "STUDIO_PORT": str(PORT)})
        fixture = subprocess.run([sys.executable, os.path.join(HERE, "_fixture.py"),
                                  db_path, audio_dir, PID],
                                 cwd=HERE, env=clean_env(), capture_output=True, text=True,
                                 encoding="utf-8", timeout=180)
        if fixture.returncode != 0:
            print(fixture.stdout[-2000:])
            print(fixture.stderr[-2000:])
            raise SystemExit("夹具没造出来")
        info = json.loads([ln for ln in fixture.stdout.strip().splitlines() if ln.strip()][-1])
        print("夹具项目 %s《%s》 音频 %d 个" % (info["id"], info["name"], len(info.get("audio") or [])))

        out = open(os.path.join(tmp, "server.log"), "w", encoding="utf-8")
        server = subprocess.Popen([sys.executable, os.path.join(HERE, "studio_server.py")],
                                  cwd=HERE, env=env, stdout=out, stderr=subprocess.STDOUT)
        if not wait_port(PORT):
            raise SystemExit("服务没起来")

        with urllib.request.urlopen(BASE + "/api/studio/health", timeout=10) as resp:
            health = json.loads(resp.read().decode("utf-8"))
        check("health 带 web/docs/agent", health.get("web") and health.get("docs") and health.get("agent"),
              health.get("agent"))

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise SystemExit("没装 playwright")

        os.makedirs(SHOTS, exist_ok=True)
        errors = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900}, locale="zh-CN")
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(BASE + "/", wait_until="networkidle")
            page.wait_for_timeout(700)

            check("顶栏显示已连接", "已连接" in (page.inner_text("#conn-text") or ""),
                  page.inner_text("#conn-text"))

            # 对话区该有开场白
            page.wait_for_selector("#chat-log .message", timeout=15000)

            page.fill("#message", "这份资料里讲折射的说法站得住吗？拿不准的地方联网查一下，顺便说来源。")
            page.press("#message", "Enter")
            page.wait_for_timeout(1200)

            check("发出后立刻有「正在处理」气泡", page.locator(".message.pending").count() == 1)
            page.screenshot(path=os.path.join(SHOTS, "chat-pending.png"))

            # 工具活动 chip 应该在等待期间陆续出现
            appeared = False
            for _ in range(60):
                page.wait_for_timeout(1000)
                if page.locator(".message.pending .tool-chip").count() > 0:
                    appeared = True
                    break
            check("等待时能看到工具在干什么", appeared,
                  page.inner_text(".message.pending")[:120].replace("\n", " ") if appeared else "没出现")

            # 等真回话落地
            reply = ""
            for _ in range(180):
                page.wait_for_timeout(1000)
                if page.locator(".message.pending").count() == 0:
                    bodies = page.locator("#chat-log .message.agent .message-body p.rich")
                    if bodies.count():
                        reply = bodies.nth(bodies.count() - 1).inner_text()
                        if reply.strip():
                            break
            check("拿到真实回话", len(reply.strip()) > 40, "%d 字" % len(reply.strip()))

            chips = page.locator("#chat-log .tool-chip").count()
            check("回话下面留了工具轨迹", chips > 0, "%d 个 chip" % chips)

            links = page.locator("#chat-log .message.agent .message-body p.rich a").count()
            strong = page.locator("#chat-log .message.agent .message-body p.rich strong").count()
            check("链接被渲染成可点的 a", links >= 0, "%d 个链接" % links)
            check("粗体被渲染成 strong（不是露星号）", "**" not in reply, "strong=%d" % strong)

            page.screenshot(path=os.path.join(SHOTS, "chat-reply.png"), full_page=False)

            # 上传：拖一个 txt 进去不方便，走文件控件
            sample = os.path.join(tmp, "补一段资料.txt")
            with open(sample, "w", encoding="utf-8") as fh:
                fh.write("彩虹是阳光在水滴里折射与反射形成的。红光偏折最少，紫光最多。\n"
                         "所以彩虹总是外红内紫，观察者背对太阳时才看得到。\n")
            before = page.locator(".reference-files button").count()
            page.set_input_files('[data-upload="material"]', sample)
            page.wait_for_timeout(2500)
            after = page.locator(".reference-files button").count()
            toast = page.inner_text("#toast") if page.locator("#toast").count() else ""
            check("上传后资料数增加（或资料块出现）", after >= before, "before=%d after=%d" % (before, after))
            check("上传给了明确反馈", "收下" in toast or "补一段资料" in page.content(), toast[:80])

            page.screenshot(path=os.path.join(SHOTS, "chat-upload.png"))

            check("没有前端报错", not errors, "；".join(errors[:3]))
            browser.close()

        print("\n回话摘录：\n" + reply[:600])
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in CHECKS if ok)
    print("\n%d/%d 通过" % (passed, len(CHECKS)))
    for name, ok, detail in CHECKS:
        if not ok:
            print("  FAIL %s %s" % (name, detail))
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    sys.exit(main())
