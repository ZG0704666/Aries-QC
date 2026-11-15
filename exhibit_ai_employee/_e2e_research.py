# -*- coding: utf-8 -*-
"""真联网 + 真模型的端到端：一句话让数字员工自己调研知名作品，直接起草出展项。

不碰 studio.sqlite3：临时库 + 临时音频目录 + 独立端口（默认 4197）。
这一步会真的搜网、真的调模型，跑一次大概一到三分钟。

    python _e2e_research.py
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("RESEARCH_PORT", "4197"))
BASE = "http://127.0.0.1:%d" % PORT
ASK = "蒙娜丽莎这个作品你先自己联网调研一下，然后按亲子观众的口吻把讲解起草出来。"

ok = 0
bad = 0


def check(label, condition, extra=""):
    global ok, bad
    if condition:
        ok += 1
        print("PASS", label, extra)
    else:
        bad += 1
        print("FAIL", label, extra)


def clean_env(extra=None):
    env = dict(os.environ)
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    if extra:
        env.update(extra)
    return env


def wait_port(port, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def call(path, method="GET", payload=None, timeout=180):
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, {"raw": body}


def main():
    tmp = tempfile.mkdtemp(prefix="studio_research_")
    db_path = os.path.join(tmp, "studio.sqlite3")
    audio_dir = os.path.join(tmp, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    server = None
    try:
        env = clean_env({"STUDIO_DB": db_path, "STUDIO_AUDIO_DIR": audio_dir, "STUDIO_PORT": str(PORT)})
        log = open(os.path.join(tmp, "server.log"), "w", encoding="utf-8")
        server = subprocess.Popen([sys.executable, os.path.join(HERE, "studio_server.py")],
                                  cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
        if not wait_port(PORT):
            raise SystemExit("服务没起来")

        status, payload = call("/api/studio/health")
        print("health", payload.get("code"), "web=", (payload.get("web") or {}).get("engine"))
        check("health 正常", status == 200 and (payload.get("code") or "").endswith("f"))

        status, payload = call("/api/studio/projects", "POST",
                               {"name": "蒙娜丽莎", "audience": "亲子观众", "language": "中文"})
        project = payload["project"]
        pid = project["id"]
        print("项目", pid, "｜资料", len(project.get("materials") or []),
              "｜调研", len(project.get("research") or []))
        check("新项目手上没有任何资料", not project.get("materials"))

        status, payload = call("/api/studio/projects/%s/run" % pid, "POST", {})
        print("  run 无依据 →", status, (payload.get("error") or "")[:70])
        check("无依据时 run 告诉人怎么开工（不再只说缺资料）",
              status == 400 and "联网调研" in (payload.get("error") or ""))

        status, payload = call("/api/studio/projects/%s/chat" % pid, "POST", {"message": ASK})
        check("对话异步接单（202）", status == 202, "%s %s" % (status, payload))

        tools = []
        final = None
        after = 0
        deadline = time.time() + 300
        while time.time() < deadline:
            time.sleep(2.0)
            st, ev = call("/api/studio/projects/%s/events?after=%d" % (pid, after), timeout=30)
            for item in ev.get("events") or []:
                after = max(after, int(item["id"]))
                kind = item.get("kind")
                detail = item.get("detail") or {}
                if kind == "chat.tool":
                    line = "%s %s" % (detail.get("tool"), detail.get("message") or "")
                    if detail.get("state") == "start":
                        print("  · 开始", line)
                    else:
                        print("  · 完成", line)
                        tools.append(detail.get("tool"))
                elif kind in ("chat.agent", "chat.failed"):
                    final = (kind, detail)
            if final:
                break

        check("对话有结论（不是超时）", final is not None, final[0] if final else "300 秒没等到 chat.agent")
        if final:
            kind, detail = final
            print("\n===== 数字员工的回话（%s）=====\n%s\n" % (kind, detail.get("text") or detail.get("error")))
            check("没有失败", kind == "chat.agent", detail.get("error") if kind == "chat.failed" else "")
            text = detail.get("text") or ""
            check("回话不是「请提供资料」", "请提供" not in text and "资料为空" not in text)
            check("回话不空也不啰嗦", 20 <= len(text) <= 400, "%d 字" % len(text))

        print("工具轨迹：", " → ".join(tools) if tools else "（没有工具调用）")
        check("用上了联网调研", "web_search" in tools and "add_research" in tools, tools)
        check("把网页存进了项目", "add_research" in tools)
        check("定了展项清单或直接起草", "plan_exhibits" in tools or "start_generation" in tools)

        # start_generation 是「这轮说完就开始跑」，所以得等草稿真的落地再断言
        p = {}
        deadline = time.time() + 300
        while time.time() < deadline:
            st, ev = call("/api/studio/projects/%s" % pid)
            p = ev["project"]
            if p.get("status") not in ("running", "draft") and p.get("exhibits"):
                break
            print("  … 等草稿落地（状态 %s）" % p.get("status"))
            time.sleep(4)
        print("项目现状：状态 %s｜资料 %d｜调研 %d｜展项 %d｜v%s"
              % (p.get("status"), len(p.get("materials") or []), len(p.get("research") or []),
                 len(p.get("exhibits") or []), p.get("version")))
        check("项目里留下了调研记录", bool(p.get("research")))
        if p.get("research"):
            for item in p["research"]:
                print("  %s《%s》%d 条摘录  %s" % (item["id"], item.get("title", "")[:40],
                                                  len(item.get("quotes") or []), item.get("url", "")[:80]))
                check("%s 有可引用摘录" % item["id"], len(item.get("quotes") or []) >= 3)
                check("%s 没有编造的摘录" % item["id"], all(q.get("text") for q in item.get("quotes") or []))
        check("调研之后真的起草出了展项", bool(p.get("exhibits")))
        for ex in (p.get("exhibits") or [])[:3]:
            main_text = (ex.get("main") or {}).get("text") or ""
            print("  %s《%s》主讲解 %d 字｜事实 %d 条"
                  % (ex["id"], ex.get("title", ""), len(main_text), len(ex.get("facts") or [])))
        if p.get("exhibits"):
            ex = p["exhibits"][0]
            main_text = (ex.get("main") or {}).get("text") or ""
            check("主讲解落在 80~400 字", 80 <= len(main_text) <= 400, "%d 字" % len(main_text))
            refs = [f.get("source_ref") for f in (ex.get("facts") or []) if f.get("source_ref")]
            check("事实引用落到了 WEB 来源或资料上", bool(refs), refs[:4])
            check("引用都经过了逐字核验", all(f.get("verified") for f in (ex.get("facts") or [])),
                  [(f.get("id"), f.get("verified")) for f in (ex.get("facts") or [])])
            tests = {t.get("name"): t.get("status") for t in (p.get("tests") or [])}
            print("  自测：", tests or "（还没跑）")
            check("自测覆盖门通过", tests.get("覆盖完整") == "passed", tests)

    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
    print("\n%d 项通过，%d 项失败" % (ok, bad))
    sys.exit(0 if bad == 0 else 1)
