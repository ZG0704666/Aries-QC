# -*- coding: utf-8 -*-
"""列出前端用到的所有 class（按出现次数），用于确定设计系统要覆盖哪些零件。"""
import collections
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(BASE, "assets", "app.js"), encoding="utf-8").read()
html = open(os.path.join(BASE, "studio_web.html"), encoding="utf-8").read()

names = collections.Counter()
for m in re.finditer(r'class="([^"]+)"', src + html):
    for part in m.group(1).split():
        if part.startswith("$") or "{" in part:
            continue
        names[part] += 1

print("共 %d 个 class" % len(names))
for k, v in names.most_common(120):
    print("%-24s %d" % (k, v))
