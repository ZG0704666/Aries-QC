"""新前端（studio_web.html + assets/app.js）的真实浏览器走查。

跑法：python _ui_checks.py
会起一个临时服务（临时 DB + 真实音频目录的只读引用），用 Chromium 逐视图点击并断言：
  1) 零 pageerror / console error；
  2) 七个视图都渲染出真实数据，且没有 undefined / NaN / [object Object]；
  3) 页面上不出现占位式假数据标记（本地交互演示 / 示例任务 / DEMO 编号 等）；
  4) 关键交互真的打到后端：定位原文高亮、切换展项、运行自测、记录反馈与候选。
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
PORT = int(os.environ.get("UI_CHECK_PORT", "4212"))
BASE = "http://127.0.0.1:%d" % PORT
SHOTS = os.path.join(ROOT, "_ui_shots")
FIXTURE_ID = "uifix01"
FIXTURE_NAME = "走查夹具项目"
FIXTURE_TITLES = ["测试展项一", "测试展项二", "测试展项三"]

FORBIDDEN = ["本地交互演示", "示例任务", "未调用真实", "PRJ-DEMO", "TASK-DEMO",
             "载入示例记录", "示例用例", "演示数据"]
PLACEHOLDER = ["undefined", "NaN", "[object Object]"]
VIEWS = [("project", "项目与报价"), ("live", "执行现场"), ("content", "内容成果"),
         ("tests", "测试审核"), ("voice", "语音终端"), ("release", "发布验收"),
         ("feedback", "反馈改进")]

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(detail) if detail else ""))
    return ok


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
            with urllib.request.urlopen(BASE + "/api/studio/health", timeout=3) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main():
    if not free_port(PORT):
        print("端口 %d 已被占用，先停掉再用" % PORT)
        return 2
    tmp = tempfile.mkdtemp(prefix="studio_ui_")
    db_path = os.path.join(tmp, "ui.sqlite3")
    audio_dir = os.path.join(tmp, "audio")            # 夹具现场合成音频，不碰真实数据
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(SHOTS, exist_ok=True)

    # 夹具项目由 _fixture.py 现场造，不复制真实库（空库起步后本机可能什么都没有）
    built = subprocess.run([sys.executable, "_fixture.py", db_path, audio_dir, FIXTURE_ID],
                           cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if built.returncode != 0:
        print("夹具建不起来：\n" + (built.stderr or ""))
        return 2
    fixture = json.loads(built.stdout.strip().splitlines()[-1])

    env = clean_env()
    env.update({
        "STUDIO_DB": db_path,
        "STUDIO_AUDIO_DIR": audio_dir,
        "STUDIO_PORT": str(PORT),
        "STUDIO_HOST": "127.0.0.1",
        "PYTHONIOENCODING": "utf-8",
    })
    server = subprocess.Popen([sys.executable, "studio_server.py"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    exit_code = 1
    browser = None
    try:
        if not wait_health():
            print("服务没起来（端口 %d）" % PORT)
            return 2
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1080}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
            page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
            page.goto(BASE + "/", wait_until="networkidle")
            page.wait_for_timeout(1200)

            check("顶栏显示已连接真实服务", "已连接" in page.inner_text("#conn-text"),
                  page.inner_text("#conn-text"))
            check("项目切换器读到真实项目名", FIXTURE_NAME in page.inner_text("#project-switch"),
                  page.inner_text("#project-switch"))

            seen_text = {}
            counts = {}
            for view, label in VIEWS:
                page.goto(BASE + "/#%s" % view, wait_until="domcontentloaded")
                page.wait_for_timeout(700)
                body = page.inner_text("#workspace-body")
                seen_text[label] = body
                counts[view] = {"paras": page.locator(".para-list li").count(),
                                "audio": page.locator("audio").count()}
                tab = page.locator("#workspace-tabs a.active")
                check("视图 %s：标签高亮正确" % label,
                      tab.count() == 1 and tab.inner_text().strip() == label,
                      tab.inner_text().strip() if tab.count() else "无")
                check("视图 %s：面板有内容" % label, len(body.strip()) > 200, "%d 字" % len(body))
                bad = [w for w in PLACEHOLDER if w in body]
                check("视图 %s：无占位符泄漏" % label, not bad, bad)
                fake = [w for w in FORBIDDEN if w in body]
                check("视图 %s：无假数据标记" % label, not fake, fake)
                page.screenshot(path=os.path.join(SHOTS, "view-%s.png" % view), full_page=False)

            live = seen_text["执行现场"]
            check("执行现场：三个展项标题都在",
                  all(t in live for t in FIXTURE_TITLES), [t for t in FIXTURE_TITLES if t not in live])
            check("执行现场：真实事件记录条数", "条" in live and "运行事件" in live)

            tests = seen_text["测试审核"]
            for name in ("覆盖完整", "引文逐字可定位", "无跨展项串台", "主讲解时长约 45 秒"):
                check("测试审核：出现真实用例「%s」" % name, name in tests)

            content = seen_text["内容成果"]
            check("内容成果：出现真实来源编号 SRC-001", "SRC-001" in content)
            check("内容成果：暴露原文段落", counts["content"]["paras"] >= 5,
                  counts["content"]["paras"])

            voice = seen_text["语音终端"]
            check("语音终端：三份 MP3 都在", voice.count(".mp3") >= 3, voice.count(".mp3"))
            check("语音终端：写出实测时长窗口", "33.75" in voice.replace(",", "."), )
            check("语音终端：播放器数量", counts["voice"]["audio"] >= 1,
                  counts["voice"]["audio"])

            release = seen_text["发布验收"]
            check("发布验收：交付包列出真实音频文件名",
                  "EX01-breeze" in release and "EX02-breeze" in release and "EX03-breeze" in release)
            check("发布验收：门禁读到审核状态", "人工审核" in release)

            # ---- 交互 1：定位原文高亮 ----
            page.goto(BASE + "/#live", wait_until="domcontentloaded")
            page.wait_for_timeout(600)
            page.locator('[data-action="locate-source"]').first.click()
            page.wait_for_timeout(900)
            check("交互：定位原文跳到内容成果", page.locator("#workspace-tabs a.active").inner_text().strip() == "内容成果",
                  page.locator("#workspace-tabs a.active").inner_text().strip())
            check("交互：命中的段落被高亮", page.locator(".para-list li.hit").count() == 1,
                  page.locator(".para-list li.hit").count())
            page.screenshot(path=os.path.join(SHOTS, "action-locate.png"))

            # ---- 交互 2：切换展项 ----
            page.goto(BASE + "/#live", wait_until="domcontentloaded")
            page.wait_for_timeout(600)
            first_title = page.inner_text(".artifact-heading h3")
            page.locator('[data-action="exhibit"]').nth(2).click()
            page.wait_for_timeout(500)
            third_title = page.inner_text(".artifact-heading h3")
            check("交互：切换展项改变正文", first_title != third_title,
                  first_title.replace("\n", " ") + " → " + third_title.replace("\n", " "))

            # ---- 交互 3：运行真实自测（不打模型，只算规则与 ffprobe） ----
            page.goto(BASE + "/#tests", wait_until="domcontentloaded")
            page.wait_for_timeout(600)
            page.locator('[data-action="run-tests"]').first.click()
            page.wait_for_timeout(2500)
            toast = page.inner_text("#toast")
            check("交互：自测返回真实通过数", "通过" in toast, toast)
            rows = page.locator(".table-wrap tbody tr").count()
            check("交互：自测表格 7 行", rows == 7, rows)

            # ---- 交互 4：记录一条真实反馈 + 登记候选 ----
            page.goto(BASE + "/#feedback", wait_until="domcontentloaded")
            page.wait_for_timeout(700)
            page.fill('form[data-form="feedback"] textarea[name="problem"]', "走查：观众说讲得太快跟不上")
            page.fill('form[data-form="feedback"] input[name="title"]', "走查反馈")
            page.locator('form[data-form="feedback"] button[type="submit"]').click()
            page.wait_for_timeout(1800)
            body = page.inner_text("#workspace-body")
            check("交互：反馈写入并编号 FB-001", "FB-001" in body, page.inner_text("#toast"))
            page.fill('form[data-form="candidate"] textarea[name="suggestion"]', "把两句长句拆成短句，先讲现象再讲原因")
            page.locator('form[data-form="candidate"] button[type="submit"]').click()
            page.wait_for_timeout(1500)
            check("交互：候选可登记", "候选" in page.inner_text("#workspace-body"), page.inner_text("#toast"))
            page.screenshot(path=os.path.join(SHOTS, "action-feedback.png"))

            real_errors = [e for e in errors if "favicon" not in e]
            check("零 JS 错误", not real_errors, real_errors[:4])
            exit_code = 0 if all(ok for _, ok, _ in results) else 1
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

    passed = sum(1 for _, ok, _ in results if ok)
    print("\n%d/%d 通过" % (passed, len(results)))
    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print("失败：")
        for name in failed:
            print("  ·", name)
    print("截图目录：%s" % SHOTS)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
