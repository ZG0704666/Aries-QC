# -*- coding: utf-8 -*-
"""从 _visual_audit.py 的结构图里挑「版心过空」的屏幕，并打印指定视图的完整结构图。"""
import io
import os
import re
import sys

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "_ui_shots", "visual-audit.txt")
raw = open(PATH, "rb").read().decode("utf-8", "replace")
parts = re.split(r"(?m)^={78}\s*$", raw)

# 每屏一段：先 header 行，再结构图
for p in parts:
    if "结构图" not in p:
        continue
    lines = [l for l in p.splitlines() if l.strip()]
    head = next((l for l in lines if re.search(r"\b[A-Z]{4,}\s+\d+x\d+", l)), "")
    struct = [l for l in lines if l.startswith("   |")]
    if not struct:
        continue
    # 版心 = 24~72 列、6~27 行，统计非空格字符占比
    core = sum(1 for l in struct[6:27] for c in l[26:76] if c != " ")
    total = 21 * 50
    ratio = core / total
    print("%-58s 版心文字密度=%.3f" % (head.strip()[:58], ratio))
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        for l in struct:
            print(l)
        print()
