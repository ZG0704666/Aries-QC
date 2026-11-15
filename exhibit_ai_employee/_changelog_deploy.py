# -*- coding: utf-8 -*-
"""CHANGELOG 顶部追加「上云」一节。幂等。"""
from pathlib import Path

p = Path(__file__).resolve().parent / "CHANGELOG.md"
text = p.read_text(encoding="utf-8")
marker = "## 上云"
if marker in text:
    print("already present")
    raise SystemExit(0)

block = """## 上云：相对路径 · 断连守卫 · 一键部署 — 2026-11-15

部署到华为云 ECS（EulerOS 2.0 / Python 3.9 / 16vCPU 64GiB），与既有站点（GuitarVision、贵客松 web、旧链路 app.py）共用一个 IP，Studio 挂在 `https://<host>/studio/` 子路径下。

### 改动
- **前端改相对地址**（`_relative_paths.py`，35 处）：`'/api/studio…` → `'api/studio…`（`assets/app.js` 16 处、`studio_classic.html` 18 处）、`href="/classic"` → `href="classic"`。浏览器按页面所在目录解析，于是同一份代码在 `/` 和 `/studio/` 下都对——这是能挂子路径的前提。
- **断连守卫**（`_brokenpipe_guard.py`）：`studio_server.py:1153` 新增 `write_body()`，吞掉 `BrokenPipeError` / `ConnectionResetError` 并置 `close_connection=True`；`send_json` 的 `end_headers()` 同样包住；6 处 `self.wfile.write(...)` 改走它。前端 1.2s 轮询 + 音频预载被重渲染取消 + nginx 关 buffering，客户端中途断连是常态，原先会刷成对的 500 堆栈盖住真错误。
- `CODE_REV` → `studio-2026-11-15-p`。
- 新增 `DEPLOY.md`（依赖、首次部署、systemd/nginx 全文、运维、端口与安全边界、本机/云端差异）与 `deploy/deploy.py`（`all|upload|service|nginx|verify`，凭据读 `deploy/deploy.local.json` 或环境变量，该文件不入库）。README 附录 A 补生产实例与部署入口。

### 验证
- 远端 27/27：七视图可读且无「连不上」、控制台零错误、静态资源零失败、口令写入 `localStorage.studio_token`、health/音频/export.zip 均 200、GuitarVision `/` 与 `/journal/` 未受影响、TTS 真合成走 **breeze**（4.3s，`fallback_errors: []`）、临时项目「创建 → 对话真回话 → 删除」全通。
- 断连守卫实测：3 次只读 200 字节就掐的 `export.zip` 请求，`BrokenPipe` 计数 9 → 9（新增 0）。
- 本地回归：`_audit_full` 77/77、`_api_checks` 25/25、`_ui_checks` 51/51、`_ui_layout` 25/25、`_probe_empty` 34/34。

### 教训
- heredoc 里混 `%d` 与外层 `%` 格式化会 `TypeError: not enough arguments for format string` → 用 `.replace("__CONF__", …)`。
- 冒烟脚本直连 SSH 跑 TTS 时必须 `. ./.env`：systemd 的 `EnvironmentFile` 不会给别人的 shell，否则 `BREEZE_API_KEY` 缺失会静默降级到 edge-tts。
- nginx 两条 `server` 块 `listen` 相同且 `server_name` 匹配时，只生效第一个且**不报错**——改配置要先备份、`nginx -t` 通过才 reload。

"""
p.write_text(block + text, encoding="utf-8", newline="\n")
print("changelog updated")
