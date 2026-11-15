"""只读探针：在真实浏览器里加载线上页面，只看有没有报错、各视图有没有内容。不点任何写操作。"""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:4182/"
VIEWS = ["project", "live", "content", "tests", "voice", "release", "feedback"]

errors = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1000})
    page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
    page.on(
        "console",
        lambda m: errors.append("console: %s" % m.text) if m.type == "error" else None,
    )
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(1200)

    print("conn:", page.inner_text("#conn-text").strip())
    print("project:", page.inner_text("#project-switch").strip())
    print("employee-state:", page.inner_text("#employee-state").strip())
    print("context-chips:", page.inner_text("#context-chips").strip().replace("\n", " / "))

    for view in VIEWS:
        page.evaluate("v => { location.hash = '#/' + v }", view)
        page.wait_for_timeout(500)
        body = page.inner_text("#workspace-body")
        title = page.inner_text("#workspace-body h2") if page.query_selector("#workspace-body h2") else "(无标题)"
        bad = [w for w in ("undefined", "NaN", "[object Object]") if w in body]
        print(
            "%-9s 标题=%-22s 正文%4d 字%s"
            % (view, title.strip()[:22], len(body), ("  ⚠" + ",".join(bad)) if bad else "")
        )

    page.evaluate("() => { location.hash = '#/live' }")
    page.wait_for_timeout(400)
    page.screenshot(path="_ui_shots/live-check.png", full_page=True)
    browser.close()

print("JS 错误：", errors if errors else "无")
