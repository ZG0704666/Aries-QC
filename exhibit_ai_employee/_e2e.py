"""端到端走查：按当前 studio_web.html 的真实选择器，验证定位、知识卡、自测、审核、试听链路。"""
import json
import sys
import urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4182"


def api(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    project = api("/api/studio/seed")["project"] if len(sys.argv) > 1 else None
    if project:
        print("seeded:", project["id"], project["status"], "v%s" % project["version"])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1600, "height": 1100}, device_scale_factor=2)
        errors = []
        page.on("pageerror", lambda e: errors.append("pageerror: " + str(e)))
        page.on("console", lambda m: errors.append("console: " + m.text) if m.type == "error" else None)
        page.goto(BASE + "/", wait_until="networkidle")
        page.wait_for_timeout(2000)

        print("mode:", page.inner_text("#modeText"))
        print("sceneMeta:", page.inner_text("#sceneMeta")[:120].replace("\n", " | "))
        print("projectName:", page.inner_text("#projectName"))
        print("steps:", page.inner_text("#steps")[:200].replace("\n", " / "))

        # 1 定位原文（首条事实上的按钮）
        locate = page.locator('button[data-act="locate"]').first
        print("locate buttons:", page.locator('button[data-act="locate"]').count())
        if page.locator('button[data-act="locate"]').count():
            locate.click()
            page.wait_for_timeout(400)
            print("locate visible:", page.is_visible("#locateBox"))
            print("locate head:", page.inner_text("#locateHead"))
            print("locate match:", page.inner_text("#locateMatch"))
            print("highlighted:", page.locator("#locateText mark").count())
            page.screenshot(path="shot_locate.png")
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
        page.screenshot(path="shot_review.png", full_page=True)

        # 4 试听（浏览器朗读，不产生音频文件）
        page.click('.tab[data-panel="voice"]') if page.locator('.tab[data-panel="voice"]').count() else None
        page.wait_for_timeout(300)
        print("voiceText 长度:", len(page.inner_text("#voiceText")))
        print("voiceState:", page.inner_text("#voiceState"))

        page.screenshot(path="shot_e2e.png", full_page=True)
        print("errors:", errors[:8])
        browser.close()


if __name__ == "__main__":
    main()
