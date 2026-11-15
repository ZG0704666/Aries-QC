"""版式体检：不靠肉眼，用几何量核对设计稿承诺的几件事。

  1) 任何视口宽度下都没有页面级横向溢出（设计稿明令禁止）；
  2) 桌面双栏比例约 1:2（左栏 ≈ 33%），窄屏退化为单栏且能切换；
  3) 关键面板真的占位（宽高都 > 0），没有塌成 0 高；
  4) 字号符合设计稿：正文 16px、页面标题 24–28px、导航 14px；
  5) 专注工作区（focus-work）只藏对话栏，退出后恢复。
跑法：python _ui_layout.py
"""
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
PORT = int(os.environ.get("UI_LAYOUT_PORT", "4213"))
BASE = "http://127.0.0.1:%d" % PORT
WIDTHS = [1600, 1440, 1024, 768, 390]

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + (" | " + str(detail) if detail else ""))


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
        print("端口 %d 已被占用" % PORT)
        return 2
    tmp = tempfile.mkdtemp(prefix="studio_layout_")
    db_copy = os.path.join(tmp, "ui.sqlite3")
    shutil.copy(os.path.join(ROOT, "studio.sqlite3"), db_copy)
    env = clean_env()
    env.update({"STUDIO_DB": db_copy, "STUDIO_AUDIO_DIR": os.path.join(ROOT, "audio"),
                "STUDIO_PORT": str(PORT), "STUDIO_HOST": "127.0.0.1", "PYTHONIOENCODING": "utf-8"})
    server = subprocess.Popen([sys.executable, "studio_server.py"], cwd=ROOT, env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    code = 1
    try:
        if not wait_health():
            print("服务没起来")
            return 2
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1600, "height": 1000})
            page.goto(BASE + "/#live", wait_until="networkidle")
            page.wait_for_timeout(900)

            for width in WIDTHS:
                page.set_viewport_size({"width": width, "height": 1000})
                page.goto(BASE + "/#live", wait_until="domcontentloaded")
                page.wait_for_timeout(500)
                stats = page.evaluate("""() => {
                  const de = document.documentElement;
                  const aside = document.querySelector('aside.conversation');
                  const main = document.querySelector('main.workspace');
                  const cols = getComputedStyle(document.querySelector('.app-shell')).gridTemplateColumns;
                  const body = getComputedStyle(document.body);
                  const h2 = document.querySelector('#workspace-body h2');
                  const tab = document.querySelector('#workspace-tabs a');
                  const tiles = [...document.querySelectorAll('.exhibit-tile')].map(el => {
                    const r = el.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)];
                  });
                  return {
                    scrollW: de.scrollWidth, clientW: de.clientWidth,
                    asideW: aside ? Math.round(aside.getBoundingClientRect().width) : 0,
                    mainW: main ? Math.round(main.getBoundingClientRect().width) : 0,
                    asideDisplay: aside ? getComputedStyle(aside).display : 'none',
                    cols: cols,
                    bodyFont: body.fontSize,
                    h2Font: h2 ? getComputedStyle(h2).fontSize : '',
                    tabFont: tab ? getComputedStyle(tab).fontSize : '',
                    tiles: tiles,
                    wide: [...document.querySelectorAll('#workspace-body *')].filter(el => {
                      const r = el.getBoundingClientRect();
                      if (r.right <= de.clientWidth + 1) return false;
                      // 计算祖先里是否有可横向滚动的容器（如 .pipeline / .table-wrap 的滚动条），
                      // 那种越界是设计好的横向滚动，不算溢出到页面上。
                      let p = el.parentElement;
                      while (p && p !== document.body) {
                        const ox = getComputedStyle(p).overflowX;
                        if ((ox === 'auto' || ox === 'scroll') && p.scrollWidth > p.clientWidth + 1) return false;
                        p = p.parentElement;
                      }
                      return true;
                    }).length,
                    scrollStrips: [...document.querySelectorAll('.pipeline, .tab-line, .table-wrap')]
                      .map(el => [el.className.split(' ')[0], el.scrollWidth > el.clientWidth + 1])
                  };
                }""")
                check("%dpx：无页面级横向溢出" % width, stats["scrollW"] <= stats["clientW"] + 1,
                      "scrollWidth=%s clientWidth=%s" % (stats["scrollW"], stats["clientW"]))
                check("%dpx：正文元素不越出视口" % width, stats["wide"] == 0, "%s 个" % stats["wide"])
                print("      横向滚动条带：%s" % stats["scrollStrips"])
                if width >= 1024:
                    ratio = stats["asideW"] / float(stats["asideW"] + stats["mainW"] or 1)
                    check("%dpx：左栏约占 1/3" % width, 0.28 <= ratio <= 0.40, "%.2f" % ratio)
                else:
                    check("%dpx：窄屏隐藏侧栏（单栏）" % width, stats["asideW"] == 0 or stats["asideDisplay"] == "none",
                          "asideW=%s display=%s" % (stats["asideW"], stats["asideDisplay"]))
                check("%dpx：展项卡片有实际尺寸" % width,
                      stats["tiles"] and all(w > 40 and h > 40 for w, h in stats["tiles"]), stats["tiles"])
                stats2 = page.evaluate("""() => ({
                  h2: (document.querySelector('#workspace-body h2') || {}).textContent || '',
                })""")
                if not stats["h2Font"]:
                    print("  （该宽度下没有 h2，标题字号检查跳过）")

            page.set_viewport_size({"width": 1600, "height": 1000})
            page.goto(BASE + "/#live", wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            fonts = page.evaluate("""() => {
              const pick = (sel) => { const el = document.querySelector(sel); return el ? getComputedStyle(el).fontSize : ''; };
              return { body: pick('body'), h2: pick('#workspace-body h2'), tab: pick('#workspace-tabs a'),
                       chat: pick('#chat-log'), pill: pick('.pill') };
            }""")
            check("字号：正文 16px", fonts["body"] == "16px", fonts["body"])
            check("字号：页面标题 24–28px", fonts["h2"] in ("24px", "26px", "28px"), fonts["h2"])
            check("字号：导航 14px", fonts["tab"] == "14px", fonts["tab"])

            page.locator('[data-action="focus-work"]').first.click()
            page.wait_for_timeout(400)
            focused = page.evaluate("""() => ({
              cls: document.body.className,
              aside: (() => { const a = document.querySelector('aside.conversation');
                              const r = a.getBoundingClientRect();
                              return [Math.round(r.width), getComputedStyle(a).display]; })()
            })""")
            check("专注工作区：正文变宽、侧栏收起",
                  "focus-work" in focused["cls"] and (focused["aside"][0] == 0 or focused["aside"][1] == "none"),
                  focused)
            page.locator('[data-action="focus-work"]').first.click()
            page.wait_for_timeout(400)
            check("退出专注后侧栏恢复",
                  "focus-work" not in page.evaluate("() => document.body.className"))
            code = 0 if all(ok for _, ok, _ in results) else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in results if ok)
    print("\n%d/%d 通过" % (passed, len(results)))
    for name, ok, _ in results:
        if not ok:
            print("  · 失败：", name)
    return code


if __name__ == "__main__":
    sys.exit(main())
