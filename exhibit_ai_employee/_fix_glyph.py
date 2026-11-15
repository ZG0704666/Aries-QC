# -*- coding: utf-8 -*-
"""交付包文件树：去掉 summary 里手写的 ▤ 字符，折叠箭头统一由 CSS 画。
用字节替换，避免控制台编码把字符改坏。"""
from pathlib import Path

p = Path(__file__).resolve().parent / "assets" / "app.js"
raw = p.read_bytes()
old = "<summary>▤ ".encode("utf-8")
new = "<summary>".encode("utf-8")
assert raw.count(old) == 1, raw.count(old)
p.write_bytes(raw.replace(old, new))
print("removed decorative glyph from file-tree summary")
