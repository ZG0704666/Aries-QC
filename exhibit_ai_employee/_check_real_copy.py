# -*- coding: utf-8 -*-
"""对真实项目页面做一次「还有没有说明文字」的体检。

走真实服务（默认 4182、真实 studio.sqlite3），不写任何数据：
逐视图收集 .subtle / .notice / .small.muted / .section-note 里的文字，
把长度 >= 48 字（说明性长句的特征）的挑出来给人看。

    python _check_real_copy.py
"""

import io
import os
import sys

from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE = os.environ.get("REAL_BASE", "http://127.0.0.1:4182")
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ui_shots")
VIEWS = ["project", "live", "content", "tests", "voice", "release", "feedback"]
PICK = ".subtle, .notice, .small.muted, .section-note, .composer-caption"


def main():
    os.makedirs(SHOTS, exist_ok=True)
    long_hits = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_timeout(1200)
        name = page.eval_on_selector("body", "el => el.innerText.slice(0, 80)")
        print("首屏:", name.replace("\n", " / "))

        for view in VIEWS:
            page.click('a[href="#%s"]' % view)
            page.wait_for_timeout(500)
            items = page.eval_on_selector_all(
                PICK,
                """els => els.filter(e => e.offsetParent !== null)
                        .map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim())
                        .filter(t => t.length)""",
            )
            for text in items:
                mark = "LONG" if len(text) >= 48 else "ok  "
                print("%s %-8s %2d 字 %s" % (mark, view, len(text), text[:90]))
                if len(text) >= 48:
                    long_hits.append((view, text))
            page.screenshot(path=os.path.join(SHOTS, "copy-%s.png" % view), full_page=False)

        browser.close()

    print()
    print("长句（>=48 字）%d 条" % len(long_hits))
    print("console 错误:", errors)
    return 0 if not long_hits else 1


if __name__ == "__main__":
    sys.exit(main())
