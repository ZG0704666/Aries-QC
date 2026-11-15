# -*- coding: utf-8 -*-
"""给「项目功能文档」批量截七视图 + 经典工作台。只读，不改任何数据。"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get("SHOT_BASE", "http://127.0.0.1:4182")
OUT = os.path.abspath(os.environ.get("SHOT_OUT", r"D:\怀客松\功能文档\screenshots"))
VIEWS = [
    ("project", "项目与报价"),
    ("live", "执行现场"),
    ("content", "内容成果"),
    ("tests", "测试审核"),
    ("voice", "语音终端"),
    ("release", "发布验收"),
    ("feedback", "反馈改进"),
]

os.makedirs(OUT, exist_ok=True)


def wait_ready(page, extra_ms=900):
    page.wait_for_function(
        """() => {
            const t = document.querySelector('#conn-text');
            if (!t) return false;
            const s = t.textContent || '';
            if (s.indexOf('正在连接') >= 0) return false;
            const body = document.querySelector('#workspace-body');
            return body && body.innerText.trim().length > 0;
        }""",
        timeout=30000,
    )
    page.wait_for_timeout(extra_ms)


with sync_playwright() as p:
    browser = p.chromium.launch(args=["--force-device-scale-factor=1.5"])
    ctx = browser.new_context(viewport={"width": 1680, "height": 1050}, device_scale_factor=1.5)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(BASE + "/#live", wait_until="networkidle")
    wait_ready(page)

    for key, name in VIEWS:
        page.evaluate("(v) => { location.hash = v; }", key)
        page.wait_for_timeout(300)
        wait_ready(page, 700)
        path = os.path.join(OUT, "01-%s-%s.png" % (key, name) if False else "%s.png" % key)
        page.screenshot(path=path, full_page=True)
        info = page.evaluate(
            """() => ({
                title: document.title,
                project: (document.querySelector('#project-switch')||{}).innerText,
                tab: (document.querySelector('#workspace-tabs .active')||{}).innerText,
                body: (document.querySelector('#workspace-body')||{}).innerText.slice(0, 400)
            })"""
        )
        print("[shot]", key, "->", os.path.basename(path), "|", info["tab"], "|", info["project"])
        print("   body:", " / ".join(info["body"].split("\n")[:6])[:300])

    # 经典工作台（回退对照）
    page.goto(BASE + "/classic", wait_until="networkidle")
    page.wait_for_timeout(2500)
    page.screenshot(path=os.path.join(OUT, "classic.png"), full_page=True)
    print("[shot] classic -> classic.png")

    # 空态：新建项目弹窗（只打开，不提交）
    page.goto(BASE + "/#live", wait_until="networkidle")
    wait_ready(page)
    page.click("#project-switch")
    page.wait_for_timeout(800)
    page.screenshot(path=os.path.join(OUT, "project-switch.png"))
    print("[shot] project-switch -> project-switch.png")

    print("JS errors:", errors)
    browser.close()
print("OUT=", OUT)
