from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1100}, device_scale_factor=2)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto("http://127.0.0.1:4182/", wait_until="networkidle")
    page.wait_for_timeout(2200)

    before = page.is_visible("#locateBox")
    page.click("button.locate")
    page.wait_for_timeout(400)
    after = page.is_visible("#locateBox")
    head = page.inner_text("#locateHead") if after else "-"
    match = page.inner_text("#locateMatch") if after else "-"
    marked = page.locator("#locateText mark").count()
    print("panel before:", before, "| after:", after)
    print("head:", head)
    print("match:", match)
    print("highlighted chars:", marked)
    page.screenshot(path="shot_locate.png", full_page=False)

    page.click("#locateClose")
    page.wait_for_timeout(200)
    print("closed:", not page.is_visible("#locateBox"))

    # 切到知识卡视图，确认事实列表真实
    page.click('#viewTabs button[data-view="facts"]')
    page.wait_for_timeout(300)
    print("fact cards:", page.locator("#contentBody .fact").count())

    # 测试与审核页
    page.click('.tab[data-panel="review"]')
    page.wait_for_timeout(400)
    print("approve disabled before tests:", page.get_attribute("#approveBtn", "disabled") is not None)
    page.click("#runTests")
    page.wait_for_timeout(1500)
    print("test rows:", page.locator("#testList .test-row").count())
    print("approve disabled after tests:", page.get_attribute("#approveBtn", "disabled") is not None)
    print("summary:", page.inner_text("#testSummary"))
    print("errors:", errors)
    browser.close()
