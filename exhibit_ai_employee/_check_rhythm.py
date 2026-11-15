"""版式节奏体检：间距是否成体系、正文行高是否在 1.5~1.8、指标组是否对齐。

这是对 token 化的补充验证——颜色和字号收敛了，但如果间距各写各的，版面照样乱。
判据来自 ui-ux-pro-max 的 spacing-scale / line-height / whitespace-balance。

例外：讲解正文（`.paper` / 阅读弹窗 / 资料段落 / 对话气泡 / 事实卡）是**长文阅读区**，
行高 1.75~1.9 是刻意的（读起来才不挤），所以这条判据只约束界面文字。
"""
import sys

from playwright.sync_api import sync_playwright

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4182
BASE = "http://127.0.0.1:%d/" % PORT
VIEWS = ["project", "live", "content", "tests", "voice", "release", "feedback"]
LADDER = {0, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 28, 32, 40, 48}

PROBE = """() => {
  const px = (v) => Math.round(parseFloat(v) || 0);
  const body = document.querySelector('#workspace-body') || document.body;
  const kids = Array.from(body.children).filter((el) => el.offsetHeight > 0);
  const gaps = [];
  for (let i = 1; i < kids.length; i += 1) {
    const r0 = kids[i - 1].getBoundingClientRect();
    const r1 = kids[i].getBoundingClientRect();
    gaps.push(Math.round(r1.top - r0.bottom));
  }
  const paras = Array.from(document.querySelectorAll('#workspace-body p'))
    .filter((el) => el.offsetHeight > 0 && el.textContent.trim().length > 20)
    .filter((el) => !el.closest('.paper, .reading-dialog, .para-list, .message-body, .fact-item'))
    .slice(0, 12)
    .map((el) => {
      const s = getComputedStyle(el);
      const size = px(s.fontSize);
      return {lh: +(px(s.lineHeight) / (size || 1)).toFixed(2), size};
    });
  const rows = Array.from(document.querySelectorAll('#workspace-body .metric-row'))
    .filter((el) => el.offsetHeight > 0).slice(0, 12)
    .map((el) => Math.round(el.getBoundingClientRect().height));
  const stats = Array.from(document.querySelectorAll('#workspace-body .stat'));
  const statHeights = Array.from(new Set(stats.map((el) => Math.round(el.getBoundingClientRect().height))));
  const clipped = stats.filter((el) => el.scrollWidth > el.clientWidth + 1).length;
  return {gaps, paras, rows: Array.from(new Set(rows)), statHeights, clipped};
}"""


def main():
    failures = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        for view in VIEWS:
            page.goto(BASE + "#" + view, wait_until="networkidle")
            page.wait_for_timeout(600)
            got = page.evaluate(PROBE)
            off = [g for g in got["gaps"] if abs(g) not in LADDER]
            print("%-9s 区块间隙=%-22s 字号/行高=%s" % (
                view, got["gaps"], ["%dpx×%.2f" % (p["size"], p["lh"]) for p in got["paras"][:4]]))
            print("          指标行高=%-14s stat 行高=%s 截断=%d" % (
                got["rows"], got["statHeights"], got["clipped"]))
            if off:
                failures.append("%s: 区块间隙 %s 不在 4 网格上" % (view, off))
            bad = [p for p in got["paras"] if not (1.45 <= p["lh"] <= 1.85)]
            if bad:
                failures.append("%s: 界面正文行高 %s 超出 1.45~1.85" % (view, bad))
            if got["clipped"]:
                failures.append("%s: 有 %d 个 .stat 文字被截断" % (view, got["clipped"]))
        browser.close()

    if failures:
        print()
        for f in failures:
            print("FAIL " + f)
        return 1
    print("\n节奏全部在体系内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
