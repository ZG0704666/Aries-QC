# -*- coding: utf-8 -*-
"""用本机 Chrome/Edge 无头模式把 HTML 截成 PNG，并自动起临时 HTTP 服务。"""
from __future__ import annotations

import functools
import glob
import http.server
import os
import socketserver
import subprocess
import tempfile
import threading
import time

CHROME_CANDIDATES = [
    os.environ.get("CHROME_PATH", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # 静音
        pass


def find_chrome() -> str:
    for p in CHROME_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    raise RuntimeError(
        "未找到 Chrome/Edge。请安装 Chrome，或设置环境变量 CHROME_PATH 指向 chrome.exe。"
    )


class LocalServer:
    """在后台线程里起一个只读静态服务，供 Chrome 访问 file 内容。"""

    def __init__(self, directory: str):
        handler = functools.partial(_QuietHandler, directory=directory)
        self._srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        self._srv.daemon_threads = True
        self.port = self._srv.server_address[1]
        self._th = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def __enter__(self):
        self._th.start()
        return self

    def __exit__(self, *exc):
        self._srv.shutdown()
        self._srv.server_close()


def screenshot(
    chrome: str,
    url: str,
    out_png: str,
    size=(1440, 900),
    dpr: int = 2,
    budget_ms: int = 2500,
    retries: int = 1,
) -> bool:
    if os.path.exists(out_png):
        os.remove(out_png)
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={size[0]},{size[1]}",
        f"--force-device-scale-factor={dpr}",
        f"--virtual-time-budget={budget_ms}",
        f"--screenshot={out_png}",
        url,
    ]
    for attempt in range(retries + 1):
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.15)
        if os.path.isfile(out_png) and os.path.getsize(out_png) > 10_000:
            return True
        time.sleep(0.6)
    return False


def render_html(
    html_path: str,
    out_dir: str,
    prefix: str,
    shots: int = 8,
    size=(1440, 900),
    dpr: int = 2,
) -> list[str]:
    """把一个 HTML 按 i=0..shots-1 的滚动位置截成 shots 张图，返回路径列表。"""
    chrome = find_chrome()
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, f"{prefix}_*.png")):
        os.remove(old)
    name = os.path.basename(html_path)
    work = os.path.dirname(html_path)
    outputs: list[str] = []
    with LocalServer(work) as srv:
        for i in range(shots):
            url = f"http://127.0.0.1:{srv.port}/{name}?i={i}&n={shots - 1}"
            out_png = os.path.join(out_dir, f"{prefix}_{i + 1:02d}.png")
            ok = screenshot(chrome, url, out_png, size=size, dpr=dpr)
            if not ok:
                raise RuntimeError(f"截图失败：{out_png}")
            outputs.append(out_png)
    return outputs


def new_workdir() -> str:
    return tempfile.mkdtemp(prefix="chat-shot-")
