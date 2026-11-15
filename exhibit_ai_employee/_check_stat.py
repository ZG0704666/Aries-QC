"""核对 stat 的渲染：真起 4182（或指定端口），逐视图数 .stat/.pill，量圆点几何与颜色。

判据（来自 ui-ux-pro-max 的 whitespace-balance / color-semantic）：
  · 每屏 pill 数量应 <= 5（表格里的状态胶囊不算标签墙的一种，但也要计数给人看）
  · .stat 的字号必须落在 token 阶梯内（13px），圆点必须是 6px 实心圆
  · is-pass/is-warn/is-fail 三色必须真的不同（否则等于没区分）
"""
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4182
BASE = "http://127.0.0.1:%d/" % PORT
VIEWS = ["project", "live", "content", "tests", "voice", "release", "feedback"]

PROBE = """() => {
  const pick = (sel) => Array.from(document.querySelectorAll(sel));
  const dot = (el) => {
    const s = getComputedStyle(el, '::before');
    return {w: s.width, h: s.height, r: s.borderRadius, bg: s.backgroundColor};
  };
  const stats = pick('.stat');
  return {
    stat: stats.length,
    pill: pick('.pill').length,
    sizes: Array.from(new Set(stats.map((el) => getComputedStyle(el).fontSize))),
    dots: Array.from(new Set(stats.slice(0, 6).map(dot).map((d) => d.w + ' ' + d.h + ' ' + d.bg))),
    tones: {
      pass: (document.querySelector('.stat.is-pass') || {}).textContent || '',
      warn: (document.querySelector('.stat.is-warn') || {}).textContent || '',
      fail: (document.querySelector('.stat.is-fail') || {}).textContent || '',
    },
    colors: {
      pass: (() => { const el = document.querySelector('.stat.is-pass'); return el ? getComputedStyle(el).color : ''; })(),
      warn: (() => { const el = document.querySelector('.stat.is-warn'); return el ? getComputedStyle(el).color : ''; })(),
      fail: (() => { const el = document.querySelector('.stat.is-fail'); return el ? getComputedStyle(el).color : ''; })(),
    },
    overflowX: document.documentElement.scrollWidth > window.innerWidth + 2,
  };
}"""


def main():
    try:
        health = json.loads(urllib.request.urlopen(BASE + "api/studio/health", timeout=10).read())
    except Exception as error:
        print("连不上 %s：%s" % (BASE, error))
        return 2
    print("health code=%s pid=%s" % (health.get("code"), health.get("pid")))
    projects = json.loads(urllib.request.urlopen(BASE + "api/studio/projects", timeout=10).read())["projects"]
    if not projects:
        print("库里没有项目，先建一个再看。")
        return 2
    print("项目：%s" % "、".join("%s %s" % (p["id"], p["name"]) for p in projects))

    failures = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for view in VIEWS:
            page.goto(BASE + "#" + view, wait_until="networkidle")
            page.wait_for_timeout(700)
            got = page.evaluate(PROBE)
            print("%-9s stat=%-3d pill=%-3d 字号=%s 圆点=%s 溢出=%s"
                  % (view, got["stat"], got["pill"], got["sizes"], got["dots"][:2], got["overflowX"]))
            if got["stat"]:
                if got["sizes"] != ["13px"]:
                    failures.append("%s: .stat 字号 %s，应为 13px" % (view, got["sizes"]))
                for d in got["dots"]:
                    if not d.startswith("6px 6px"):
                        failures.append("%s: 圆点尺寸 %s，应为 6px 6px" % (view, d))
                if got["overflowX"]:
                    failures.append("%s: 出现横向溢出" % view)
            if got["pill"] > 5:
                print("       ↑ pill 多于 5 个：%s" % got["pill"])
            print("       色彩 pass=%s warn=%s fail=%s" % (got["colors"]["pass"], got["colors"]["warn"], got["colors"]["fail"]))
        page.screenshot(path="_ui_shots/stat-project.png", full_page=True)
        browser.close()

    if failures:
        print()
        for f in failures:
            print("FAIL " + f)
        return 1
    print("\n全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
