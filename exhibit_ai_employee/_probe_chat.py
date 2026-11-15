#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""真跑一遍「上传资料 → 联网对话」这条链：起临时服务、传文件、发一句话、等它自己查完。

不是夹具测试：这里真的会调模型、真的会去 Bing 搜。所以慢（几十秒）也是正常的。
用法：python _probe_chat.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = int(os.environ.get("CHAT_PROBE_PORT", "4215"))
BASE = "http://127.0.0.1:%d" % PORT

MATERIAL = """光的折射_展签资料

光从空气斜射入水中时，传播方向会发生偏折，这种现象叫作光的折射。

入射光线、折射光线和法线在同一平面内，折射光线与入射光线分居法线两侧。

光从空气进入水中时，折射角小于入射角；反过来，光从水中射向空气时，折射角大于入射角。

筷子斜插进有水的玻璃杯里，看上去像在水面处折断，就是折射造成的。

池水看起来比实际的浅，也是因为从池底反射的光在水面折射后进入眼睛。

如果光垂直射向水面，也就是入射角为零，传播方向不改变。

彩虹的形成与阳光在水滴中的折射和反射有关。
"""


def clean_env():
    env = os.environ.copy()
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH",
                "STUDIO_DB", "STUDIO_AUDIO_DIR", "STUDIO_HOST", "STUDIO_PORT"):
        env.pop(key, None)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def call(path, method="GET", body=None, raw=None, expect=200):
    url = BASE + path
    data = None
    headers = {}
    if raw is not None:
        data = raw
        headers["Content-Type"] = "application/octet-stream"
    elif body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            status = response.status
    except urllib.error.HTTPError as error:
        payload = json.loads(error.read().decode("utf-8") or "{}")
        status = error.code
    assert status == expect, "期望 %s 实际 %s：%s" % (expect, status, payload)
    return payload


def main():
    root = os.path.dirname(os.path.abspath(__file__))
    work = tempfile.mkdtemp(prefix="chat_probe_")
    env = clean_env()
    env["STUDIO_DB"] = os.path.join(work, "probe.sqlite3")
    env["STUDIO_AUDIO_DIR"] = os.path.join(work, "audio")
    env["STUDIO_PORT"] = str(PORT)
    env["STUDIO_HOST"] = "127.0.0.1"
    log = open(os.path.join(work, "server.log"), "wb")
    server = subprocess.Popen([sys.executable, "studio_server.py"], cwd=root, env=env,
                              stdout=log, stderr=subprocess.STDOUT)
    passed = []
    try:
        for _ in range(80):
            try:
                call("/api/studio/health", expect=200)
                break
            except Exception:
                time.sleep(0.25)
        health = call("/api/studio/health")
        print("health code=%s web=%s docs=%s agent=%s" % (
            health["code"], health["web"]["engine"], "pdf" in health["docs"]["formats"],
            health["agent"]))
        assert health["web"]["tools"] and health["docs"]["formats"]
        passed.append("health 带 web/docs/agent 状态")

        project = call("/api/studio/projects", "POST",
                       {"name": "联网测试项目", "audience": "亲子观众", "language": "中文"},
                       expect=201)["project"]
        pid = project["id"]
        print("project", pid, project["name"], project["status"])
        assert project["materials"] == [] and project["exhibits"] == []
        passed.append("建项目是空项目")

        uploaded = call("/api/studio/projects/%s/upload?name=%s" % (
            pid, urllib.request.quote("光的折射_展签资料.txt")), "POST",
            raw=MATERIAL.encode("utf-8"), expect=200)
        doc = uploaded["doc"]
        print("upload source=%s kind=%s chars=%s paras=%s" % (
            uploaded["source_id"], doc["kind"], doc["chars"], len(uploaded["project"]["sources"][-1]["paragraphs"])))
        assert doc["kind"].startswith("text") or doc["kind"] == "txt"
        assert len(uploaded["project"]["materials"]) == 1
        assert uploaded["project"]["materials"][0]["material"].startswith("光的折射")
        passed.append("上传 txt 收下并切段，materials 存正文")

        bad = call("/api/studio/projects/%s/upload?name=x.doc" % pid, "POST",
                   raw=b"\xd0\xcf\x11\xe0old office", expect=400)
        print("doc 拒绝:", bad["error"][:40])
        passed.append("老式 .doc 明确报错")

        os.environ["CHAT_PROBE_LAST_EVENT"] = ""
        state = call("/api/studio/projects/%s/events" % pid)
        last = state["events"][-1]["id"] if state["events"] else 0
        started = call("/api/studio/projects/%s/chat" % pid, "POST",
                       {"message": "帮我查一下光从空气进入水里为什么会折射，顺便看看我这份资料有没有说错的地方"},
                       expect=202)
        print("chat 202", started)
        passed.append("对话接口立刻 202，不阻塞界面")

        busy = None
        try:
            call("/api/studio/projects/%s/chat" % pid, "POST", {"message": "再来一句"}, expect=409)
            busy = True
        except AssertionError as error:
            busy = False
            print("第二次没被拦：", error)
        assert busy
        passed.append("上一句还没回完时第二次发消息被 409 拦下")

        reply = None
        tools = []
        deadline = time.time() + 180
        while time.time() < deadline:
            feed = call("/api/studio/projects/%s/events?after=%d" % (pid, last))
            for item in feed["events"]:
                last = item["id"]
                kind = item["kind"]
                detail = item.get("detail") or {}
                if kind == "chat.tool":
                    print("  tool", detail.get("state"), detail.get("tool"), "|", detail.get("message"))
                if kind == "chat.agent":
                    reply = detail
                    tools = detail.get("tools") or []
                    break
                if kind in ("chat.failed", "error"):
                    print("失败事件", detail)
            if reply:
                break
            time.sleep(1.5)
        assert reply, "等不到 chat.agent"
        text = reply.get("text") or ""
        print("\n--- 员工回话（%d 字）---\n%s\n" % (len(text), text))
        print("工具轨迹：", [(t["tool"], t["ok"]) for t in tools])
        assert text.strip()
        assert len(text) >= 20
        passed.append("拿到真实回话（%d 字，%d 次工具调用）" % (len(text), len(tools)))

        final = call("/api/studio/projects/%s" % pid)["project"]
        roles = [m["role"] for m in final["chat"]]
        assert roles[:2] == ["user", "agent"], roles
        assert final["chat"][-1].get("tools") is not None
        print("chat 记录：", [(m["role"], len(m.get("text") or "")) for m in final["chat"]])
        passed.append("对话记录落库（user/agent 各一条，带工具轨迹）")
    finally:
        try:
            server.terminate()
            server.wait(timeout=10)
        except Exception:
            pass
        log.close()
        print("\nserver.log 尾部：")
        with open(os.path.join(work, "server.log"), "rb") as fh:
            tail = fh.read().decode("utf-8", "replace").strip().splitlines()[-6:]
        for line in tail:
            print("  " + line)
        shutil.rmtree(work, ignore_errors=True)

    print("\n%d/%d 通过" % (len(passed), len(passed)))
    for item in passed:
        print("  PASS " + item)


if __name__ == "__main__":
    main()
