# -*- coding: utf-8 -*-
"""最终交付验收：服务常驻状态 + 远端取一张内容成果屏截图。"""
import json
import sys
import urllib3
from pathlib import Path

import paramiko
import requests
from playwright.sync_api import sync_playwright

urllib3.disable_warnings()

CONF = json.loads((Path(__file__).resolve().parent / "deploy" / "deploy.local.json").read_text(encoding="utf-8"))
HOST = CONF["host"]
TOKEN = CONF["token"]
BASE = "https://%s/studio/" % HOST
SHOTS = Path(__file__).resolve().parent / "_ui_shots"
SHOTS.mkdir(exist_ok=True)

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(HOST, username=CONF["user"], password=CONF["password"], timeout=30)


def run(cmd):
    _, out, err = cli.exec_command(cmd, timeout=120)
    return (out.read() + err.read()).decode("utf-8", "replace").strip()


print("服务状态：")
for cmd in [
    "systemctl is-enabled exhibit-studio",
    "systemctl is-active exhibit-studio",
    "systemctl show -p Restart -p RestartSec -p NRestarts --value exhibit-studio",
    "systemctl show exhibit-studio -p ActiveEnterTimestamp --value",
    "ss -lntp | grep 4182 | head -1",
]:
    print("  %-52s %s" % (cmd.split("--value")[0][:52], run(cmd)))

health = requests.get(BASE + "api/studio/health", params={"token": TOKEN}, timeout=20, verify=False).json()
print("\nhealth：code=%s  model=%s  key=%s  tts=%s  pid=%s"
      % (health.get("code"), health.get("model"), health.get("key_configured"),
         ",".join((health.get("tts") or {}).get("engines") or []), health.get("pid")))

projects = requests.get(BASE + "api/studio/projects", params={"token": TOKEN}, timeout=20, verify=False).json()
ids = [p["id"] for p in projects.get("projects", [])]
print("项目：%s" % ids)

errors = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE + "?token=" + TOKEN, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(1500)
    page.evaluate("() => location.hash = '#content'")
    page.wait_for_timeout(2500)
    page.screenshot(path=str(SHOTS / "prod-content.png"), full_page=False)
    print("\n截图：%s" % (SHOTS / "prod-content.png"))
    print("控制台错误：%s" % (errors or "无"))
    browser.close()

cli.close()
