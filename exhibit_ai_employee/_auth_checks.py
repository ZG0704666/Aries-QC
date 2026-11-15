"""鉴权回归：验证 studio_server 的访问口令真的在拦，且护栏不会把本机开发卡死。

和 _audit_checks.py 一样是「故意做错」的对抗测试，区别是这里走真实 HTTP：
口令这种事只有从外部发请求才测得出来，直接调函数测不出中间件漏挂。

隔离措施：
  · 每个用例都用临时库（STUDIO_DB），不碰 studio.sqlite3；
  · 服务进程用独立端口（4201/4202），不影响正在跑的 4182；
  · 子进程环境里显式删除继承来的口令变量，避免本机环境变量导致用例假通过。
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, ".")
HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "studio_server.py")
TOKEN = "check-token-9f3a"
results = []


def record(ok, name, detail):
    results.append((ok, name, detail))


def wait_port(port, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.15)
    return False


def request(port, path, method="GET", token_header=None, body=None, query_token=None):
    url = "http://127.0.0.1:%d%s" % (port, path)
    if query_token:
        url += ("&" if "?" in url else "?") + "token=" + query_token
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token_header:
        headers["X-Access-Token"] = token_header
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except Exception as error:  # 连接被拒等
        return None, str(error).encode()


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH",
                        "STUDIO_HOST", "STUDIO_PORT", "STUDIO_DB")}
    env.update(extra)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class Server:
    def __init__(self, port, **env_extra):
        self.port = port
        self.db = os.path.join(tempfile.gettempdir(), "studio_auth_%d.sqlite3" % port)
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(self.db + suffix)
            except OSError:
                pass
        self.proc = subprocess.Popen(
            [sys.executable, SERVER],
            env=clean_env(STUDIO_PORT=str(port), STUDIO_DB=self.db,
                          STUDIO_HOST="127.0.0.1", **env_extra),
            cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def up(self):
        return wait_port(self.port)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main():
    # ---------- 场景一：配置了口令 ----------
    server = Server(4201, STUDIO_ACCESS_TOKEN=TOKEN)
    if not server.up():
        out, err = server.proc.communicate(timeout=5)
        print("服务未能启动：\n" + err.decode("utf-8", "replace"))
        return 1
    try:
        status, body = request(4201, "/")
        record(status == 200 and b"<html" in body.lower(), "静态页无需口令即可打开",
               "status=%s bytes=%d" % (status, len(body)))

        status, body = request(4201, "/api/studio/health")
        record(status == 401, "无口令读接口应被拒", "status=%s body=%s" % (status, body[:80]))

        status, body = request(4201, "/api/studio/health", token_header=TOKEN)
        health = json.loads(body) if status == 200 else {}
        record(status == 200 and health.get("auth_required") is True,
               "带 X-Access-Token 头应放行且声明需要口令",
               "status=%s auth_required=%s" % (status, health.get("auth_required")))

        status, _ = request(4201, "/api/studio/health", query_token=TOKEN)
        record(status == 200, "URL 上带 ?token= 应放行（给 audio/下载用）", "status=%s" % status)

        status, _ = request(4201, "/api/studio/health", token_header=TOKEN + "x")
        record(status == 401, "错误口令应被拒", "status=%s" % status)

        status, _ = request(4201, "/api/studio/health", query_token="")
        record(status == 401, "空 token 参数不得当作通过", "status=%s" % status)

        status, body = request(4201, "/api/studio/projects/7e1c974ff8/run", method="POST", body={})
        record(status == 401, "无口令不得触发生成（会烧模型额度）",
               "status=%s body=%s" % (status, body[:80]))

        status, body = request(4201, "/api/studio/projects/7e1c974ff8/publish", method="POST", body={})
        record(status == 401, "无口令不得触发发布", "status=%s" % status)

        status, body = request(4201, "/api/studio/projects/7e1c974ff8/authorize",
                               method="POST", token_header=TOKEN, body={"confirmed_by": "checker"})
        record(status in (200, 404), "带口令的写操作应通过鉴权（业务错误不等于鉴权错误）",
               "status=%s body=%s" % (status, body[:80]))

        # 口令不得出现在静态页里
        status, body = request(4201, "/")
        record(TOKEN.encode() not in body, "口令不得泄漏进静态页", "found=%s" % (TOKEN.encode() in body))
    finally:
        server.stop()

    # ---------- 场景二：未配置口令 + 监听非本机 → 必须拒绝启动 ----------
    proc = subprocess.run(
        [sys.executable, SERVER],
        env=clean_env(STUDIO_PORT="4202", STUDIO_HOST="0.0.0.0",
                      STUDIO_DB=os.path.join(tempfile.gettempdir(), "studio_auth_guard.sqlite3")),
        cwd=HERE, capture_output=True, timeout=30)
    text = (proc.stderr + proc.stdout).decode("utf-8", "replace")
    record(proc.returncode != 0 and "拒绝启动" in text,
           "裸奔监听非本机时应拒绝启动", "returncode=%s" % proc.returncode)

    # ---------- 场景三：未配置口令 + 本机监听 → 放行（本机开发不受影响）----------
    server = Server(4203)
    started = server.up()
    server.stop()
    record(started, "本机监听且未配口令时仍可启动（本机开发不被卡死）", "started=%s" % started)

    # ---------- 场景四：显式逃生阀 ----------
    proc = subprocess.run(
        [sys.executable, "-c",
         "import os,sys;sys.path.insert(0,'.');"
         "os.environ['STUDIO_HOST']='0.0.0.0';os.environ['STUDIO_ALLOW_NO_AUTH']='1';"
         "os.environ['STUDIO_PORT']='4204';"
         "import studio_server as S;"
         "print('LOOPBACK', S.is_loopback('127.0.0.1'), S.is_loopback('0.0.0.0'), S.is_loopback('::1'))"],
        env=clean_env(), cwd=HERE, capture_output=True, timeout=30)
    text = proc.stdout.decode("utf-8", "replace")
    record("LOOPBACK True False True" in text, "is_loopback 判定正确（::1 也算本机）", text.strip()[:80])

    print()
    fails = 0
    for ok, name, detail in results:
        print(("PASS " if ok else "FAIL ") + name + " | " + detail)
        if not ok:
            fails += 1
    print("\n%d/%d 通过" % (len(results) - fails, len(results)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
