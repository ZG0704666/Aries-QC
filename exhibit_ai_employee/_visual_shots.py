# -*- coding: utf-8 -*-
"""视觉走查截图：把真实 4182 的七个视图逐屏截下来，供人（或带视觉的模型）看图。

    python _visual_shots.py [port] [full|viewport]
默认 1440x900 视口截图；full 则截整页长图。
"""
import io
import os
import sys

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4182
FULL = len(sys.argv) > 2 and sys.argv[2] == "full"
BASE = "http://127.0.0.1:%d/" % PORT
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ui_shots")
VIEWS = ["project", "live", "content", "tests", "voice", "release", "feedback"]


def main():
    os.makedirs(SHOTS, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1400)
        for view in VIEWS:
            page.evaluate("v => location.hash = '#' + v", view)
            page.wait_for_timeout(700)
            suffix = "full" if FULL else "view"
            path = os.path.join(SHOTS, "vis-%s-%s.png" % (view, suffix))
            page.screenshot(path=path, full_page=FULL)
            print("saved", path)
        browser.close()


if __name__ == "__main__":
    main()
