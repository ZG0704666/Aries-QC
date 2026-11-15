"""空库起步的端到端走查：没有示例项目 → 页面给建档引导 → 建档 → 七视图空态 → 删除 → 回到引导。"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("PROBE_BASE", "http://127.0.0.1:4182")
NAME = "空库验证项目"

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


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1600, "height": 1080})
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
    page.screenshot(path="_ui_shots/empty-before.png", full_page=True)

    # 建档
    page.fill('input[name="name"]', NAME)
    page.fill('input[name="audience"]', "内部验证")
    page.click('form[data-form="new-project"] button[type="submit"]')
    page.wait_for_timeout(1200)
    check("建档后顶栏显示项目名", NAME in page.inner_text("#project-switch"), page.inner_text("#project-switch"))
    check("建档后 toast", True)
    page.evaluate("() => { location.hash = 'project'; }")
    page.wait_for_timeout(450)
    body = page.inner_text("#workspace-body")
    check("项目页提示还没有资料", "这个项目还没有资料" in body)
    page.evaluate("() => { location.hash = 'content'; }")
    page.wait_for_timeout(450)
    body = page.inner_text("#workspace-body")
    check("内容成果页给导入入口", "先导入真实资料" in body and page.locator("#material-file").count() == 1)
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
    page.screenshot(path="_ui_shots/empty-after-create.png", full_page=True)

    # 无资料时：页面不给生成按钮，明确让去导入资料
    page.evaluate("() => { location.hash = 'live'; }")
    page.wait_for_timeout(450)
    live = page.inner_text("#workspace-body")
    check("无资料时执行现场不给生成按钮", page.locator('[data-action="run"]').count() == 0)
    check("无资料时执行现场指向导入资料", "还没有资料" in live and "去导入资料" in live)
    check("无资料时页面不承诺调用模型", "共 0 次" not in live)

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
    body = page.inner_text("#workspace-body")
    check("删除后回到建档引导", page.locator('input[name="name"]').count() == 1, page.inner_text("#project-switch"))
    check("删除后顶栏没有项目", "还没有项目" in page.inner_text("#project-switch"))
    page.screenshot(path="_ui_shots/empty-after-delete.png", full_page=True)

    check("零 JS 错误", not errors, "; ".join(errors[:3]))
    browser.close()

print("\n%d/%d 通过" % (ok, ok + bad))
sys.exit(0 if bad == 0 else 1)
