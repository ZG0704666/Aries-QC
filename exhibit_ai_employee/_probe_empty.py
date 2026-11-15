# -*- coding: utf-8 -*-
"""空库起步的走查：没有任何示例项目 → 建档引导 → 建档 → 七视图空态 → 删除 → 回到引导。

自带一台空库服务（默认 4198），不碰 studio.sqlite3，也不依赖真实库是不是空的。

    python _probe_empty.py
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

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("EMPTY_PORT", "4198"))
BASE = "http://127.0.0.1:%d" % PORT
NAME = "空库验证项目"
SHOTS = os.path.join(HERE, "_ui_shots")

ok = 0
bad = 0


def check(label, condition, extra=""):
    global ok, bad
    if condition:
        ok += 1
        print("PASS", label, extra)
    else:
        bad += 1
        print("FAIL", label, extra)


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
    tmp = tempfile.mkdtemp(prefix="studio_empty_")
    db_path = os.path.join(tmp, "studio.sqlite3")
    audio_dir = os.path.join(tmp, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    os.makedirs(SHOTS, exist_ok=True)
    server = None
    try:
        env = clean_env({"STUDIO_DB": db_path, "STUDIO_AUDIO_DIR": audio_dir, "STUDIO_PORT": str(PORT)})
        log = open(os.path.join(tmp, "server.log"), "w", encoding="utf-8")
        server = subprocess.Popen([sys.executable, os.path.join(HERE, "studio_server.py")],
                                  cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
        if not wait_port(PORT):
            raise SystemExit("服务没起来")
        with urllib.request.urlopen(BASE + "/api/studio/projects", timeout=10) as resp:
            check("空库返回空项目列表", json.loads(resp.read().decode("utf-8")).get("projects") == [])

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1080}, locale="zh-CN")
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append("console:" + m.text) if m.type == "error" else None)

            page.goto(BASE, wait_until="networkidle")
            page.wait_for_timeout(700)

            check("连接状态", "已连接" in page.inner_text("#conn-text"), page.inner_text("#conn-text"))
            check("顶栏没有项目名", "还没有项目" in page.inner_text("#project-switch"), page.inner_text("#project-switch"))
            check("上下文芯片无项目", "无项目" in page.inner_text("#context-chips"), page.inner_text("#context-chips"))
            check("正文给建档引导", page.locator('input[name="name"]').count() == 1)
            check("引导里写明不预置示例", "不预置任何示例内容" in page.inner_text("#workspace-body"))
            page.screenshot(path=os.path.join(SHOTS, "empty-before.png"), full_page=True)

            # 建档
            page.fill('input[name="name"]', NAME)
            page.fill('input[name="audience"]', "内部验证")
            page.click('form[data-form="new-project"] button[type="submit"]')
            page.wait_for_timeout(1200)
            check("建档后顶栏显示项目名", NAME in page.inner_text("#project-switch"), page.inner_text("#project-switch"))

            page.evaluate("() => { location.hash = 'project'; }")
            page.wait_for_timeout(450)
            body = page.inner_text("#workspace-body")
            check("项目页提示还没有内容依据", "这个项目还没有内容依据" in body)

            page.evaluate("() => { location.hash = 'content'; }")
            page.wait_for_timeout(450)
            body = page.inner_text("#workspace-body")
            check("内容成果页给两条路", "两条路，选一条" in body and "让它先联网调研" in body)
            check("内容成果页给导入入口", page.locator('[data-upload="material"]').count() >= 1)
            check("内容成果页给授权表单", page.locator('form[data-form="authorize"]').count() == 1)

            # 七视图空态
            for view, label in [("project", "项目与报价"), ("live", "执行现场"), ("content", "内容成果"),
                                ("tests", "测试审核"), ("voice", "语音终端"), ("release", "发布验收"),
                                ("feedback", "反馈改进")]:
                page.evaluate("(v) => { location.hash = v; }", view)
                page.wait_for_timeout(450)
                text = page.inner_text("#workspace-body")
                active = page.locator("#workspace-tabs a.active").inner_text()
                check("视图 %s 渲染" % view,
                      active.strip() == label and len(text) > 100 and "undefined" not in text and "NaN" not in text
                      and "[object Object]" not in text, "active=%s len=%d" % (active.strip(), len(text)))
                check("视图 %s 不出现演示项目名" % view, "光与声音探索展" not in text and "光的折射" not in text)
            page.screenshot(path=os.path.join(SHOTS, "empty-after-create.png"), full_page=True)

            # 没有依据时：页面不给生成按钮，明确给两条路
            page.evaluate("() => { location.hash = 'live'; }")
            page.wait_for_timeout(450)
            live = page.inner_text("#workspace-body")
            check("无依据时执行现场不给生成按钮", page.locator('[data-action="run"]').count() == 0)
            check("无依据时执行现场给出两条路",
                  "还没有内容依据" in live and "去导入资料" in live and "让它先调研" in live)
            check("无依据时页面不承诺调用模型", "共 0 次" not in live)

            # 删除
            page.click("#project-switch")
            page.wait_for_timeout(400)
            check("项目对话框有新建入口", page.locator('[data-action="new-project"]').count() >= 1)
            check("项目对话框有删除入口", page.locator('[data-action="delete-project"]').count() == 1)
            page.click('[data-action="delete-project"]')
            page.wait_for_timeout(400)
            check("删除对话框写明会删掉什么", "这个操作会删掉" in page.inner_text("#dialog-body"))
            page.click('[data-action="delete-project-yes"]')
            page.wait_for_timeout(1200)
            check("删除后回到建档引导", page.locator('input[name="name"]').count() == 1)
            check("删除后顶栏没有项目", "还没有项目" in page.inner_text("#project-switch"))
            page.screenshot(path=os.path.join(SHOTS, "empty-after-delete.png"), full_page=True)

            check("零 console / page 错误", not errors, errors[:3])
            browser.close()
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d 项通过，%d 项失败" % (ok, bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
