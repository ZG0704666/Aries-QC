# 部署与运维

Studio 是一个单进程的 Python 服务（标准库 HTTP server + `edge-tts`），没有前端构建步骤，也没有外部数据库。所以部署就是「放文件 + 起 systemd + 挂到 nginx 的一个子路径」。

现网实例：**https://139.9.131.86/studio/**（访问口令在服务器 `/opt/exhibit-studio/.env` 的 `STUDIO_ACCESS_TOKEN`）。

---

## 一、它依赖什么

| 依赖 | 说明 |
|---|---|
| Python 3.9+ | 只用标准库 + `edge-tts`（可选 `pypdf`，用于读 PDF 资料） |
| ffmpeg / ffprobe | 音频转码与**时长实测**。没有 ffprobe 就没有时长门禁——自测会判「量不到时长」而不是放行 |
| 出网 | 模型 API（DeepSeek）、TTS（Breeze / edge-tts）、联网调研（Bing） |
| nginx（可选） | 只有在需要 80/443 对外、或与别的站点共用一个 IP 时才要 |

---

## 二、首次部署

### 1. 传运行时文件

只需要这些，源码仓库里的 `_*.py` 探针、`tests/`、`.blend` 等一概不传：

```
studio_server.py  tts.py  breeze.py  docread.py  websearch.py
studio_web.html   studio_classic.html
README.md  CHANGELOG.md
assets/           audio/
studio.sqlite3    # 要带上已有项目才传
```

```bash
tar -czf studio_deploy.tar.gz studio_server.py tts.py breeze.py docread.py \
    websearch.py studio_web.html studio_classic.html README.md CHANGELOG.md \
    studio.sqlite3 assets audio
scp studio_deploy.tar.gz root@<host>:/root/
ssh root@<host> 'mkdir -p /opt/exhibit-studio && tar -xzf /root/studio_deploy.tar.gz -C /opt/exhibit-studio'
```

### 2. Python 依赖

```bash
cd /opt/exhibit-studio
python3 -m venv venv
venv/bin/pip install -U pip
venv/bin/pip install edge-tts pypdf
dnf install -y ffmpeg ffmpeg-libs      # CentOS/HCE/EulerOS 系；Debian 系用 apt install ffmpeg
```

### 3. 配置 `.env`

```bash
cd /opt/exhibit-studio
cp .env.example .env 2>/dev/null || touch .env
chmod 600 .env
```

必填项：

```ini
DEEPSEEK_API_KEY=...            # 或 AI_API_KEY
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-chat

STUDIO_HOST=127.0.0.1           # 只监听本机，由 nginx 对外
STUDIO_PORT=4182
STUDIO_ACCESS_TOKEN=...         # 访问口令；不设则只能在监听 127.0.0.1 时启动（启动护栏）
```

可选项：

```ini
BREEZE_API_KEY=...  BREEZE_VOICE_ID=...  BREEZE_MODEL_ID=breeze-tts-2
STUDIO_TTS_ENGINE=auto          # auto：breeze → edge-tts → sapi，前一个失败就换下一个
STUDIO_DB=/opt/exhibit-studio/studio.sqlite3
STUDIO_AUDIO_DIR=/opt/exhibit-studio/audio
```

> **护栏**：`main()` 里有一道检查——既没配 `STUDIO_ACCESS_TOKEN`、又不是监听 `127.0.0.1` 时直接 `SystemExit`。这是为了防止把没有口令的接口暴露到公网。确实需要公开无口令服务时才设 `STUDIO_ALLOW_NO_AUTH=1`。

### 4. systemd

`/etc/systemd/system/exhibit-studio.service`：

```ini
[Unit]
Description=Exhibit Studio - AI 员工内容工作台
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/exhibit-studio
EnvironmentFile=/opt/exhibit-studio/.env
ExecStart=/opt/exhibit-studio/venv/bin/python /opt/exhibit-studio/studio_server.py
Restart=always
RestartSec=3
TimeoutStopSec=20
StandardOutput=append:/var/log/exhibit-studio.log
StandardError=append:/var/log/exhibit-studio.log

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now exhibit-studio
systemctl status exhibit-studio --no-pager
curl -s -H "X-Access-Token: $TOKEN" http://127.0.0.1:4182/api/studio/health
```

`Restart=always` + `enable` 组合保证：进程崩了 3 秒后自己起来，机器重启后也自己起来。

### 5. nginx 挂到子路径

Studio 的前端全部用**相对地址**请求接口（`api/studio/...` 而不是 `/api/studio/...`），所以它既能挂在 `/`，也能挂在 `/studio/` 这样的子路径下——浏览器按页面所在目录解析，两种都对。

`/etc/nginx/snippets/studio-locations.conf`：

```nginx
location = /studio {
    return 301 /studio/;
}

location /studio/ {
    proxy_pass http://127.0.0.1:4182/;      # 尾斜杠把 /studio/ 前缀剥掉
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    client_max_body_size 24m;               # 资料上传（docread 上限 20MB）
    proxy_read_timeout 600s;                # 整批起草、联网调研是分钟级
    proxy_send_timeout 600s;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}
```

然后在已有的 `server { listen 443 ssl ... }` 块里 `include /etc/nginx/snippets/studio-locations.conf;`。

```bash
nginx -t && systemctl reload nginx
```

> 挂到已有站点的 ssl server 块里，**先备份**、`nginx -t` 通过才 reload。两条 server 块如果有相同的 `listen` + `server_name`，nginx 只会用第一个，不会报错——这是最容易踩的坑。

---

## 三、日常运维

```bash
systemctl status  exhibit-studio          # 在跑吗
systemctl restart exhibit-studio          # 改了 .env 或 .py 之后
journalctl -u exhibit-studio -n 50        # systemd 视角
tail -50 /var/log/exhibit-studio.log      # 应用日志（含 traceback）
ss -lntp | grep 4182                      # 端口
curl -s -H "X-Access-Token: $TOKEN" http://127.0.0.1:4182/api/studio/health
```

`health` 里的 `code` 字段是当前代码版本（`CODE_REV`），改完重启后必须变——这是「我改的到底是哪份代码」的唯一可靠判据。

### 更新代码

```bash
scp studio_server.py tts.py assets/app.js assets/studio.css root@<host>:/opt/exhibit-studio/...
ssh root@<host> 'systemctl restart exhibit-studio'
```

前端文件（`assets/`、`*.html`）是每次请求现读的，改完刷新即可，不用重启；只有 `.py` 需要重启。静态资源响应带 `Cache-Control: no-store`，所以也不会拿到旧缓存。

### 关于客户端断连

前端 1.2s 轮询、音频预载会被重新渲染取消，nginx 又关了 buffering，所以「客户端中途关连接」是常态。`write_body()` / `send_json()` 会吞掉 `BrokenPipeError` / `ConnectionResetError` 并把连接标记为关闭——断线不是服务端错误，不该在日志里刷成 500 堆栈把真错误盖住。

---

## 四、端口与安全边界

- 服务只监听 `127.0.0.1:4182`，公网只看得到 nginx 的 80/443。
- 所有 `/api/studio/*` 都要口令（`X-Access-Token` 头或 `?token=`）；静态页与 `/assets/*` 免口令——那里面没有项目数据。
- 口令比较用 `hmac.compare_digest`，避免计时侧信道。
- `?token=` 这条通道是必需的：`<audio src>` 和 `导出下载` 没法带自定义请求头。代价是口令会出现在 URL 里（会进浏览器历史和 nginx access log）。前端首次带 `?token=` 打开后会把它存进 `localStorage`，之后接口请求走请求头。
- 服务器上的 `.env` 权限 600，只 root 可读。
- 数据库 `studio.sqlite3` 不入版本库——里面有真实项目的资料与对话记录。

---

## 五、本机与云端的行为差异

| 项 | 本机 | 云端 |
|---|---|---|
| 访问口令 | 通常不设（`auth_required:false`） | 必须设，经 nginx 反代 |
| TTS 引擎 | `breeze → edge-tts → sapi` 全可用 | 通常是 `breeze → edge-tts`（无 Windows SAPI） |
| 端口 | 4182 直连 | 127.0.0.1:4182，由 nginx 暴露 |
| 口吻差异 | 无 | 联网调研的落地 IP 不同，搜索结果会有差别 |

自测里的「时长门」在两边都必须真量：`measured_duration()` 优先现场 `ffprobe` 并回写，量不到就判失败——**不拿字数冒充时长**。所以 ffprobe 装没装，直接决定自测是不是真在验。
