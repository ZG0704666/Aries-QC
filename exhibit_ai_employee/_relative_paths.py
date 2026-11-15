# -*- coding: utf-8 -*-
"""把前端写死的根绝对路径改成相对路径，让页面能挂在 /studio/ 子路径下。

根绝对路径（'/api/studio/...'、href="/classic"）只在站点根目录时才对；
挂到 https://host/studio/ 后会被解析成 /api/... 而打到别的站点。
浏览器解析相对路径时按「当前页面所在目录」——页面在 / 时得到 /api/...，
在 /studio/ 时得到 /studio/api/...，两种部署都对。

只改字面量前缀，不动逻辑。幂等：再跑一次计数为 0。
"""
from pathlib import Path

ROOT = Path(r"D:\怀客松\exhibit_ai_employee")

def patch(path: Path, pairs):
    text = path.read_text(encoding="utf-8")
    total = 0
    for old, new in pairs:
        n = text.count(old)
        if n:
            text = text.replace(old, new)
            total += n
            print("  %s: %d × %r -> %r" % (path.name, n, old, new))
    if total:
        path.write_text(text, encoding="utf-8", newline="\n")
    else:
        print("  %s: 已是相对路径，跳过" % path.name)
    return total

print("== assets/app.js ==")
n1 = patch(ROOT / "assets" / "app.js", [
    ("'/api/studio", "'api/studio"),
    ('"/api/studio', '"api/studio'),
    ('href="/classic"', 'href="classic"'),
])

print("== studio_classic.html ==")
n2 = patch(ROOT / "studio_classic.html", [
    ("'/api/studio", "'api/studio"),
    ('"/api/studio', '"api/studio'),
    ('href="/classic"', 'href="classic"'),
])

print("== studio_web.html ==")
n3 = patch(ROOT / "studio_web.html", [
    ("'/api/studio", "'api/studio"),
    ('"/api/studio', '"api/studio'),
])

print("\nchanged total:", n1 + n2 + n3)
