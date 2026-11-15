# -*- coding: utf-8 -*-
"""让「客户端中途断开」不再在日志里刷 BrokenPipe 500 堆栈。

背景：前端 1.2s 轮询、音频预载会被重新渲染取消，nginx 又关了 buffering，
所以客户端断连是常态。原先 send_json/serve_page 直接写 socket，一旦断连，
do_GET 的 catch-all 还会再写一次 500（于是再抛一次 BrokenPipe），日志里就出现
成对的堆栈——长跑服务会被这种噪音盖住真错误。
"""
from pathlib import Path

p = Path(r"D:\怀客松\exhibit_ai_employee\studio_server.py")
src = p.read_text(encoding="utf-8")
orig = src

# 1) 统一走 write_body
src = src.replace("self.wfile.write(raw)", "self.write_body(raw)")
src = src.replace("return self.wfile.write(page)", "return self.write_body(page)")

# 2) send_json：end_headers 也可能撞断连
old_json = """    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.write_body(raw)
"""
new_json = """    def write_body(self, raw):
        \"\"\"写响应体。客户端中途关连接（刷新、切视图、音频预载被取消）是常态，
        不该在日志里变成 BrokenPipe 堆栈——断线不是服务端错误。\"\"\"
        try:
            return self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            return None

    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
            return None
        return self.write_body(raw)
"""
assert old_json in src, "send_json 结构没对上"
src = src.replace(old_json, new_json)

if "self.wfile.write" in src:
    left = src.count("self.wfile.write")
    print("!! 还剩 %d 处直接写 socket" % left)

p.write_text(src, encoding="utf-8", newline="\n")
print("patched: %d -> %d bytes" % (len(orig), len(src)))
