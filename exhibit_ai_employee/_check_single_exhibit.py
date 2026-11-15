# -*- coding: utf-8 -*-
"""单展项独立操作的真实验证：UI 上点「重做」，确认只有那一个展项变了。

不是断言代码存在，是真的驱动浏览器点按钮、等生成、比对前后展项。
"""
import json
import time
import urllib.request
from playwright.sync_api import sync_playwright

ORIGIN = "http://127.0.0.1:4182"
PID = "6dd33d23da"


def project():
    with urllib.request.urlopen(f"{ORIGIN}/api/studio/projects/{PID}", timeout=10) as r:
        return json.load(r)["project"]


def main():
    before = project()
    ex_ids = [e["id"] for e in before.get("exhibits", [])]
    print("展项：", ex_ids)
    target = ex_ids[1] if len(ex_ids) > 1 else ex_ids[0]
    others_before = {e["id"]: (e.get("main") or {}).get("text", "") for e in before["exhibits"] if e["id"] != target}
    print(f"目标：只重做 {target}，其余 {list(others_before)} 应保持不变")

    results = []

    def check(name, ok, detail=""):
        results.append((name, ok, detail))
        print(("PASS " if ok else "FAIL ") + name + ("  " + str(detail) if detail else ""))

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{ORIGIN}/?project={PID}", wait_until="networkidle")
        page.wait_for_timeout(600)

        # 瓦片是 div 了，里面有独立操作按钮
        ops = page.locator(".exhibit-tile .exhibit-ops button[data-action='run-one']")
        check("每个展项都有自己的「重做」按钮", ops.count() == len(ex_ids), f"{ops.count()}/{len(ex_ids)}")
        synths = page.locator(".exhibit-tile .exhibit-ops button[data-action='synth']")
        check("每个展项都有自己的「合成」按钮", synths.count() == len(ex_ids))

        # 标题区仍能切换展项
        page.locator(".exhibit-tile .exhibit-pick").nth(1).click()
        page.wait_for_timeout(400)
        check("点标题区切换展项仍有效", "EX02" in page.locator(".paper-heading").inner_text()
              or "EX02" in page.locator(".artifact-heading").inner_text())

        # 真点「重做」目标展项
        page.on("dialog", lambda d: d.accept())
        page.locator(f".exhibit-tile .exhibit-ops button[data-action='run-one'][data-value='{target}']").click()
        page.wait_for_timeout(1200)
        running = page.locator(".exhibit-tile.is-running")
        check("生成中的瓦片有 is-running 标识", running.count() == 1)

        # 等生成结束（真模型调用，最多 180 秒）
        deadline = time.time() + 180
        done = False
        while time.time() < deadline:
            cur = project()
            if cur.get("status") != "running":
                done = True
                break
            time.sleep(3)
        check("单展项生成在 180 秒内结束", done, f"status={project().get('status')}")

        after = project()
        others_after = {e["id"]: (e.get("main") or {}).get("text", "") for e in after["exhibits"] if e["id"] != target}
        check("其余展项的讲解文本一字未动", others_before == others_after)
        new_target = next((e for e in after["exhibits"] if e["id"] == target), None)
        check("目标展项确实有主讲解", bool(new_target and (new_target.get("main") or {}).get("text")))
        check("版本号前进 0.1", abs(after["version"] - before["version"] - 0.1) < 1e-6,
              f"{before['version']} → {after['version']}")
        check("旧审核签名被清掉（内容变了不能沿用）", after.get("review") is None)
        check("展项总数没变", len(after["exhibits"]) == len(before["exhibits"]))
        check("全程零 JS 错误", not errors, errors[:2])

        page.screenshot(path="_ui_shots/single-exhibit.png")
        b.close()

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n===== 单展项独立操作 {passed}/{len(results)} =====")


if __name__ == "__main__":
    main()
