# -*- coding: utf-8 -*-
"""把七个视图的渲染文本抓下来，供功能文档逐节引用（只读）。"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4182"
VIEWS = ["project", "live", "content", "tests", "voice", "release", "feedback"]

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1680, "height": 1050})
    pg.goto(BASE + "/#live", wait_until="networkidle")
    pg.wait_for_function("() => {const t=document.querySelector('#conn-text');return t && t.textContent.indexOf('正在连接')<0 && document.querySelector('#workspace-body').innerText.trim().length>0}", timeout=30000)
    for v in VIEWS:
        pg.evaluate("(v)=>{location.hash=v}", v)
        pg.wait_for_timeout(900)
        txt = pg.evaluate("()=>document.querySelector('#workspace-body').innerText")
        print("=" * 20, v, "=" * 20)
        print(txt[:2200])
        print()
    b.close()
