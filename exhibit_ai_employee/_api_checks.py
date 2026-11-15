#!/usr/bin/env python3
"""Studio 新增接口回归：报价 / 讲解编辑 / 反馈 / 签收 / 静态资源。

这些能力是新增前端「实际接入后端」的底座——界面上的每个字段都必须落到项目上，
并且由服务端校验，而不是前端自己算完就当真。

跑法：python _api_checks.py
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("API_CHECK_PORT", "4211"))
BASE = "http://127.0.0.1:%d" % PORT
WORKDIR = tempfile.mkdtemp(prefix="studio_api_checks_")
DB_PATH = str(Path(WORKDIR) / "api.sqlite3")
AUDIO_DIR = str(Path(WORKDIR) / "audio")

PASSED = 0
FAILED = 0


def check(name, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print("PASS %s | %s" % (name, detail))
    else:
        FAILED += 1
        print("FAIL %s | %s" % (name, detail))


def clean_env():
    """剔掉批量测试里被继承的口令/端口，避免一条命令跑全量时互相串。"""
    env = dict(os.environ)
    for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH",
                "STUDIO_HOST", "STUDIO_PORT", "STUDIO_DB", "STUDIO_AUDIO_DIR"):
        env.pop(key, None)
    env["STUDIO_PORT"] = str(PORT)
    env["STUDIO_DB"] = DB_PATH
    env["STUDIO_AUDIO_DIR"] = AUDIO_DIR
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def request(method, path, payload=None, raw_body=None):
    url = BASE + path
    data = None
    if raw_body is not None:
        data = raw_body
    elif payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json; charset=utf-8")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read()
            ctype = response.headers.get("Content-Type", "")
            if "json" in ctype:
                return response.status, json.loads(body.decode("utf-8")), ctype
            return response.status, body, ctype
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            return error.code, json.loads(body.decode("utf-8")), error.headers.get("Content-Type", "")
        except (ValueError, UnicodeDecodeError):
            return error.code, body, error.headers.get("Content-Type", "")


def seed_project():
    """往临时库里塞一个带展项的项目，省掉一次真实模型流水线（慢且要花额度）。"""
    project = {
        "id": "fix01", "task_no": 1, "created_at": "2026-11-15T00:00:00+00:00",
        "name": "回归夹具", "audience": "亲子观众", "language": "中文",
        "status": "tested", "version": 0.2, "run_version": 1,
        "brief": {"text": "夹具", "at": "2026-11-15T00:00:00+00:00"},
        "authorization": {"confirmed_by": "林", "at": "2026-11-15T00:00:00+00:00", "scope": "项目内全部资料"},
        "demo": False,
        "materials": [{"id": "EX01", "title": "光的折射", "material": "a.txt"}],
        "sources": [{"id": "SRC-001", "name": "a.txt", "bytes": 10, "paragraphs": [
            {"id": "SRC-001·P001", "text": "光从一种介质斜射入另一种介质时，方向会发生改变，这就是折射。"}]}],
        "exhibits": [{
            "id": "EX01", "title": "光的折射", "material": "a.txt", "source_refs": ["SRC-001"],
            "facts": [{"id": "F-001", "text": "光斜射入另一种介质会改变方向",
                       "quote": "方向会发生改变", "source_ref": "SRC-001·P001", "verified": True}],
            "main": {"text": "把吸管放进水杯里，看起来像断成两截。光经过空气和水时方向会拐个弯，"
                             "我们的眼睛却以为它一直走直线，于是看到的位置就偏了。", "fact_ids": ["F-001"]},
            "simplified": {"text": "光从空气进入水里时方向会变。"},
            "followups": [{"q": "为什么看起来断了？", "a": "因为光的方向变了。"}],
            "fallback": [{"q": "这个多少钱？", "a": "现有资料没有提供价格。"}],
            "issues": [], "verified": True,
        }],
        "issues": [], "review": {"decision": "approved", "reviewer": "林",
                                 "at": "2026-11-15T00:00:00+00:00", "version": 0.2},
        "tests": [{"name": "覆盖完整", "status": "passed", "detail": "1/1"}],
        "voice": {"provider": "breeze", "status": "已合成音频"},
        "chat": [], "updated_at": "2026-11-15T00:00:00+00:00",
    }
    connection = sqlite3.connect(DB_PATH, timeout=20)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT, body TEXT)")
        connection.execute("INSERT OR REPLACE INTO projects(id,created_at,updated_at,body) VALUES(?,?,?,?)",
                           ("fix01", project["created_at"], project["updated_at"],
                            json.dumps(project, ensure_ascii=False)))
        connection.commit()
    finally:
        connection.close()


def wait_health(process, seconds=25):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            status, payload, _ = request("GET", "/api/studio/health")
            if status == 200 and payload.get("ok"):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def main():
    ok = True
    for name in ("audio",):
        Path(WORKDIR, name).mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT, body TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, created_at TEXT, kind TEXT, detail TEXT)")
    connection.execute("CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, created_at TEXT, elapsed_ms INTEGER, outcome TEXT, usage TEXT)")
    connection.commit()
    connection.close()
    seed_project()

    log = open(Path(WORKDIR) / "server.log", "wb")
    process = subprocess.Popen([sys.executable, "studio_server.py"], cwd=str(ROOT),
                               env=clean_env(), stdout=log, stderr=subprocess.STDOUT)
    try:
        if not wait_health(process):
            print("FAIL 服务未能启动，检查 %s" % (Path(WORKDIR) / "server.log"))
            return 1

        # ---- 静态资源
        status, body, ctype = request("GET", "/assets/atelier.css")
        check("静态样式表可访问", status == 200 and "text/css" in ctype and len(body) > 1000,
              "%s %s %d 字节" % (status, ctype, len(body)))
        status, body, _ = request("GET", "/assets/../../studio_server.py")
        check("静态路径不能穿越到源码", status == 404, "status=%s" % status)
        status, body, _ = request("GET", "/nope.css")
        check("不存在的接口回 404 JSON", status == 404 and isinstance(body, dict), "status=%s" % status)

        # ---- 报价
        status, payload, _ = request("GET", "/api/studio/projects/fix01")
        project = payload["project"]
        check("老项目自动补齐三张附表",
              project.get("quote") is None and project.get("feedbacks") == [] and project.get("acceptance") is None,
              "quote=%s feedbacks=%s acceptance=%s" % (project.get("quote"), project.get("feedbacks"), project.get("acceptance")))

        status, payload, _ = request("POST", "/api/studio/projects/fix01/quote",
                                     {"customer": "亲子展厅集成商", "reviewer": "王老师", "audience": "亲子观众",
                                      "scope": "一个展厅 · 最多 3 个展项", "duration": 45,
                                      "price": 3000, "labor": 1200, "models": 150, "other": 150,
                                      "contribution": 999999})
        quote = payload.get("quote") if isinstance(payload, dict) else None
        check("保存报价并持久化", status == 200 and quote and quote["customer"] == "亲子展厅集成商"
              and quote["price"] == 3000, "status=%s quote=%s" % (status, quote))
        check("成本与贡献由服务端算，不采信前端传的 contribution",
              quote and quote["cost"] == 1500 and quote["contribution"] == 1500,
              "cost=%s contribution=%s" % (quote and quote["cost"], quote and quote["contribution"]))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/quote", {"price": -5})
        check("负数金额被拒", status == 400 and "必须是" in payload.get("error", ""), "status=%s %s" % (status, payload.get("error")))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/quote", {"confirm": True, "scope": ""})
        check("确认范围缺字段被拒", status == 400 and "服务范围" in payload.get("error", ""), "status=%s %s" % (status, payload.get("error")))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/quote", {"confirm": True})
        check("补齐后可确认范围", status == 200 and payload["quote"]["confirmed"] is True,
              "status=%s confirmed=%s" % (status, payload.get("quote", {}).get("confirmed")))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/quote", raw_body=b"\xff\xfe not json")
        check("坏 JSON 回 400 而不是静默清空", status == 400, "status=%s" % status)

        # ---- 反馈
        status, payload, _ = request("POST", "/api/studio/projects/fix01/feedback", {"problem": "短"})
        check("过短的反馈被拒", status == 400, "status=%s" % status)
        status, payload, _ = request("POST", "/api/studio/projects/fix01/feedback",
                                     {"problem": "观众说讲得太快跟不上", "exhibit_id": "EX01"})
        entry = payload.get("feedback") if isinstance(payload, dict) else None
        check("记录反馈并编号", status == 200 and entry and entry["id"] == "FB-001" and entry["state"] == "recorded",
              "status=%s %s" % (status, entry))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/feedback",
                                     {"op": "candidate", "feedback_id": "FB-001"})
        check("登记候选必须写清改成什么", status == 400 and "写明" in payload.get("error", ""),
              "status=%s %s" % (status, payload.get("error")))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/feedback",
                                     {"op": "candidate", "feedback_id": "FB-001", "suggestion": "我们把语速放慢一点"})
        check("候选可登记", status == 200 and payload["feedback"]["state"] == "candidate",
              "status=%s state=%s" % (status, payload.get("feedback", {}).get("state")))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/feedback",
                                     {"op": "candidate", "feedback_id": "FB-999", "suggestion": "x"})
        check("不存在的反馈回 404", status == 404, "status=%s" % status)

        # ---- 签收（必须在发布之后）
        status, payload, _ = request("POST", "/api/studio/projects/fix01/acceptance",
                                     {"signer": "王老师", "decision": "accepted"})
        check("未发布不能登记签收", status == 403 and "已发布" in payload.get("error", ""),
              "status=%s %s" % (status, payload.get("error")))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/publish")
        check("审核与自测齐备后可发布", status == 200 and payload["project"]["status"] == "published",
              "status=%s %s" % (status, payload.get("project", {}).get("status")))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/acceptance",
                                     {"signer": "王老师", "decision": "accepted", "note": "现场确认"})
        record = payload.get("acceptance") if isinstance(payload, dict) else None
        check("发布后可登记签收", status == 200 and record and record["signer"] == "王老师",
              "status=%s %s" % (status, record))

        # ---- 讲解改写
        status, payload, _ = request("POST", "/api/studio/projects/fix01/exhibit",
                                     {"exhibit_id": "EX01", "text": "太短"})
        check("过短的主讲解被拒", status == 400, "status=%s" % status)
        status, payload, _ = request("POST", "/api/studio/projects/fix01/exhibit",
                                     {"exhibit_id": "EX09", "text": "这是一段足够长的讲解文本，用来验证展项不存在时的报错。"})
        check("不存在的展项回 404", status == 404, "status=%s" % status)
        new_text = ("把一根吸管斜插进水杯，看起来像断成两截。光从空气进入水时方向会拐弯，"
                    "眼睛却以为光一直走直线，所以看到的位置比实际的偏上。")
        status, payload, _ = request("POST", "/api/studio/projects/fix01/exhibit",
                                     {"exhibit_id": "EX01", "text": new_text})
        project = payload.get("project", {}) if isinstance(payload, dict) else {}
        exhibit = (project.get("exhibits") or [{}])[0]
        check("主讲解可改写并落地", status == 200 and exhibit.get("main", {}).get("text") == new_text,
              "status=%s 字数=%d" % (status, len(exhibit.get("main", {}).get("text", ""))))
        check("改写后版本 +0.1、旧测试与审核失效、状态退回待确认",
              project.get("version") == 0.3 and project.get("tests") == [] and project.get("review") is None
              and project.get("status") == "awaiting_confirmation",
              "version=%s tests=%s review=%s status=%s" % (
                  project.get("version"), project.get("tests"), project.get("review"), project.get("status")))
        status, payload, _ = request("POST", "/api/studio/projects/fix01/exhibit",
                                     {"exhibit_id": "EX01", "text": new_text})
        check("内容没变化时拒绝覆盖", status == 400 and "没有变化" in payload.get("error", ""),
              "status=%s %s" % (status, payload.get("error")))

        # ---- 事件流要能查到上面这些动作
        status, payload, _ = request("GET", "/api/studio/projects/fix01/events?after=0")
        kinds = {event["kind"] for event in payload.get("events", [])}
        check("报价/反馈/签收/改写都进了事件流",
              {"quote", "feedback", "acceptance", "exhibit"} <= kinds, "kinds=%s" % sorted(kinds))
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        log.close()
        ok = FAILED == 0

    print("\n%d/%d 通过" % (PASSED, PASSED + FAILED))
    print("临时目录：%s" % WORKDIR)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
