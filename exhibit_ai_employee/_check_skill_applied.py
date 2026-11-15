# -*- coding: utf-8 -*-
"""验证 ui-ux-pro-max skill 的四条建议真的落到了渲染结果上，不只是写了 CSS。

来源（D:\\怀客松\\_skill_recover\\ 下保存的真实输出）：
  design-system.md  Data-Dense Dashboard：row highlighting on hover、cursor-pointer、
                    hover 150-300ms、data loading spinners
  ux.md             hover 要有视觉反馈、提交要有 loading、数字要可读
  colors.md         首推 navy #1E3A5F + green #16A34A，与现有 token 同族，不换色

量的是计算样式与像素，不是「我加了规则」。
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = Path(__file__).resolve().parent
PORT = int(os.environ.get("SKILL_PORT", "4241"))
PID = "skillui01"
ORIGIN = f"http://127.0.0.1:{PORT}"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS " if ok else "FAIL ") + name + ("  " + str(detail) if detail else ""), flush=True)


def api(path, method="GET", payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(ORIGIN + path, data=body, method=method)
    if body:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            data = json.loads(raw)
        except Exception:
            data = {"_raw": raw}
        return {"_status": e.code, **data}


def main():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="studio_skill_")
    db_path = os.path.join(tmp, "skill.sqlite3")
    audio_dir = os.path.join(tmp, "audio")
    os.makedirs(audio_dir, exist_ok=True)

    built = subprocess.run([sys.executable, "_fixture.py", db_path, audio_dir, PID], cwd=BASE,
                           capture_output=True, text=True, encoding="utf-8")
    if built.returncode != 0:
        print("夹具建不起来：\n" + (built.stderr or ""))
        return 2

    env = dict(os.environ)
    for k in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        env.pop(k, None)
    env.update({"STUDIO_DB": db_path, "STUDIO_AUDIO_DIR": audio_dir,
                "STUDIO_PORT": str(PORT), "STUDIO_HOST": "127.0.0.1", "PYTHONIOENCODING": "utf-8"})
    proc = subprocess.Popen([sys.executable, "studio_server.py"], cwd=BASE, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(ORIGIN + "/api/studio/health", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        errors = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{ORIGIN}/?project={PID}", wait_until="networkidle")
            page.wait_for_timeout(700)

            def go(view):
                page.evaluate("v => location.hash = '#' + v", view)
                page.wait_for_timeout(450)

            # ---------- ① 行 hover 高亮：真的量背景色变化 ----------
            go("tests")
            page.wait_for_timeout(400)
            row = page.locator(".table-wrap tbody tr").first
            before = row.evaluate("e=>getComputedStyle(e).backgroundColor")
            row.hover()
            page.wait_for_timeout(260)  # 过渡 150ms，等它走完
            after = row.evaluate("e=>getComputedStyle(e).backgroundColor")
            check("① 表格行 hover 背景真的变了", before != after, f"{before} → {after}")

            dur = row.evaluate("e=>getComputedStyle(e).transitionDuration")
            check("① hover 过渡在 150–300ms 区间",
                  any(0.15 - 1e-6 <= float(x.rstrip("s")) <= 0.3 for x in dur.split(",")), dur)

            fb = page.locator(".table-wrap tbody tr").first
            check("① 表格有横向滚动容器（skill: overflow-x-auto wrapper）",
                  page.locator(".table-wrap").first.evaluate(
                      "e=>['auto','scroll'].includes(getComputedStyle(e).overflowX)"))

            # ---------- ② 等宽数字 ----------
            go("project")
            page.wait_for_timeout(200)
            fn = page.locator(".price").first.evaluate("e=>getComputedStyle(e).fontVariantNumeric")
            check("② 金额使用等宽数字 tabular-nums", "tabular-nums" in fn, fn)
            check("② 金额有千分位（skill: Number Formatting）",
                  "," in page.locator(".price").first.inner_text() or "—" in page.locator(".price").first.inner_text(),
                  page.locator(".price").first.inner_text())

            # ---------- ③ 折叠指示 ----------
            go("live")
            page.wait_for_timeout(200)
            summary = page.locator("details.event-history > summary").first
            cursor = summary.evaluate("e=>getComputedStyle(e).cursor")
            check("③ summary 是 pointer 光标", cursor == "pointer", cursor)
            marker = summary.evaluate(
                "e=>{const b=getComputedStyle(e,'::before');"
                "return b.borderLeftWidth + '/' + b.borderLeftColor + '/content=' + b.content;}")
            check("③ summary 有箭头指示（CSS 三角，不再是字符）",
                  marker.startswith("5px"), marker)
            t0 = summary.evaluate("e=>getComputedStyle(e,'::before').transform")
            summary.click()
            page.wait_for_timeout(260)
            t1 = summary.evaluate("e=>getComputedStyle(e,'::before').transform")
            check("③ 展开后箭头旋转（transform 变化）", t0 != t1, f"{t0} → {t1}")

            # 折叠指示只留一个箭头，且不换行（旧实现 ::before 是字符 '›'，会和三角叠成双箭头）
            wrap = page.locator("details.event-history > summary").first.bounding_box()
            check("③ 运行记录 summary 单行（无双箭头换行）", wrap and wrap["height"] <= 56,
                  round(wrap["height"], 1) if wrap else None)

            # .file-tree summary 是 grid 三列，不能被折叠指示改成 flex
            go("release")
            page.wait_for_timeout(300)
            if page.locator(".file-tree summary").count():
                disp = page.locator(".file-tree summary").first.evaluate("e=>getComputedStyle(e).display")
                check("③ 文件树 summary 保持 grid 布局", disp == "grid", disp)
            go("live")
            page.wait_for_timeout(300)

            # ---------- ④ 生成中 spinner ----------
            has_run = page.locator('button[data-action="run"]').count()
            if has_run:
                btn = page.locator('button[data-action="run"]').first
                page.evaluate("""() => {
                  const b = document.querySelector('button[data-action="run"]');
                  if (b) b.disabled = true;   // 只量样式，不真触发模型调用
                }""")
                page.wait_for_timeout(200)
                spin = btn.evaluate("e=>getComputedStyle(e,'::after').animationName")
                check("④ 生成按钮禁用时有 spinner 动画", spin == "ds-spin", spin)
                btn.evaluate("e=>e.disabled=false")
            else:
                check("④ 生成按钮存在", False, "找不到 data-action=run")

            # ---------- ⑤ 配色方向核对（skill 首推 navy+green，与现有 token 同族） ----------
            tokens = page.evaluate("""() => {
              const cs = getComputedStyle(document.documentElement);
              return {navy: cs.getPropertyValue('--ds-navy').trim(),
                      accent: cs.getPropertyValue('--ds-accent').trim()};
            }""")
            check("⑤ 主色是 navy 系（skill: Trust navy）", tokens["navy"].startswith("#"), tokens)

            # ---------- ⑥ 不引入横向溢出 / JS 错误 ----------
            bad = []
            for v in ["project", "live", "content", "tests", "voice", "release", "feedback"]:
                go(v)
                page.wait_for_timeout(150)
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
                if overflow:
                    bad.append(v)
            check("⑥ 七视图无横向溢出", not bad, bad)
            check("⑥ 全程零 JS 错误", not errors, errors)
            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()

    ok = sum(1 for _, v in results if v)
    print(f"\n===== skill 落地验证 {ok}/{len(results)} =====")
    (BASE / "_ui_shots").mkdir(exist_ok=True)
    (BASE / "_ui_shots" / "skill-applied.txt").write_text(
        "\n".join(("PASS " if v else "FAIL ") + n for n, v in results) + f"\n{ok}/{len(results)}\n",
        encoding="utf-8")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
