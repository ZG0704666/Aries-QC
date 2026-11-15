# -*- coding: utf-8 -*-
"""把 Studio 部署到一台 Linux 服务器（一键：传文件 → venv → systemd → nginx → 验收）。

凭据不进版本库：同目录放 deploy.local.json（已在 .gitignore 里），或用环境变量。

    deploy.local.json
    {
      "host": "1.2.3.4",
      "user": "root",
      "password": "…",            # 或 "key_file": "C:/Users/me/.ssh/id_rsa"
      "token": "访问口令，留空则自动生成",
      "remote_root": "/opt/exhibit-studio",
      "base_url": "https://1.2.3.4",
      "sub_path": "/studio/",     # 挂在根路径就写 "/"
      "env_file": ".env.local"    # 本机已有的密钥文件，原样送上服务器
    }

用法：
    python deploy/deploy.py all          # 全流程
    python deploy/deploy.py upload       # 只传文件
    python deploy/deploy.py service      # 只装 systemd 并启动
    python deploy/deploy.py nginx        # 只挂 nginx 子路径
    python deploy/deploy.py verify       # 只跑验收

本机依赖：paramiko、requests（验收时还会用 playwright）。
服务器依赖见 DEPLOY.md。
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import sys
import tarfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent                      # exhibit_ai_employee/
CONF_PATH = HERE / "deploy.local.json"

RUNTIME = [
    "studio_server.py", "tts.py", "breeze.py", "docread.py", "websearch.py",
    "studio_web.html", "studio_classic.html", "README.md", "CHANGELOG.md", "DEPLOY.md",
]
RUNTIME_DIRS = ["assets", "audio"]
OPTIONAL = ["studio.sqlite3"]           # 有就带上（已有项目的数据库）

UNIT = """[Unit]
Description=Exhibit Studio - AI 员工内容工作台
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={root}
EnvironmentFile={root}/.env
ExecStart={root}/venv/bin/python {root}/studio_server.py
Restart=always
RestartSec=3
TimeoutStopSec=20
StandardOutput=append:/var/log/exhibit-studio.log
StandardError=append:/var/log/exhibit-studio.log

[Install]
WantedBy=multi-user.target
"""

SNIPPET = """# Exhibit Studio（AI 员工内容工作台）
# 前端用相对地址请求接口，所以挂在子路径下也能工作：这里用带尾斜杠的
# proxy_pass 把 {prefix} 剥掉，应用自己仍以为在根路径。
location = {prefix_no_slash} {{
    return 301 {prefix};
}}

location {prefix} {{
    proxy_pass http://127.0.0.1:{port}/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    client_max_body_size 24m;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    proxy_buffering off;
    add_header Cache-Control "no-store" always;
}}
"""


def cfg() -> dict:
    data = {}
    if CONF_PATH.exists():
        data = json.loads(CONF_PATH.read_text(encoding="utf-8"))
    for key, env in [("host", "STUDIO_SSH_HOST"), ("user", "STUDIO_SSH_USER"),
                     ("password", "STUDIO_SSH_PASSWORD"), ("token", "STUDIO_ACCESS_TOKEN"),
                     ("base_url", "STUDIO_BASE_URL"), ("key_file", "STUDIO_SSH_KEY")]:
        if os.environ.get(env):
            data[key] = os.environ[env]
    data.setdefault("user", "root")
    data.setdefault("remote_root", "/opt/exhibit-studio")
    data.setdefault("sub_path", "/studio/")
    data.setdefault("env_file", ".env.local")
    data.setdefault("port", 4182)
    if not data.get("host"):
        raise SystemExit("缺少 host：写 deploy/deploy.local.json 或设 STUDIO_SSH_HOST")
    if not data.get("token"):
        data["token"] = secrets.token_hex(8)
    if not data.get("base_url"):
        data["base_url"] = "https://" + data["host"]
    return data


def ssh(c):
    import paramiko

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kw = dict(port=22, username=c["user"], timeout=30, banner_timeout=30, auth_timeout=30)
    if c.get("key_file"):
        kw["key_filename"] = c["key_file"]
    else:
        kw["password"] = c["password"]
    cli.connect(c["host"], **kw)

    def run(cmd, timeout=300):
        _, out, err = cli.exec_command(cmd, timeout=timeout)
        return (out.read().decode("utf-8", "replace") + err.read().decode("utf-8", "replace")).strip()

    return cli, run


def step_upload(c):
    print("== 传运行时文件 ==")
    buf = io.BytesIO()
    missing = [f for f in RUNTIME if not (ROOT / f).is_file()]
    if missing:
        raise SystemExit("缺少运行时文件：" + ", ".join(missing))
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name in RUNTIME:
            tar.add(ROOT / name, arcname=name)
        for name in RUNTIME_DIRS:
            if (ROOT / name).is_dir():
                tar.add(ROOT / name, arcname=name)
        for name in OPTIONAL:
            if (ROOT / name).is_file():
                tar.add(ROOT / name, arcname=name)
    payload = buf.getvalue()

    cli, run = ssh(c)
    sftp = cli.open_sftp()
    with sftp.open("/root/studio_deploy.tar.gz", "wb") as f:
        f.write(payload)
    sftp.close()
    root = c["remote_root"]
    print("  打包 %d 字节" % len(payload))
    print("  " + run("mkdir -p %s && tar -xzf /root/studio_deploy.tar.gz -C %s && ls %s | head -20"
                     % (root, root, root)))
    print("  " + run("command -v ffmpeg >/dev/null && echo ffmpeg-ok || (dnf install -y ffmpeg ffmpeg-libs >/dev/null 2>&1 "
                     "&& echo ffmpeg-installed || apt install -y ffmpeg >/dev/null 2>&1 && echo ffmpeg-installed || echo 'ffmpeg 缺失：时长门将无法实测')"))
    print("  " + run("cd %s && [ -d venv ] || python3 -m venv venv" % root))
    print("  " + run("cd %s && venv/bin/pip install -q -U pip && venv/bin/pip install -q edge-tts pypdf && "
                     "venv/bin/python -c 'import edge_tts; print(\"edge-tts\", edge_tts.__version__)'" % root))
    cli.close()


def step_service(c):
    print("== systemd ==")
    root = c["remote_root"]
    env_lines = []
    local_env = ROOT / c["env_file"]
    if local_env.is_file():
        env_lines = local_env.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n").split("\n")
    env_lines += ["", "# ── 部署追加 ──",
                  "STUDIO_HOST=127.0.0.1",
                  "STUDIO_PORT=%d" % c["port"],
                  "STUDIO_ACCESS_TOKEN=%s" % c["token"]]
    cli, run = ssh(c)
    sftp = cli.open_sftp()
    with sftp.open(root + "/.env", "w") as f:
        f.write("\n".join(env_lines) + "\n")
    sftp.chmod(root + "/.env", 0o600)
    with sftp.open("/etc/systemd/system/exhibit-studio.service", "w") as f:
        f.write(UNIT.format(root=root))
    sftp.close()
    print("  " + run("systemctl daemon-reload && systemctl enable exhibit-studio 2>&1 | tail -1"))
    print("  " + run("systemctl restart exhibit-studio && sleep 4 && systemctl is-active exhibit-studio"))
    print("  " + run("ss -lntp | grep %d || echo 'NO LISTEN'" % c["port"]))
    health = run("curl -s --max-time 10 -H 'X-Access-Token: %s' http://127.0.0.1:%d/api/studio/health"
                 % (c["token"], c["port"]))
    print("  health: " + health[:220])
    if '"ok": true' not in health:
        print(run("tail -40 /var/log/exhibit-studio.log"))
    cli.close()


def step_nginx(c):
    print("== nginx 子路径 ==")
    prefix = c["sub_path"]
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    if not prefix.endswith("/"):
        prefix += "/"
    if prefix == "/":
        print("  挂在根路径，跳过 nginx 子路径配置（直接 proxy_pass 到 %d 即可）" % c["port"])
        return
    cli, run = ssh(c)
    sftp = cli.open_sftp()
    snippet_path = "/etc/nginx/snippets/studio-locations.conf"
    with sftp.open(snippet_path, "w") as f:
        f.write(SNIPPET.format(prefix=prefix, prefix_no_slash=prefix.rstrip("/"), port=c["port"]))
    sftp.close()
    print("  " + run("wc -l " + snippet_path))

    # 找一个 listen 443 的 server 块，把 include 塞进去（幂等）
    patch = r'''
python3 - <<'PY'
import glob, re, shutil, time
target = "    include /etc/nginx/snippets/studio-locations.conf;"
hit = None
for path in glob.glob("/etc/nginx/conf.d/*.conf") + glob.glob("/etc/nginx/sites-enabled/*"):
    text = open(path, encoding="utf-8", errors="replace").read()
    if target.strip() in text:
        print("already:", path); hit = path; break
    if "listen 443" in text and "server_name" in text:
        hit = path; break
if hit and target.strip() not in open(hit, encoding="utf-8", errors="replace").read():
    bak = hit + ".bak-" + time.strftime("%Y%m%d%H%M%S")
    shutil.copy2(hit, bak)
    text = open(hit, encoding="utf-8", errors="replace").read()
    idx = text.rstrip().rfind("}")
    text = text[:idx] + target + "\n" + text[idx:]
    open(hit, "w", encoding="utf-8").write(text)
    print("patched:", hit, "backup:", bak)
elif not hit:
    print("没找到 listen 443 的 server 块，请手工 include: /etc/nginx/snippets/studio-locations.conf")
PY'''
    print("  " + run(patch))

    check = run("nginx -t 2>&1")
    print("  " + check.replace("\n", "\n  "))
    if "successful" not in check:
        print("  !! nginx -t 未通过，不 reload（上面有备份路径，可回滚）")
        cli.close()
        return
    print("  " + run("systemctl reload nginx && echo reloaded"))
    cli.close()


def step_verify(c):
    print("== 验收 ==")
    import urllib3
    import requests
    urllib3.disable_warnings()
    base = c["base_url"].rstrip("/")
    prefix = c["sub_path"]
    if not prefix.endswith("/"):
        prefix += "/"
    api = base + prefix + "api/studio/health"
    ok = True
    for label, url in [
        ("首页", base + prefix),
        ("前端脚本", base + prefix + "assets/app.js"),
        ("样式", base + prefix + "assets/studio.css"),
        ("健康检查", api + "?token=" + c["token"]),
    ]:
        try:
            r = requests.get(url, timeout=30, verify=False)
            good = r.status_code == 200
            print("  %-10s %s %s" % (label, r.status_code, r.headers.get("Content-Type", "")))
            ok = ok and good
        except Exception as error:
            print("  %-10s 失败 %s" % (label, error))
            ok = False
    cli, run = ssh(c)
    out = run("cd %s && rm -rf audio/_smoke && set -a && . ./.env && set +a && venv/bin/python -c "
              "\"import json,tts; r=tts.synthesize('_smoke','smoke','部署验收。这句用来确认云端语音链路是通的。',engine='auto'); "
              "print(json.dumps(r,ensure_ascii=False))\"" % c["remote_root"], timeout=240)
    print("  TTS: " + out[-260:])
    run("rm -rf %s/audio/_smoke" % c["remote_root"])
    cli.close()
    print("  访问地址：%s%s?token=%s" % (base, prefix, c["token"]))
    return ok


ACTIONS = {"upload": step_upload, "service": step_service, "nginx": step_nginx, "verify": step_verify}


def main(argv):
    what = argv[1] if len(argv) > 1 else "all"
    c = cfg()
    todo = ["upload", "service", "nginx", "verify"] if what == "all" else [what]
    for name in todo:
        if name not in ACTIONS:
            raise SystemExit("未知动作：%s（可选 %s / all）" % (name, " ".join(ACTIONS)))
        ACTIONS[name](c)
        print()
    print("完成。运维命令见 DEPLOY.md。")


if __name__ == "__main__":
    main(sys.argv)
