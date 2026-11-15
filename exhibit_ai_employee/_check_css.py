# -*- coding: utf-8 -*-
"""检查 CSS 结构完整性：括号配平、引号配平、content 字符串是否完整。"""
import glob
import re

FILES = ["assets/styles.css", "assets/refinement.css", "assets/atelier.css",
         "assets/workspace-tools.css", "assets/studio.css", "assets/tokens.css"]

for path in FILES:
    raw = open(path, encoding="utf-8").read()
    # 去掉注释再数括号，避免注释里的中文干扰
    stripped = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    print("%-28s 长度%6d  { %d } %d  引号 %d  var() %3d  color-mix %2d"
          % (path.split("/")[-1], len(raw), stripped.count("{"), stripped.count("}"),
             stripped.count('"'), len(re.findall(r"var\(--ds-", raw)),
             len(re.findall(r"color-mix\(", raw))))
    for m in re.finditer(r'content\s*:\s*"([^"]*)"', raw):
        print("      content: %s" % m.group(1))
