#!/usr/bin/env python3
"""展览互动内容制作员 · 本地服务
静态页：GET /            （studio_web.html）
接口：  /api/studio/*
数据：  studio.sqlite3（项目、事件、调用记录）
模型：  通过 .env.local 的 AI_BASE_URL / AI_MODEL / DEEPSEEK_API_KEY 调用
"""
import hashlib
import hmac
import io
import ipaddress
import json
import os
import re
import sqlite3
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import docread
import websearch

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("STUDIO_DB", ROOT / "studio.sqlite3"))
HOST = os.environ.get("STUDIO_HOST", "127.0.0.1")
PORT = int(os.environ.get("STUDIO_PORT", "4182"))
# 访问口令。Studio 这套此前完全没有鉴权：一旦监听非本机地址，任何人都能调生成、
# 审批、发布并烧掉模型与 Breeze 额度。这里与 app.py 用同一个变量名，便于一套口令管两套服务。
ACCESS_TOKEN = (os.environ.get("STUDIO_ACCESS_TOKEN") or os.environ.get("ACCESS_TOKEN") or "").strip()


def is_loopback(host):
    """判断监听地址是否只对本机可见。用于决定「没配口令」能不能放行。"""
    host = (host or "").strip().strip("[]").lower()
    if host in ("", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def load_local_env():
    path = ROOT / ".env.local"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
API_BASE = os.environ.get("AI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
API_KEY = os.environ.get("AI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
MODEL = os.environ.get("AI_MODEL", "deepseek-chat")
CODE_REV = "studio-2026-11-15-o"

# 本地 TTS 模块：放在 load_local_env() 之后导入，使 .env.local 里的音色配置能生效。
import tts  # noqa: E402


def now():
    return datetime.now(timezone.utc).isoformat()


def db():
    connection = sqlite3.connect(DB_PATH, timeout=20, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=20000")
    return connection


def initialize():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT, body TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, created_at TEXT, kind TEXT, detail TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, created_at TEXT, elapsed_ms INTEGER, outcome TEXT, usage TEXT)")


def event(project_id, kind, detail=None):
    with db() as c:
        c.execute("INSERT INTO events(project_id,created_at,kind,detail) VALUES(?,?,?,?)",
                  (project_id, now(), kind, json.dumps(detail or {}, ensure_ascii=False)))


def load(project_id):
    with db() as c:
        row = c.execute("SELECT body FROM projects WHERE id=?", (project_id,)).fetchone()
    if not row:
        raise KeyError("项目不存在")
    project = json.loads(row["body"])
    # 老项目里没有这几张附表；在这里补默认值，前端就不必到处判 None
    project.setdefault("quote", None)
    project.setdefault("feedbacks", [])
    project.setdefault("acceptance", None)
    return project


def save(project):
    project["updated_at"] = now()
    with db() as c:
        c.execute("INSERT OR REPLACE INTO projects(id,created_at,updated_at,body) VALUES(?,?,?,?)",
                  (project["id"], project["created_at"], project["updated_at"],
                   json.dumps(project, ensure_ascii=False)))


class ModelError(Exception):
    pass


def model_json(messages, project_id="-", max_tokens=4000, retries=2):
    if not API_KEY:
        raise ModelError("未配置模型凭据（AI_API_KEY / DEEPSEEK_API_KEY）")
    body = {
        "model": MODEL, "messages": messages, "temperature": 0.2,
        "response_format": {"type": "json_object"}, "max_tokens": max_tokens,
    }
    started = time.monotonic()
    outcome, usage = "failed", {}
    try:
        for attempt in range(retries + 1):
            request = urllib.request.Request(
                API_BASE + "/chat/completions",
                data=json.dumps(body, ensure_ascii=False).encode(),
                headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    result = json.load(response)
                usage = result.get("usage", {})
                content = result["choices"][0]["message"]["content"]
                outcome = "success"
                return json.loads(content)
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as error:
                if attempt >= retries:
                    raise ModelError("%s: %s" % (type(error).__name__, error)) from error
                time.sleep(1.5 * (attempt + 1))
    finally:
        elapsed = int((time.monotonic() - started) * 1000)
        with db() as c:
            c.execute("INSERT INTO calls(project_id,created_at,elapsed_ms,outcome,usage) VALUES(?,?,?,?,?)",
                      (project_id, now(), elapsed, outcome, json.dumps(usage)))


def model_chat(messages, tools=None, project_id="-", max_tokens=1600, retries=2, temperature=0.55):
    """一对一对话调用（自由文本，可带工具）。返回 assistant message 原文。

    与 model_json 的区别：不强制 JSON —— 聊天要说得像人话，套 JSON 会把它变成填空题。
    """
    if not API_KEY:
        raise ModelError("未配置模型凭据（AI_API_KEY / DEEPSEEK_API_KEY）")
    body = {"model": MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    started = time.monotonic()
    outcome, usage = "failed", {}
    try:
        for attempt in range(retries + 1):
            request = urllib.request.Request(
                API_BASE + "/chat/completions",
                data=json.dumps(body, ensure_ascii=False).encode(),
                headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    result = json.load(response)
                usage = result.get("usage", {})
                message = result["choices"][0]["message"] or {}
                outcome = "success"
                return message
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, KeyError) as error:
                if attempt >= retries:
                    raise ModelError("%s: %s" % (type(error).__name__, error)) from error
                time.sleep(1.5 * (attempt + 1))
    finally:
        elapsed = int((time.monotonic() - started) * 1000)
        with db() as c:
            c.execute("INSERT INTO calls(project_id,created_at,elapsed_ms,outcome,usage) VALUES(?,?,?,?,?)",
                      (project_id, now(), elapsed, outcome, json.dumps(usage)))


SENTENCE = re.compile(r"[^。！？；\n]+[。！？；]?")


def similarity(first, second):
    """字符级相似度，用于判断引用是否只是轻微改写。"""
    import difflib
    return difflib.SequenceMatcher(None, first, second).ratio()


def repair_quote(quote, paragraph):
    """引用与原文只差个别字时，取原文中覆盖该引用的完整句子，保证交付稿里是逐字原文。
    返回 (修复后的原文句子, 是否发生了修复)。"""
    if not quote or quote in paragraph:
        return quote, False
    import difflib
    match = difflib.SequenceMatcher(None, quote, paragraph).find_longest_match(0, len(quote), 0, len(paragraph))
    if match.size < max(8, int(len(quote) * 0.8)):
        return quote, False
    start, end = match.b, match.b + match.size
    while start > 0 and paragraph[start - 1] not in "。！？；\n":
        start -= 1
    while end < len(paragraph) and paragraph[end - 1] not in "。！？；\n":
        end += 1
    return paragraph[start:end].strip(), True


SYSTEM_PROMPT = """你是博物馆/科技馆的「展览互动内容制作员」。你把给定的来源（馆方资料或联网调研的网页摘录）改写成现场可用的中文讲解内容，面向亲子观众。
硬性要求：
1. 只能使用给定来源中的事实。不得补充来源里没有的数据、年份、人名、机构名。
2. 每条事实必须给出原文逐字引用 quote：从来源段落里原样复制一整句，逐字符一致，包括标点，不得增删改一个字，也不得拼接两个不相邻的句子。quote 必须能在标注的 [编号] 正文里做到字符串精确匹配。source_ref 写该段落的完整编号：资料段落形如 SRC-001·P003，网页摘录形如 WEB-001·Q002。
3. 讲解要口语化、适合对着观众说，控制在约 45 秒（中文约 140~170 字）。
4. 严格输出 JSON，不要任何解释文字。
JSON 结构：
{"exhibit_id":"EX01","title":"...",
 "facts":[{"id":"F-001","text":"事实陈述","quote":"原文逐字句","source_ref":"SRC-001·P002"}],
 "main":{"text":"主讲解全文","fact_ids":["F-001"]},
 "simplified":{"text":"给儿童的一句话版本，60字内"},
 "followups":[{"q":"观众可能追问的问题","a":"据资料回答"}],
 "fallback":[{"q":"资料之外的常见问题","a":"如实说明资料未覆盖，并建议现场工作人员补充"}]}
facts 给 3~6 条；followups 2~3 条；fallback 1~2 条。特别注意：quote 字段必须是资料原文的字符串切片，宁可 quote 长一点，也不要为了通顺改动任何一个字。"""


def build_sources(materials):
    """把资料切成带编号的段落，作为可逐字定位的来源。"""
    sources = []
    for index, material in enumerate(materials, start=1):
        src_id = "SRC-%03d" % index
        paragraphs = []
        for para in re.split(r"\n\s*\n|\n", material["text"]):
            para = para.strip()
            if len(para) < 8:
                continue
            paragraphs.append({"id": src_id + "·P%03d" % (len(paragraphs) + 1), "text": para})
        sources.append({
            "id": src_id, "name": material["name"], "bytes": len(material["text"].encode()),
            "paragraphs": paragraphs,
        })
    return sources


def research_index(project):
    """把联网调研档案摊平成和资料一样的形状：一条网页 = 一个来源，摘录 = 段落。

    为什么要统一形状：verify / 自测门 / 交付导出都要按「引用能不能在来源正文里
    逐字找到」来判，资料和网页摘录除了编号前缀没有区别，不该各写一套校验。
    """
    items = []
    for entry in project.get("research") or []:
        items.append({
            "id": entry["id"],
            "name": entry.get("title") or entry.get("url") or "",
            "url": entry.get("url") or "",
            "kind": "web",
            "paragraphs": list(entry.get("quotes") or []),
        })
    return items


def all_sources(project):
    """本轮可用的全部来源：员工上传的资料 + 联网调研的网页摘录。"""
    return list(project.get("sources") or []) + research_index(project)


def _norm_space(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def add_research(project, url, text, title="", quotes=None, query=""):
    """登记一条联网调研，返回 (来源编号, 保留摘录数, 丢弃数)。

    quotes 里每条都要能在页面正文里原样找到，找不到的直接丢掉——
    宁可少一条摘录，也不让改写过的句子混进「原文引用」。
    """
    body = _norm_space(text)
    if len(body) < 120:
        raise ValueError("这页只抓到 %d 字正文，太短，换一页。" % len(body))
    existing = {entry["id"] for entry in project.get("research") or []}
    number = 1
    while "WEB-%03d" % number in existing:
        number += 1
    web_id = "WEB-%03d" % number

    kept, dropped = [], 0
    candidates = [_norm_space(item) for item in (quotes or []) if _norm_space(item)]
    for quote in candidates:
        if quote in body:
            kept.append(quote)
        else:
            dropped += 1
    # 模型挑的句子若只命中一两条，就从正文补足；宁可多几条可引用的整句，
    # 也不要让一个展项只挂一条事实（知识卡门要求每个展项至少 2 条）。
    if len(kept) < 3:
        for sentence in SENTENCE.findall(body):
            sentence = sentence.strip()
            if len(sentence) >= 14 and _norm_space(sentence) not in [_norm_space(k) for k in kept]:
                kept.append(sentence)
            if len(kept) >= 6:
                break
    if not kept:
        raise ValueError("这页没有可用的整句摘录。")

    # 页面标题常常已经带书名号（《蒙娜丽莎》），界面上又包了一层，先剥掉再存。
    clean_title = _norm_space(title).strip("《》「」\"' ").strip() or url
    project.setdefault("research", []).append({
        "id": web_id, "url": url, "title": clean_title[:120], "query": str(query or "")[:120],
        "retrieved_at": now(), "chars": len(body),
        "quotes": [{"id": "%s·Q%03d" % (web_id, index), "text": item}
                   for index, item in enumerate(kept[:20], start=1)],
    })
    return web_id, len(kept[:20]), dropped


def exhibit_units(project):
    """这一轮要起草哪几个展项。

    有资料就一份资料一个展项（老口径不变）；没资料但有调研记录时按展项清单
    来，清单也没定就用项目名兜一个——知名作品不需要员工先上传资料。
    """
    materials = project.get("materials") or []
    if materials:
        return [dict(item) for item in materials]
    plan = project.get("plan") or []
    if plan:
        return [{"id": item.get("id") or "EX%02d" % (index + 1), "title": item.get("title") or ""}
                for index, item in enumerate(plan)]
    research = project.get("research") or []
    if research:
        title = project.get("name") or research[0].get("title") or "展项"
        return [{"id": "EX01", "title": str(title)[:60]}]
    return []


def find_exhibit(project, exhibit_id):
    for item in project.get("exhibits", []):
        if item["id"] == exhibit_id:
            return item
    raise KeyError(exhibit_id)


def verify(project, exhibit):
    """逐字校验：quote 必须能在其来源资料中原样出现。
    来源编号可以是段落级（SRC-001·P002 / WEB-001·Q003）或来源级（SRC-001 / WEB-001）；
    来源级时只在同一份来源内自动定位段落，绝不跨展项找。"""
    source_map = {src["id"]: src for src in all_sources(project)}
    issues = []
    facts = []
    for fact in exhibit.get("facts", []):
        quote = str(fact.get("quote", "")).strip()
        ref = str(fact.get("source_ref", "")).strip()
        source = source_map.get(ref.split("·")[0])
        para = None
        repaired = False
        if source and quote:
            for item in source["paragraphs"]:
                if item["id"] == ref and quote in item["text"]:
                    para = item
                    break
            if para is None:
                for item in source["paragraphs"]:
                    candidate, did_repair = repair_quote(quote, item["text"])
                    if did_repair and candidate in item["text"]:
                        quote, repaired = candidate, True
                        para, ref = item, item["id"]
                        break
            if para is None:
                for item in source["paragraphs"]:
                    if quote in item["text"]:
                        para, ref = item, item["id"]
                        break
        verified = para is not None
        fact = dict(fact)
        fact["verified"] = verified
        fact["quote"] = quote
        if verified:
            fact["source_ref"] = ref
            if repaired:
                fact["repaired"] = True
        facts.append(fact)
        if not verified:
            issues.append({
                "id": "IS-" + (fact.get("id") or uuid.uuid4().hex[:6]) + "-" + exhibit["id"],
                "exhibit_id": exhibit["id"], "fact_id": fact.get("id"),
                "title": "原文引用无法逐字定位",
                "detail": "这条事实标注的来源 %s 中找不到逐字引用，可能被模型改写或跨展项串台。"
                          % (ref or "（空）"),
                "quote": quote, "source_ref": ref,
                "created_at": now(),
                "actions": ["补充资料", "删除该事实"],
            })
    exhibit["facts"] = facts
    exhibit["issues"] = issues
    exhibit["verified"] = all(f["verified"] for f in facts) and bool(facts)
    return exhibit


def generate_exhibit(project, unit, index, research_mode):
    """生成一个展项。整批与单个共用这一条路径，保证行为一致。

    返回生成并校验后的展项；模型失败时把项目置 failed 并返回 None。
    """
    project_id = project["id"]
    exhibit = dict(unit)
    event(project_id, "step", {"step": "cards", "state": "running", "label": "知识卡",
                               "detail": "正在处理 %s %s" % (exhibit["id"], exhibit.get("title", ""))})
    own = None if research_mode else (
        project["sources"][index] if index < len(project.get("sources", [])) else None)
    pool = [own] if own else all_sources(project)
    context = ""
    for source in pool:
        for para in source["paragraphs"]:
            context += "[%s] %s\n" % (para["id"], para["text"])
    context = context[:12000]
    exhibit["source_refs"] = [source["id"] for source in pool]
    hint = ("资料段落（只能引用这里的 [编号]）：" if own else
            "来源段落（员工资料 SRC-… 与联网摘录 WEB-… 混排，只能引用这里的 [编号]）：")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content":
            "展项编号：%s\n展项名称：%s\n观众：%s\n\n%s\n%s\n\n请为这个展项输出 JSON。"
            % (exhibit["id"], exhibit.get("title", ""), project.get("audience", "亲子观众"),
               hint, context)},
    ]
    try:
        data = model_json(messages, project_id, max_tokens=4000)
    except ModelError as error:
        event(project_id, "error", {"message": "模型调用失败：" + str(error)})
        project["status"] = "failed"
        project["error"] = str(error)
        save(project)
        return None
    item = dict(exhibit)
    item.update({
        "title": str(data.get("title") or exhibit["title"])[:60],
        "facts": data.get("facts") or [],
        "main": data.get("main") or {"text": ""},
        "simplified": data.get("simplified") or {"text": ""},
        "followups": data.get("followups") or [],
        "fallback": data.get("fallback") or [],
    })
    if not item["main"].get("text"):
        item["issues"] = [{"id": "IS-EMPTY-" + exhibit["id"], "exhibit_id": exhibit["id"],
                           "title": "没有生成主讲解", "detail": "模型返回的主讲解为空，需要重新生成。",
                           "actions": ["重新生成", "补充资料"]}]
        item["verified"] = False
    else:
        item = verify(project, item)
    event(project_id, "step", {"step": "cards", "state": "done", "label": "知识卡",
                               "detail": "%s：%d 条事实，%d 处待核验" % (
                                   item["id"], len(item["facts"]), len(item.get("issues", [])))})
    return item


def run_single_exhibit(project_id, exhibit_id):
    """只重新生成一个展项，其余展项原样保留。

    与整批一样：版本 +0.1、自测重跑、审核失效（内容变了旧签名就不能再用）。
    """
    def work():
        try:
            project = load(project_id)
            units = exhibit_units(project)
            target = None
            index = 0
            for i, unit in enumerate(units):
                if unit["id"] == exhibit_id:
                    target = unit
                    index = i
                    break
            if target is None:
                project["status"] = "failed"
                project["error"] = "展项不在本轮清单里：" + exhibit_id
                save(project)
                event(project_id, "error", {"message": project["error"]})
                return
            project["status"] = "running"
            project["run_version"] = project.get("run_version", 0) + 1
            project["version"] = round(project.get("version", 0) + 0.1, 1)
            project["review"] = None
            save(project)
            research_mode = not (project.get("materials") or [])
            item = generate_exhibit(project, target, index, research_mode)
            if item is None:
                return
            replaced = False
            for i, old in enumerate(project.get("exhibits", [])):
                if old["id"] == exhibit_id:
                    project["exhibits"][i] = item
                    replaced = True
                    break
            if not replaced:
                project.setdefault("exhibits", []).append(item)
            project["issues"] = [issue for draft in project["exhibits"] for issue in draft.get("issues", [])]
            project["tests"] = content_tests(project)
            failed = [row for row in project["tests"] if row.get("status") != "passed"]
            project["status"] = "awaiting_confirmation" if (project["issues"] or failed) else "tested"
            save(project)
            event(project_id, "run.finished", {
                "message": "%s 已重新生成；自测 %d/%d 通过" % (
                    exhibit_id, len(project["tests"]) - len(failed), len(project["tests"])),
                "exhibit_id": exhibit_id})
        except Exception as error:
            traceback.print_exc()
            try:
                project = load(project_id)
                project["status"] = "failed"
                project["error"] = "%s: %s" % (type(error).__name__, error)
                save(project)
            except Exception:
                pass
            event(project_id, "error", {"message": "单展项生成异常：" + str(error)})

    threading.Thread(target=work, daemon=True).start()


def run_pipeline(project_id):
    def work():
        try:
            project = load(project_id)
            project["status"] = "running"
            project["run_version"] = project.get("run_version", 0) + 1
            project["version"] = project.get("version", 0) + 0.1
            project["version"] = round(project["version"], 1)
            project["exhibits"] = []
            project["issues"] = []
            save(project)

            steps = [
                ("receive", "资料接收", "读取授权资料并登记来源"),
                ("locate", "来源定位", "把资料切成可逐字定位的段落"),
                ("cards", "知识卡", "抽取可核验的事实条目"),
                ("draft", "讲解与问答", "生成主讲解、简化版与追问"),
            ]
            event(project_id, "step", {"step": "receive", "state": "done", "label": "资料接收",
                                       "detail": "共 %d 份资料" % len(project.get("sources", []))})
            event(project_id, "step", {"step": "locate", "state": "done", "label": "来源定位",
                                       "detail": "%d 个可定位段落" % sum(len(s["paragraphs"]) for s in project.get("sources", []))})

            units = exhibit_units(project)
            if not units:
                project["status"] = "failed"
                project["error"] = "没有可用的内容依据"
                save(project)
                event(project_id, "error", {"message": "还没有可用的内容依据：先联网调研，或导入资料。"})
                return
            research_mode = not (project.get("materials") or [])
            drafts = []
            for index, unit in enumerate(units):
                item = generate_exhibit(project, unit, index, research_mode)
                if item is None:
                    return
                drafts.append(item)
                project["exhibits"] = drafts
                project["issues"] = [issue for draft in drafts for issue in draft.get("issues", [])]
                save(project)

            # 起草完顺手把自测跑掉：质量门是系统自己的事，不该让员工再点一次按钮。
            project["tests"] = content_tests(project)
            failed = [row for row in project["tests"] if row.get("status") != "passed"]
            project["status"] = "awaiting_confirmation" if (project["issues"] or failed) else "tested"
            save(project)
            event(project_id, "step", {"step": "draft", "state": "done", "label": "讲解与问答",
                                       "detail": "共 %d 个展项草稿" % len(project["exhibits"])})
            event(project_id, "tests", {
                "passed": len(project["tests"]) - len(failed), "total": len(project["tests"]),
                "failed": [row.get("name") for row in failed],
            })
            event(project_id, "run.finished", {
                "message": "草稿已生成，%d 处引用需要确认；自测 %d/%d 通过" % (
                    len(project["issues"]), len(project["tests"]) - len(failed), len(project["tests"])),
                "issues": len(project["issues"]),
            })
        except Exception as error:
            traceback.print_exc()
            try:
                project = load(project_id)
                project["status"] = "failed"
                project["error"] = "%s: %s" % (type(error).__name__, error)
                save(project)
            except Exception:
                pass
            event(project_id, "error", {"message": "流水线异常：" + str(error)})

    threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------- 项目建档

def create_project(name, audience="", language="", brief="", materials=None, project_id=None):
    """建一个空项目。资料由使用者自己导入，这里不塞任何内置示例。

    materials: [{"name","text","title"}]，可省略；省略就是完全没有资料的空项目。
    """
    materials = list(materials or [])
    project = {
        "id": project_id or uuid.uuid4().hex[:10],
        "task_no": None,
        "created_at": now(),
        "name": (name or "").strip() or "未命名项目",
        "audience": (audience or "").strip(),
        "language": (language or "").strip(),
        "status": "draft",
        "version": 0.1,
        "run_version": 0,
        "brief": {"text": (brief or "").strip(), "at": now()},
        "authorization": None,
        "demo": False,
        "materials": [{"id": "EX%02d" % (i + 1), "title": item.get("title", ""),
                       "material": item.get("text", ""),
                       "source_refs": []} for i, item in enumerate(materials)],
        "sources": build_sources(materials),
        "exhibits": [],
        "issues": [],
        "review": None,
        "tests": [],
        "voice": {"provider": "browser", "status": "未合成"},
        "chat": [],
    }
    for index, item in enumerate(materials):
        if not project["materials"][index]["title"]:
            project["materials"][index]["title"] = "展项 %s" % (index + 1)
    refs = [s["id"] for s in project["sources"]]
    for item in project["materials"]:
        item["source_refs"] = refs
    with db() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM projects").fetchone()
    project["task_no"] = (row["n"] or 0) + 1
    save(project)
    event(project["id"], "project", {"message": "已创建项目「%s」%s" % (
        project["name"],
        "，载入 %d 份资料" % len(materials) if materials else "，还没有资料")})
    return project


def add_source(project, name, text):
    """把一段资料追加进项目并重新编号 SRC，返回新资料编号。

    编号必须整体重来：SRC-002 变成 SRC-003 之后，原有的 source_ref 也得跟着改，
    否则老事实的引用会指向另一份资料。
    """
    new_source = build_sources([{"name": name, "text": text}])[0]
    project.setdefault("sources", []).append(new_source)
    for index, source in enumerate(project["sources"], start=1):
        new_id = "SRC-%03d" % index
        for para in source["paragraphs"]:
            para["id"] = new_id + para["id"].split("·", 1)[1]
        source["id"] = new_id
    materials = project.setdefault("materials", [])
    materials.append({"id": "M-%03d" % (len(materials) + 1), "title": name[:120],
                      "material": text, "source_refs": [new_source["id"]]})
    return new_source["id"]


def delete_project(project):
    """删掉项目档案、它的事件与调用记录、以及它的音频目录。返回删掉的音频文件数。"""
    pid = project["id"]
    with db() as c:
        c.execute("DELETE FROM events WHERE project_id=?", (pid,))
        c.execute("DELETE FROM calls WHERE project_id=?", (pid,))
        c.execute("DELETE FROM projects WHERE id=?", (pid,))
    removed = 0
    folder = tts.AUDIO_ROOT / pid
    if folder.is_dir():
        for path in folder.glob("*"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        try:
            folder.rmdir()
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------- tests

# 讲解目标时长与容差。容差可用环境变量改，但默认值必须在自测详情里写清楚，
# 让「约 45 秒」是一个可核对的区间，而不是一句形容。
DURATION_TARGET = float(os.environ.get("STUDIO_DURATION_TARGET", "45"))
DURATION_TOLERANCE = float(os.environ.get("STUDIO_DURATION_TOLERANCE", "0.25"))


def measured_duration(project, exhibit_id):
    """返回 (实测秒数, 来源)。现场 ffprobe 优先并把结果回写进项目，其次用合成时记的时长。

    刻意不按「字节数 ÷ 码率」估算：那是推算不是实测，而时长门是验收依据。
    """
    info = (project.get("audio") or {}).get(exhibit_id)
    if not info:
        return None, None
    path = tts.AUDIO_ROOT / project["id"] / str(info.get("filename") or "")
    if path.is_file():
        probed = tts.probe_media(path) or {}
        if probed.get("duration_s"):
            info["duration_s"] = probed["duration_s"]
            if probed.get("bitrate_kbps"):
                info["bitrate_kbps"] = probed["bitrate_kbps"]
            info["probed_at"] = now()
            return float(probed["duration_s"]), "ffprobe"
    if info.get("duration_s"):
        return float(info["duration_s"]), "记录值"
    return None, None


def content_tests(project):
    results = []

    def add(name, ok, detail):
        results.append({"name": name, "status": "passed" if ok else "failed", "detail": detail})

    exhibits = project.get("exhibits", [])
    expected = {unit["id"] for unit in exhibit_units(project)}
    got = {e["id"] for e in exhibits}
    add("覆盖完整", bool(expected) and got == expected,
        "项目 %d 个展项，已生成 %d 个%s" % (
            len(expected), len(got),
            "" if got == expected else "；缺 " + "、".join(sorted(expected - got))
            + ("；多 " + "、".join(sorted(got - expected)) if got - expected else "")))

    bad = []
    for exhibit in exhibits:
        for fact in exhibit.get("facts", []):
            if not fact.get("verified"):
                bad.append("%s %s" % (exhibit["id"], fact.get("id")))
    add("引文逐字可定位", not bad, "全部事实的 quote 均能在来源段落原样找到" if not bad else "待核验：" + "、".join(bad))

    cross = []
    for exhibit in exhibits:
        for fact in exhibit.get("facts", []):
            ref = str(fact.get("source_ref", ""))
            own = exhibit.get("source_refs") or []
            if own and ref.split("·")[0] not in own:
                cross.append("%s 引用了 %s" % (exhibit["id"], ref))
    add("无跨展项串台", not cross, "各展项只引用自己的资料" if not cross else "；".join(cross))

    # 时长门：字数只是替代指标，真正能验收的是朗读出来的秒数。
    # 有音频就必须量到真实时长；量不到算未通过（不能拿字数通过来冒充时长通过）。
    low = DURATION_TARGET * (1 - DURATION_TOLERANCE)
    high = DURATION_TARGET * (1 + DURATION_TOLERANCE)
    lengths, out_of_range, unmeasured, measured = [], [], [], []
    for exhibit in exhibits:
        text = (exhibit.get("main") or {}).get("text", "")
        n = len(text)
        if not 80 <= n <= 400:
            lengths.append("%s 主讲解 %d 字" % (exhibit["id"], n))
        seconds, source = measured_duration(project, exhibit["id"])
        if seconds is None:
            if (project.get("audio") or {}).get(exhibit["id"]):
                unmeasured.append("%s 有音频但读不出时长（ffprobe 不可用或文件损坏）" % exhibit["id"])
            continue
        measured.append("%s %.2f 秒" % (exhibit["id"], seconds))
        if not low <= seconds <= high:
            out_of_range.append("%s 实测 %.2f 秒" % (exhibit["id"], seconds))
    window = "%.1f~%.1f 秒" % (low, high)
    problems = []
    if lengths:
        problems.append("字数不在 80~400：" + "、".join(lengths))
    if out_of_range:
        problems.append("实测时长超出 %s：%s" % (window, "、".join(out_of_range)))
    problems.extend(unmeasured)
    if problems:
        detail = "；".join(problems)
    elif measured:
        detail = "字数 80~400；实测朗读时长 %s 全部落在 %s 内（目标 %.0f 秒 ±%.0f%%）" % (
            "、".join(measured), window, DURATION_TARGET, DURATION_TOLERANCE * 100)
    else:
        detail = "字数在 80~400 字；本项目尚未合成音频，本次只核字数，未核实测时长"
    add("主讲解时长约 45 秒", not problems, detail)

    facts_total = sum(len(e.get("facts", [])) for e in exhibits)
    per_exhibit = len(exhibits) and facts_total / len(exhibits) >= 2
    add("知识卡已生成", per_exhibit,
        "共 %d 条事实，每个展项至少 2 条%s" % (facts_total, "" if per_exhibit else "（不足）"))

    no_text = [e["id"] for e in exhibits if not (e.get("main") or {}).get("text")]
    add("主讲解非空", not no_text, "各展项都有主讲解" if not no_text else "缺失：" + "、".join(no_text))

    no_answer = []
    for exhibit in exhibits:
        for item in exhibit.get("followups", []) + exhibit.get("fallback", []):
            if not str(item.get("a") or "").strip():
                no_answer.append("%s「%s」" % (exhibit["id"], str(item.get("q") or "")[:12]))
    add("问答无空答", not no_answer, "追问与兜底都有回答" if not no_answer else "空答：" + "；".join(no_answer))
    return results


# ---------------------------------------------------------------- 交付导出

STATUS_TEXT = {
    "draft": "草稿", "running": "生成中", "awaiting_confirmation": "等待确认",
    "tested": "已自测", "approved": "已批准", "published": "已发布", "failed": "失败",
}


def fmt_duration(seconds):
    """把秒数写成人能读的形式；拿不到有效值就返回 None，绝不编一个。"""
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    minutes, rest = divmod(value, 60)
    if minutes >= 1:
        return "%d 分 %.1f 秒" % (int(minutes), rest)
    return "%.1f 秒" % rest


def delivery_files(project):
    """已登记音频的**落盘事实**：字节数与 sha256 一律按磁盘上的文件重算，
    不直接采信合成时写进数据库的记录——库里的指纹证明不了客户手上的文件。

    返回的每一项都带 present 标记；文件丢了就标 missing，由调用方如实说明，
    而不是照着数据库里的旧数字写出一份看起来齐全的交付稿。
    """
    rows = []
    for exhibit in project.get("exhibits", []):
        info = (project.get("audio") or {}).get(exhibit["id"])
        if not info:
            continue
        filename = str(info.get("filename") or "")
        path = tts.AUDIO_ROOT / project["id"] / filename
        present = bool(filename) and "/" not in filename and ".." not in filename and path.is_file()
        rows.append({
            "exhibit_id": exhibit["id"],
            "info": info,
            "filename": filename,
            "path": path,
            "present": present,
            "bytes": path.stat().st_size if present else 0,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if present else "",
            "duration_s": info.get("duration_s"),
        })
    return rows


def build_export_markdown(project):
    """交付稿正文。状态行必须如实反映审核/自测/音频的真实状态，不能只写成品目录。"""
    audio_map = project.get("audio") or {}
    rows = {row["exhibit_id"]: row for row in delivery_files(project)}
    tests = project.get("tests") or []
    passed = sum(1 for t in tests if t.get("status") == "passed")
    review = project.get("review") or {}
    if review.get("decision") == "approved":
        review_line = "%s 于 %s 批准（v%s）" % (review.get("reviewer"), review.get("at"), review.get("version"))
    elif review.get("decision") == "needs_revision":
        review_line = "%s 于 %s 要求修改（v%s）" % (review.get("reviewer"), review.get("at"), review.get("version"))
    else:
        review_line = "尚未人工审核——本稿不可当作已验收交付"
    missing = [e["id"] for e in project["exhibits"] if e["id"] not in audio_map]
    lines = [
        "# %s 交付稿 v%s" % (project["name"], project["version"]),
        "",
        "> 项目状态：%s" % STATUS_TEXT.get(project["status"], project["status"]),
        "> 自测状态：%s" % ("%d/%d 通过" % (passed, len(tests)) if tests else "未运行"),
        "> 审核状态：%s" % review_line,
        "> 音频状态：%s" % ("全部展项均已合成音频（指纹见各展项小节）" if not missing
                          else "不完整——以下展项没有音频：" + "、".join(missing)),
        "> 音频文件：本 Markdown 只含清单与指纹；MP3 本体在 export.zip 的「音频」目录内。",
        "",
    ]
    for exhibit in project["exhibits"]:
        lines += ["## %s %s" % (exhibit["id"], exhibit["title"]), "",
                  (exhibit.get("main") or {}).get("text", ""), "",
                  "> 简化版：" + (exhibit.get("simplified") or {}).get("text", ""), ""]
        for fact in exhibit.get("facts", []):
            lines.append("- [%s] %s（%s，%s）" % (fact.get("id"), fact.get("text"), fact.get("source_ref"),
                                              "已核验" if fact.get("verified") else "待核验"))
        row = rows.get(exhibit["id"])
        if row is None:
            # 没产出就说没产出，不留空白
            lines.append("- 音频：未生成（本展项尚无合成音频，不可视为已交付音频）")
        elif not row["present"]:
            lines.append("- 音频：登记为 %s，但磁盘上找不到该文件——需重新合成后才能交付" % row["filename"])
        else:
            duration = fmt_duration(row["duration_s"])
            lines.append("- 音频：%s｜%s｜%s｜%d 字节｜sha256 %s%s" % (
                row["filename"], row["info"].get("engine"), row["info"].get("format", "mp3"),
                row["bytes"], row["sha256"][:16],
                ("｜实测时长 %s" % duration) if duration else "｜实测时长未采集"))
        lines.append("")
    return "\n".join(lines)


def build_audio_readme(project, rows):
    """音频目录说明。由导出时生成，取代过去那份手写模板。"""
    packed = [row for row in rows if row["present"]]
    first = packed[0]["info"] if packed else {}
    lines = [
        "# 音频交付说明",
        "",
        "本文件由 Studio 导出时自动生成，与同目录下的 MP3 一一对应。",
        "",
        "## 合成信息",
        "",
        "- 引擎：%s" % (first.get("engine") or "—"),
        "- 模型：%s" % (first.get("model") or "—"),
        "- 音色：%s" % (first.get("voice") or "—"),
        "- 格式：%s" % (first.get("format") or "mp3"),
        "",
        "## 文件清单",
        "",
        "| 展项 | 文件 | 字节 | 实测时长 | sha256（前 16 位） |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        if row["present"]:
            lines.append("| %s | %s | %d | %s | %s |" % (
                row["exhibit_id"], row["filename"], row["bytes"],
                fmt_duration(row["duration_s"]) or "未采集", row["sha256"][:16]))
        else:
            lines.append("| %s | %s（磁盘上已丢失） | — | — | — |" % (row["exhibit_id"], row["filename"]))
    if not packed:
        lines.append("| — | 本项目尚无可用音频 | — | — | — |")
    lines += [
        "",
        "## 已验证 / 未验证（务必看清再验收）",
        "",
        "- 已验证：文件由服务端真实合成并落盘，可解码；上表 sha256 是导出时对**实际打包字节**重算的结果。",
        "- 已验证：上表时长是用 ffprobe 读实际音频得到的（标「未采集」的是合成早于时长采集开启）。",
        "- 未验证：音色、语速、断句是否符合馆方要求，需要人工试听确认。",
        "- 未验证：设备端（耳机、音箱、眼镜）能否正常播放，本项目尚未接入真机。",
        "- 结论：合成成功只证明文件产出了，不等于验收通过。",
        "",
    ]
    return "\n".join(lines)


def build_export_bundle(project):
    """把 Markdown 交付稿、音频本体、音频说明与清单打成一个 zip，返回 (bytes, manifest)。"""
    markdown = build_export_markdown(project)
    rows = delivery_files(project)
    manifest = {
        "project_id": project["id"],
        "project_name": project["name"],
        "version": project["version"],
        "status": project["status"],
        "exported_at": now(),
        "review": project.get("review"),
        "tests": {"total": len(project.get("tests") or []),
                  "passed": sum(1 for t in (project.get("tests") or []) if t.get("status") == "passed")},
        "files": [
            {"path": "交付稿.md", "bytes": len(markdown.encode())},
        ],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("交付稿.md", markdown)
        for row in rows:
            if not row["present"]:
                continue
            bundle.write(row["path"], "音频/" + row["filename"])
            manifest["files"].append({
                "path": "音频/" + row["filename"], "bytes": row["bytes"],
                "sha256": row["sha256"], "duration_s": row["duration_s"],
                "engine": row["info"].get("engine"), "voice": row["info"].get("voice"),
            })
        bundle.writestr("音频/README.md", build_audio_readme(project, rows))
        bundle.writestr("交付清单.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buffer.getvalue(), manifest


# ------------------------------------------------- 项目附表：报价 / 反馈 / 签收
# 这三样原来是前端自己捏的草稿（3000/1200/150/150、三条假反馈、虚假签收）。
# 要让界面上每个数字都能回头查，就必须落到项目上，并且由服务端校验。

def _text(value, limit):
    return str(value or "").strip()[:limit]


def _money(value, label):
    """金额只收有限非负数。前端拦不住直接调接口，脏数据会一路进报价与交付清单。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("「%s」必须是数字" % label)
    if number != number or not (0 <= number <= 1e9):
        raise ValueError("「%s」必须是 0~10 亿之间的数字" % label)
    return round(number, 2)


QUOTE_TEXT_FIELDS = (("customer", "客户名称"), ("reviewer", "内容审核人"),
                     ("audience", "目标观众"), ("scope", "服务范围"))
QUOTE_MONEY_FIELDS = (("duration", "目标时长"), ("price", "报价"),
                      ("labor", "直接人工"), ("models", "模型与语音"), ("other", "其他直接费用"))


def quote_of(project):
    """返回补全后的报价对象。成本与贡献一律服务端算，不采信前端传的值。"""
    quote = dict(project.get("quote") or {})
    for key, _ in QUOTE_TEXT_FIELDS:
        quote.setdefault(key, "")
    for key, _ in QUOTE_MONEY_FIELDS:
        quote.setdefault(key, 0.0)
    quote.setdefault("confirmed", False)
    quote.setdefault("confirmed_at", None)
    quote.setdefault("updated_at", None)
    quote["cost"] = round(sum(float(quote[key]) for key in ("labor", "models", "other")), 2)
    quote["contribution"] = round(float(quote["price"]) - quote["cost"], 2)
    return quote


def apply_quote(project, data):
    quote = quote_of(project)
    for key, label in QUOTE_TEXT_FIELDS:
        if key in data:
            quote[key] = _text(data.get(key), 200)
    for key, label in QUOTE_MONEY_FIELDS:
        if key in data:
            # 空字符串 = 用户没填这个金额框。金额框留空是常态，不能当成脏数据拒掉整次提交，
            # 否则「更新测算」一点就报「必须是数字」，用户填的报价其实一分钱都没存进去。
            raw = data.get(key)
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            quote[key] = _money(raw, label)
    if data.get("confirm"):
        missing = [label for key, label in QUOTE_TEXT_FIELDS[:1] + QUOTE_TEXT_FIELDS[3:]
                   if not quote[key]]
        if missing:
            raise ValueError("确认范围前必须填写：" + "、".join(missing))
        if quote["price"] <= 0:
            raise ValueError("确认范围前必须填写报价金额")
        quote["confirmed"] = True
        quote["confirmed_at"] = quote["confirmed_at"] or now()
    quote["updated_at"] = now()
    project["quote"] = {k: v for k, v in quote.items() if k not in ("cost", "contribution")}
    return quote_of(project)


def add_feedback(project, data):
    items = project.setdefault("feedbacks", [])
    problem = _text(data.get("problem"), 2000)
    if len(problem) < 4:
        raise ValueError("反馈问题至少写 4 个字：没有现象描述的反馈无法复核")
    entry = {
        "id": "FB-%03d" % (len(items) + 1),
        "exhibit_id": _text(data.get("exhibit_id"), 16) or None,
        "title": _text(data.get("title"), 80) or problem[:24],
        "question": _text(data.get("question"), 200),
        "problem": problem,
        "old": _text(data.get("old"), 1000),
        "suggestion": _text(data.get("suggestion"), 1000),
        "state": "recorded",
        "recorded_at": now(),
    }
    items.append(entry)
    return entry


def update_feedback(project, data):
    target = None
    for item in project.get("feedbacks") or []:
        if item["id"] == _text(data.get("feedback_id"), 16):
            target = item
    if target is None:
        raise KeyError("反馈记录不存在")
    state = _text(data.get("state"), 20)
    if state not in ("candidate", "closed"):
        raise ValueError("state 只能是 candidate（登记为改进候选）或 closed")
    if state == "candidate":
        suggestion = _text(data.get("suggestion"), 1000) or target.get("suggestion", "")
        if len(suggestion) < 4:
            raise ValueError("登记改进候选必须写明改成什么说法")
        target["suggestion"] = suggestion
    target["state"] = state
    target["state_at"] = now()
    return target


def record_acceptance(project, data):
    """签收是客户动作，只能发生在已发布版本上——批准 ≠ 签收 ≠ 回款。"""
    if project.get("status") != "published":
        raise PermissionError("只有已发布的版本才能登记客户签收（当前状态：%s）"
                              % STATUS_TEXT.get(project.get("status"), project.get("status")))
    signer = _text(data.get("signer"), 40)
    if not signer:
        raise ValueError("签收人不能为空：没有署名的签收不算凭证")
    decision = _text(data.get("decision"), 20)
    if decision not in ("accepted", "rejected"):
        raise ValueError("decision 必须是 accepted 或 rejected")
    previous = project.get("acceptance")
    if previous:
        # 签收是客户的最终动作，重复点两次不该把「已签收」悄悄改写成「已拒收」。
        # 同一个人同一结论重发算幂等成功，换了结论或换了人必须先退回流程。
        if previous.get("decision") == decision and previous.get("signer") == signer:
            return previous
        raise PermissionError("v%s 已由 %s 登记为「%s」，如需改判请先重新发布新版本"
                              % (previous.get("version"), previous.get("signer"),
                                 "已签收" if previous.get("decision") == "accepted" else "已拒收"))
    project["acceptance"] = {"signer": signer, "decision": decision,
                             "note": _text(data.get("note"), 1000),
                             "version": project.get("version"), "at": now()}
    return project["acceptance"]


def apply_exhibit_text(project, data):
    """改写主讲解。改完必须让旧的自测与审核失效，否则界面会拿着过期结论放行。"""
    exhibit_id = _text(data.get("exhibit_id"), 16)
    text = str(data.get("text") or "").strip()
    exhibit = None
    for item in project.get("exhibits", []):
        if item["id"] == exhibit_id:
            exhibit = item
    if exhibit is None:
        raise KeyError("展项不存在：" + (exhibit_id or "(空)"))
    if len(text) < 20:
        raise ValueError("主讲解至少 20 字，太短无法承载一个知识点")
    if len(text) > 2000:
        raise ValueError("主讲解最多 2000 字")
    old = (exhibit.get("main") or {}).get("text", "")
    if text == old:
        raise ValueError("内容没有变化")
    exhibit["main"] = {"text": text,
                       "fact_ids": list((exhibit.get("main") or {}).get("fact_ids") or [])}
    project["version"] = round(float(project.get("version", 0)) + 0.1, 1)
    # 改一个字，旧的时长实测、测试结论、审核签名就都不再对应当前文本
    project["tests"] = []
    project["review"] = None
    if project.get("status") in ("tested", "approved", "published"):
        project["status"] = "awaiting_confirmation"
    return exhibit, old


# ---------------------------------------------------------------- http

ASSET_TYPES = {".css": "text/css; charset=utf-8",
               ".js": "application/javascript; charset=utf-8",
               ".svg": "image/svg+xml", ".png": "image/png",
               ".woff2": "font/woff2", ".ico": "image/x-icon"}


class Handler(BaseHTTPRequestHandler):
    server_version = "Studio/1.0"

    def log_message(self, fmt, *args):
        pass

    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # 以前这里静默返回 {}：一个编码错的请求体会被当成「所有字段都没传」，
            # 报价这类整体覆盖的写入会悄悄把已有值清空。宁可 400，也不要静默成功。
            raise ValueError("请求体不是合法的 UTF-8 JSON")

    def serve_page(self, name):
        page = (ROOT / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return self.wfile.write(page)

    def serve_asset(self, path):
        """只下发 assets/ 目录内的静态文件。与页面一样免口令——里面没有项目数据。"""
        base = (ROOT / "assets").resolve()
        target = (ROOT / path.lstrip("/")).resolve()
        try:
            target.relative_to(base)
        except ValueError:
            return self.send_json(404, {"error": "文件不存在"})
        if not target.is_file():
            return self.send_json(404, {"error": "文件不存在"})
        raw = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ASSET_TYPES.get(target.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return self.wfile.write(raw)

    def authorized(self):
        """校验访问口令。未配置口令时放行——启动护栏（main）保证这只在监听本机时才发生。

        口令支持 X-Access-Token 头或 ?token= 查询参数；后者是给 <audio src>、
        导出下载这类浏览器无法附加自定义头的请求用的。比较用 compare_digest 避免计时侧信道。
        """
        if not ACCESS_TOKEN:
            return True
        supplied = self.headers.get("X-Access-Token") or ""
        if not supplied:
            supplied = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        return hmac.compare_digest(supplied.strip(), ACCESS_TOKEN)

    def require_auth(self):
        """未授权时回 401。返回值非 None 表示已经写过响应。"""
        if self.authorized():
            return None
        return self.send_json(401, {"error": "需要访问口令：请带 X-Access-Token 头，或在地址后加 ?token=..."})

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path.startswith("/assets/"):
            return self.serve_asset(path)
        if path in ("/", "/index.html", "/studio"):
            return self.serve_page("studio_web.html")
        if path in ("/classic", "/classic.html"):
            # 旧版工作台保留可访问：新界面换代期间它仍是已经验过的那一份
            return self.serve_page("studio_classic.html")
        # 静态页本身不含数据，放行；所有 /api/studio/* 接口都要口令。
        denied = self.require_auth()
        if denied is not None:
            return denied
        try:
            if path == "/api/studio/health":
                return self.send_json(200, {"ok": True, "model": MODEL, "key_configured": bool(API_KEY),
                                            "database": DB_PATH.name, "code": CODE_REV, "pid": os.getpid(),
                                            "auth_required": bool(ACCESS_TOKEN), "tts": tts.status(),
                                            "web": websearch.status(), "docs": docread.status(),
                                            "agent": {"max_rounds": AGENT_MAX_ROUNDS,
                                                      "max_tool_calls": AGENT_MAX_TOOL_CALLS,
                                                      "stale_seconds": CHAT_STALE_SECONDS}})
            if path == "/api/studio/projects":
                # 空库就是空库：不再自动塞入任何内置示例项目。
                with db() as c:
                    rows = c.execute("SELECT body FROM projects ORDER BY updated_at DESC").fetchall()
                items = []
                for row in rows:
                    body = json.loads(row["body"])
                    items.append({"id": body["id"], "name": body["name"], "status": body["status"],
                                  "version": body["version"], "updated_at": body["updated_at"],
                                  "task_no": body.get("task_no")})
                return self.send_json(200, {"projects": items})
            match = re.fullmatch(r"/api/studio/projects/([A-Za-z0-9]+)(/events)?", path)
            if match:
                project = load(match.group(1))
                if match.group(2):
                    after = int((query.get("after") or ["0"])[0])
                    with db() as c:
                        rows = c.execute("SELECT id,created_at,kind,detail FROM events WHERE project_id=? AND id>? ORDER BY id LIMIT 300",
                                         (project["id"], after)).fetchall()
                    events = [{"id": r["id"], "created_at": r["created_at"], "kind": r["kind"],
                               "detail": json.loads(r["detail"] or "{}")} for r in rows]
                    return self.send_json(200, {"events": events, "status": project["status"]})
                return self.send_json(200, {"project": project})
            match = re.fullmatch(r"/api/studio/projects/([A-Za-z0-9]+)/audio/([A-Za-z0-9._-]+)", path)
            if match:
                project = load(match.group(1))
                name = match.group(2)
                # 只允许下发该项目自己登记过的音频文件，防止路径穿越读到别处
                known = {a.get("filename") for a in (project.get("audio") or {}).values()}
                if name not in known or "/" in name or ".." in name:
                    return self.send_json(404, {"error": "音频不存在，请重新合成"})
                target = tts.AUDIO_ROOT / project["id"] / name
                if not target.is_file():
                    return self.send_json(404, {"error": "音频文件已丢失，请重新合成"})
                raw = target.read_bytes()
                mime = "audio/wav" if name.endswith(".wav") else "audio/mpeg"
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Accept-Ranges", "none")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(raw)
            match = re.fullmatch(r"/api/studio/projects/([A-Za-z0-9]+)/export(\.zip)?", path)
            if match:
                project = load(match.group(1))
                if match.group(2):
                    # 交付包：Markdown + 音频本体 + 音频说明 + 清单，客户拿到的就是能直接归档的一份
                    raw, manifest = build_export_bundle(project)
                    filename = "studio-%s-v%s.zip" % (project["id"], project["version"])
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition",
                                     'attachment; filename="%s"; filename*=UTF-8\'\'%s'
                                     % (filename, quote(filename)))
                    self.send_header("Content-Length", str(len(raw)))
                    self.send_header("X-Delivered-Files", str(len(manifest["files"])))
                    self.end_headers()
                    return self.wfile.write(raw)
                raw = build_export_markdown(project).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="studio-%s.md"' % project["id"])
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                return self.wfile.write(raw)
            return self.send_json(404, {"error": "接口不存在"})
        except KeyError as error:
            return self.send_json(404, {"error": str(error)})
        except Exception as error:
            traceback.print_exc()
            return self.send_json(500, {"error": "%s: %s" % (type(error).__name__, error)})

    def handle_upload(self, project_id):
        """收一个文件本体：原始字节 + ?name=<文件名>，不走 multipart。

        前端直接 fetch(url, {method:"POST", body: file})，服务端不需要解析表单边界；
        文件名放在查询参数里（浏览器的 body 是二进制，塞不进 JSON）。
        """
        query = parse_qs(urlparse(self.path).query)
        name = (query.get("name") or [""])[0].strip()
        if not name:
            name = unquote(self.headers.get("X-File-Name") or "").strip()
        if not name:
            return self.send_json(400, {"error": "没拿到文件名。上传地址要带 ?name=文件名"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self.send_json(400, {"error": "Content-Length 不合法"})
        if length <= 0:
            return self.send_json(400, {"error": "文件是空的（0 字节）"})
        if length > docread.MAX_BYTES:
            return self.send_json(413, {"error": "文件太大了（%.1f MB）。上限是 %d MB"
                                        % (length / 1048576.0, docread.MAX_BYTES // 1048576)})
        raw = self.rfile.read(length)
        try:
            doc = docread.read_bytes(raw, name)
        except docread.ReadError as error:
            return self.send_json(400, {"error": str(error)})
        project = load(project_id)
        title = name.rsplit(".", 1)[0].strip()[:80] or "未命名资料"
        source_id = add_source(project, title, doc["text"])
        save(project)
        paragraphs = len(project["sources"][-1]["paragraphs"])
        event(project_id, "material", {"message": "上传资料：《%s》，%d 段" % (name, paragraphs) if paragraphs
                                       else "上传资料：《%s》，没有切出段落" % name,
                                       "bytes": len(raw), "source_id": source_id})
        return self.send_json(200, {"project": project, "source_id": source_id, "doc": doc})

    def do_POST(self):
        denied = self.require_auth()
        if denied is not None:
            return denied
        path = urlparse(self.path).path
        try:
            upload = re.fullmatch(r"/api/studio/projects/([A-Za-z0-9]+)/upload", path)
            if upload:
                return self.handle_upload(upload.group(1))
            data = self.read_json()
            if path == "/api/studio/projects":
                name = str(data.get("name") or "").strip()
                if not name:
                    return self.send_json(400, {"error": "项目名称不能为空"})
                if len(name) > 60:
                    return self.send_json(400, {"error": "项目名称最多 60 字"})
                project = create_project(
                    name=name,
                    audience=str(data.get("audience") or "").strip()[:40],
                    language=str(data.get("language") or "").strip()[:20],
                    brief=str(data.get("brief") or "").strip()[:2000],
                )
                return self.send_json(201, {"project": project})
            match = re.fullmatch(r"/api/studio/projects/([A-Za-z0-9]+)/(run|review|chat|tests|issue|material|voice|publish|authorize|quote|exhibit|feedback|acceptance|delete)", path)
            if not match:
                return self.send_json(404, {"error": "接口不存在"})
            project_id, action = match.group(1), match.group(2)
            project = load(project_id)

            if action == "delete":
                removed = delete_project(project)
                return self.send_json(200, {"deleted": project_id, "name": project["name"],
                                            "audio_files_removed": removed})

            if action == "run":
                if project["status"] == "running":
                    return self.send_json(409, {"error": "正在执行，请等待本轮结束"})
                only = str(data.get("exhibit_id") or "").strip()[:16]
                if only:
                    if project.get("exhibits") and not any(
                            e["id"] == only for e in project["exhibits"]):
                        return self.send_json(404, {"error": "展项不存在：" + only})
                    run_single_exhibit(project_id, only)
                    return self.send_json(202, {"status": "running", "exhibit_id": only})
                units = exhibit_units(project)
                if not units:
                    return self.send_json(400, {"error": "还没有内容依据。知名作品可以直接让我联网调研："
                                                         "在对话里说「先调研一下这个作品，然后起草」，"
                                                         "或者把展签/资料导进来。"})
                project["status"] = "running"
                project["issues"] = []
                save(project)
                event(project_id, "step", {"step": "cards", "state": "running", "label": "知识卡",
                                           "detail": "开始为 %d 个展项抽取事实" % len(units)})
                run_pipeline(project_id)
                return self.send_json(202, {"status": "running"})

            if action == "review":
                decision = data.get("decision")
                if decision not in ("approved", "needs_revision"):
                    return self.send_json(400, {"error": "decision 必须为 approved 或 needs_revision"})
                if data.get("version") != project["version"]:
                    return self.send_json(409, {"error": "版本已变化，请刷新"})
                # 署名必须在服务端校验：前端拦不住直接调接口，而审批结论会进导出与验收凭证。
                reviewer = str(data.get("reviewer") or "").strip()
                if not reviewer:
                    return self.send_json(400, {"error": "审核人不能为空，通过和退回都需要人工署名"})
                if decision == "approved":
                    if project["issues"]:
                        return self.send_json(409, {"error": "仍有 %d 处待核验引用，不能批准" % len(project["issues"])})
                    if not project.get("tests") or any(t["status"] != "passed" for t in project["tests"]):
                        return self.send_json(409, {"error": "测试未全部通过，不能批准"})
                project["review"] = {"decision": decision, "reviewer": reviewer[:40],
                                     "at": now(), "version": project["version"]}
                project["status"] = "approved" if decision == "approved" else "awaiting_confirmation"
                save(project)
                event(project_id, "review", {"message": "审核结论：" + ("通过" if decision == "approved" else "需要修改"),
                                             "reviewer": project["review"]["reviewer"]})
                return self.send_json(200, {"project": project})

            if action == "tests":
                project["tests"] = content_tests(project)
                all_passed = bool(project["tests"]) and all(t["status"] == "passed" for t in project["tests"])
                if project.get("exhibits"):
                    # 自测不过就退回待确认：不能让项目继续挂着「已自测」的旧状态，
                    # 否则界面上的状态本身就在骗人（旧代码在失败时保留原状态）。
                    project["status"] = "tested" if all_passed else "awaiting_confirmation"
                save(project)
                event(project_id, "tests", {"message": "自测完成：%d/%d 通过" % (
                    sum(1 for t in project["tests"] if t["status"] == "passed"), len(project["tests"]))})
                return self.send_json(200, {"project": project})

            if action == "issue":
                issue_id = data.get("issue_id")
                choice = data.get("choice")
                hit = None
                for exhibit in project["exhibits"]:
                    for issue in exhibit.get("issues", []):
                        if issue["id"] == issue_id:
                            hit = issue
                if not hit:
                    return self.send_json(404, {"error": "问题不存在，可能已经处理"})
                if choice == "删除该事实":
                    for exhibit in project["exhibits"]:
                        exhibit["facts"] = [f for f in exhibit.get("facts", [])
                                            if f.get("id") != hit.get("fact_id")]
                        exhibit["issues"] = [i for i in exhibit.get("issues", []) if i["id"] != issue_id]
                        exhibit["verified"] = bool(exhibit["facts"]) and all(f.get("verified") for f in exhibit["facts"])
                elif choice in ("补充资料", "补充资料后再核", "重新生成"):
                    project["status"] = "awaiting_confirmation"
                else:
                    return self.send_json(400, {"error": "未知的处理方式"})
                project["issues"] = [i for e in project["exhibits"] for i in e.get("issues", [])]
                save(project)
                event(project_id, "issue", {"message": "已处理：%s · %s" % (hit["title"], choice)})
                return self.send_json(200, {"project": project})

            if action == "material":
                name = str(data.get("name") or "补充资料")[:120]
                text = str(data.get("text") or "").strip()
                if len(text) < 20:
                    return self.send_json(400, {"error": "补充资料至少 20 字"})
                source_id = add_source(project, name, text)
                save(project)
                event(project_id, "material", {"message": "新增资料：" + name, "bytes": len(text.encode()),
                                               "source_id": source_id})
                return self.send_json(200, {"project": project, "source_id": source_id})

            if action == "authorize":
                if project.get("authorization"):
                    return self.send_json(409, {"error": "授权已确认，无需重复登记"})
                name = str(data.get("confirmed_by") or "").strip()[:40]
                if not name:
                    return self.send_json(400, {"error": "需要登记确认人姓名"})
                project["authorization"] = {"confirmed_by": name, "at": now(),
                                            "scope": "项目内全部资料可用于内容制作"}
                save(project)
                event(project_id, "authorization",
                      {"message": "资料授权已确认 · " + name})
                return self.send_json(200, {"project": project})

            if action == "quote":
                quote = apply_quote(project, data)
                save(project)
                event(project_id, "quote", {
                    "message": "报价%s · ¥%s" % ("范围已确认" if quote["confirmed"] else "已更新",
                                                quote["price"]),
                    "price": quote["price"], "contribution": quote["contribution"]})
                return self.send_json(200, {"project": project, "quote": quote})

            if action == "exhibit":
                exhibit, old_text = apply_exhibit_text(project, data)
                save(project)
                event(project_id, "exhibit", {
                    "message": "%s 主讲解已改写，版本升到 v%s；旧测试与审核已失效" % (
                        exhibit["id"], project["version"]),
                    "exhibit_id": exhibit["id"],
                    "chars_before": len(old_text), "chars_after": len(exhibit["main"]["text"])})
                return self.send_json(200, {"project": project})

            if action == "feedback":
                op = _text(data.get("op"), 20) or "add"
                if op == "add":
                    entry = add_feedback(project, data)
                    message = "记录反馈 %s" % entry["id"]
                elif op in ("candidate", "closed"):
                    entry = update_feedback(project, dict(data, state=op))
                    message = "反馈 %s → %s" % (entry["id"], op)
                else:
                    return self.send_json(400, {"error": "op 只能是 add / candidate / closed"})
                save(project)
                event(project_id, "feedback", {"message": message, "feedback_id": entry["id"]})
                return self.send_json(200, {"project": project, "feedback": entry})

            if action == "acceptance":
                record = record_acceptance(project, data)
                save(project)
                event(project_id, "acceptance", {
                    "message": "客户%s · %s" % ("签收" if record["decision"] == "accepted" else "拒收",
                                              record["signer"])})
                return self.send_json(200, {"project": project, "acceptance": record})

            if action == "voice":
                exhibit_id = str(data.get("exhibit_id") or "")[:16]
                text = str(data.get("text") or "").strip()
                if not text:
                    return self.send_json(400, {"error": "没有可合成的文本"})
                # 只允许合成当前草稿里真实存在的主讲解，避免任意文本走 TTS 通道
                exhibit = None
                for item in project.get("exhibits", []):
                    if item["id"] == exhibit_id:
                        exhibit = item
                        break
                if exhibit is None:
                    return self.send_json(404, {"error": "展项不存在：" + (exhibit_id or "(空)")})
                if text != (exhibit.get("main") or {}).get("text", "").strip():
                    return self.send_json(409, {"error": "提交的文本与当前草稿不一致，请刷新后再合成"})
                try:
                    info = tts.synthesize(project["id"], exhibit_id, text,
                                          voice=data.get("voice"), engine=data.get("engine"))
                except tts.TTSError as error:
                    event(project_id, "voice", {"message": "合成失败：" + str(error), "ok": False})
                    return self.send_json(502, {"error": "音频合成失败：" + str(error)})
                audio = project.setdefault("audio", {})
                audio[exhibit_id] = dict(info, at=now())
                project["voice"] = {"provider": info["engine"], "status": "已合成音频",
                                    "exhibit_id": exhibit_id, "chars": info["chars"],
                                    "filename": info["filename"], "at": now()}
                save(project)
                event(project_id, "voice", {
                    "message": "已合成 %s 音频：%s，%d 字节，%s，耗时 %d ms" % (
                        exhibit_id, info["engine"], info["bytes"], info["format"], info["elapsed_ms"]),
                    "ok": True})
                return self.send_json(200, {"project": project, "audio": info})

            if action == "publish":
                if not (project.get("review") and project["review"]["decision"] == "approved"):
                    return self.send_json(409, {"error": "尚未通过人工审核，不能发布"})
                if not project.get("tests") or any(t["status"] != "passed" for t in project["tests"]):
                    return self.send_json(409, {"error": "自测未全部通过，不能发布"})
                # 门禁必须和前端 gates() 一致：前端列出 5 项，后端只挡 2 项就是漏检。
                # 审核人签的「通过」绑定当时版本，改过内容后版本号变了，旧签名不能放行新版本。
                if project["review"].get("version") != project["version"]:
                    return self.send_json(409, {"error": "审核签名对应 v%s，当前是 v%s，请重新审核"
                                                % (project["review"].get("version"), project["version"])})
                if project.get("issues"):
                    return self.send_json(409, {"error": "仍有 %d 处待核验引用，不能发布" % len(project["issues"])})
                exhibits = project.get("exhibits") or []
                audio = project.get("audio") or {}
                missing_audio = [e["id"] for e in exhibits if not audio.get(e["id"])]
                if exhibits and missing_audio:
                    return self.send_json(409, {"error": "还有展项没合成音频：%s，交付包里会缺 MP3"
                                                % "、".join(missing_audio)})
                project["status"] = "published"
                save(project)
                event(project_id, "publish", {"message": "已发布 v%s" % project["version"]})
                return self.send_json(200, {"project": project})

            if action == "chat":
                message = str(data.get("message") or "").strip()
                if not message:
                    return self.send_json(400, {"error": "消息为空"})
                if len(message) > 2000:
                    return self.send_json(400, {"error": "消息太长了（上限 2000 字），分几次说吧"})
                if chat_busy(project):
                    return self.send_json(409, {"error": "我还在回上一句，稍等一下"})
                project["chat_running"] = now()
                save(project)
                threading.Thread(target=chat_worker, args=(project_id, message), daemon=True).start()
                return self.send_json(202, {"status": "thinking"})

            return self.send_json(404, {"error": "接口不存在"})
        except PermissionError as error:
            return self.send_json(403, {"error": str(error)})
        except ValueError as error:
            return self.send_json(400, {"error": str(error)})
        except KeyError as error:
            return self.send_json(404, {"error": str(error)})
        except ModelError as error:
            return self.send_json(502, {"error": str(error)})
        except Exception as error:
            traceback.print_exc()
            return self.send_json(500, {"error": "%s: %s" % (type(error).__name__, error)})


# ---------------------------------------------------------------- 对话与联网
# 员工说话，数字员工做事。这里不是「关键词分支 + 固定话术」的假对话：
# 每一轮都真的调模型，模型自己决定要不要联网查、要不要读资料、要不要重做草稿。
AGENT_MAX_ROUNDS = int(os.environ.get("STUDIO_CHAT_ROUNDS", "6"))
AGENT_MAX_TOOL_CALLS = int(os.environ.get("STUDIO_CHAT_TOOLS", "14"))
CHAT_STALE_SECONDS = int(os.environ.get("STUDIO_CHAT_STALE", "240"))

PROJECT_TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "project_digest",
        "description": "读取当前项目最新的真实状态（资料、展项、字数、待核验引用、自测、审核、音频）。"
                       "聊到「现在什么情况」之前先调它，不要凭记忆回答。",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "read_source",
        "description": "读取员工上传的某份资料原文。只给 source_id 返回段落目录；再给 paragraph_id 返回那一段原文。"
                       "核对原文、找可引用的整句时必须用它。",
        "parameters": {"type": "object", "properties": {
            "source_id": {"type": "string", "description": "资料编号，如 SRC-001"},
            "paragraph_id": {"type": "string", "description": "段落编号，如 SRC-001·P003，可省略"}},
            "required": ["source_id"]}}},
    {"type": "function", "function": {
        "name": "add_material",
        "description": "把一段真实资料登记进当前项目（员工说「把这个加进去」「我还有一段」时用）。"
                       "text 必须是原文，不要改写、不要补写。",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "资料名，如「光的折射_补充资料」"},
            "text": {"type": "string", "description": "资料原文"}},
            "required": ["name", "text"]}}},
    {"type": "function", "function": {
        "name": "add_research",
        "description": "把一个网页登记成项目的可引用来源：服务端会重新抓这页正文，把你给的 quotes 里"
                       "能在正文中原样找到的句子存成摘录（WEB-001·Q001…）。不给 quotes 就自动截取正文整句。"
                       "要让网页内容进草稿，必须先调它——只调 fetch_url 是存不进项目的。",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string", "description": "网页地址（http/https）"},
            "quotes": {"type": "array", "items": {"type": "string"},
                       "description": "从这页原样复制的整句，2~12 条；一个字都不要改"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "plan_exhibits",
        "description": "定这一批要起草几个展项（通常一件作品一个展项）。没有上传资料时，起草前必须先用它定清单。",
        "parameters": {"type": "object", "properties": {
            "titles": {"type": "array", "items": {"type": "string"},
                       "description": "展项名称，按展厅动线顺序，最多 12 个"}},
            "required": ["titles"]}}},
    {"type": "function", "function": {
        "name": "start_generation",
        "description": "按当前资料重新生成全部展项的草稿（要调模型，几十秒）。只有员工明确要你生成/重做时才调。",
        "parameters": {"type": "object", "properties": {}}}},
]


def project_digest_text(project):
    """给模型看的真实项目现状。不写「示例」，不写假进度。"""
    lines = ["项目：%s（v%s，%s）" % (project.get("name"), project.get("version"),
                                 STATUS_TEXT.get(project.get("status"), project.get("status")))]
    for key, label in (("audience", "目标观众"), ("language", "语言")):
        if project.get(key):
            lines.append("%s：%s" % (label, project[key]))
    sources = project.get("sources") or []
    if sources:
        lines.append("资料 %d 份：%s" % (len(sources), "；".join(
            "%s《%s》%d 段" % (s["id"], s.get("name", ""), len(s.get("paragraphs") or [])) for s in sources)))
    else:
        lines.append("资料：还没导入（不影响起草——知名作品可以用联网调研代替）。")
    research = project.get("research") or []
    if research:
        lines.append("联网调研 %d 个网页：%s" % (len(research), "；".join(
            "%s《%s》%d 条摘录" % (item["id"], (item.get("title") or "")[:24], len(item.get("quotes") or []))
            for item in research[:5])))
    else:
        lines.append("联网调研：还没有存过网页。")
    plan = project.get("plan") or []
    if plan:
        lines.append("展项清单（%d 个）：%s" % (len(plan), "、".join(
            "%s %s" % (item["id"], item.get("title", "")) for item in plan[:8])))
    exhibits = project.get("exhibits") or []
    if not exhibits:
        lines.append("展项：还没生成草稿。")
    for exhibit in exhibits:
        main_len = len(((exhibit.get("main") or {}).get("text") or ""))
        audio = (project.get("audio") or {}).get(exhibit["id"])
        lines.append("展项 %s《%s》：主讲解 %d 字（目标 45 秒），事实 %d 条，待核验 %d 处%s" % (
            exhibit["id"], exhibit.get("title", ""), main_len, len(exhibit.get("facts") or []),
            len(exhibit.get("issues") or []), "，已合成音频" if audio else "，还没有音频"))
    issues = project.get("issues") or []
    if issues:
        lines.append("待确认引用 %d 处：%s" % (len(issues), "；".join(
            "%s %s" % (i.get("fact_id", ""), i.get("reason", "")) for i in issues[:3])))
    tests = project.get("tests") or []
    if tests:
        passed = sum(1 for t in tests if t.get("status") == "passed")
        lines.append("自测 %d/%d 通过" % (passed, len(tests)))
    review = project.get("review") or {}
    if review.get("decision"):
        lines.append("审核：%s（%s）" % ("已通过" if review["decision"] == "approved" else "要求修改",
                                     review.get("reviewer") or ""))
    quote = quote_of(project) if project.get("quote") else None
    if quote and quote.get("confirmed"):
        lines.append("报价与范围：已确认，报价 %s 元" % quote.get("price"))
    return "\n".join(lines)


def agent_system_prompt(project):
    return """你是这个展馆内容团队里的「展览互动内容制作员」，和用户是同事，不是客服，也不是一个表单。

怎么说话：
- 像人一样：短句，先给结论，再说下一步。别用「首先/其次/综上所述」，别把每句话都加粗，条目超过三条就改成一段话。
- 现场情况你已经知道了（贴在最后），不用再问「请问您想让我做什么」，能动手就先动手。
- 不确定的事实不要编。需要外部信息就调用 web_search，必要时 fetch_url 打开页面读正文；回答里说清用了哪个来源（给链接）。
- 搜索词写 2~5 个关键词，像人在搜索框里打字：「光的折射 生活例子」而不是「请问光的折射在生活中有哪些例子呢」。长句会被搜索引擎截断。
- 查证要收得住：搜 2~3 次、打开 1~2 页就该给结论了。查完先说结论，别一直查到没话说。
- 查不到就直说查不到，别用「根据相关资料」糊过去，也不要说「已完成」来结束一个没做的事。
- 一件事做完，用一句话说清「结果 + 下一步」，一般不超过 150 字。真要分点，最多三条，用「·」而不是长表格。

边界：
- 内容依据有两种：员工上传的资料（编号 SRC-…），和你联网调研存进项目的网页摘录（编号 WEB-…）。两者引用都必须逐字原文，一个字都不许改；没有依据的内容一律不写。
- 判断要不要等资料：博物馆/美术馆的公开展品、知名作品、网上有可靠资料的题材 —— 你自己调研就够，不要拿「请提供资料」当挡箭牌，也不要说「资料为空所以做不了」。客户自己送展的作品、内部藏品、网上查不到的东西（资料很少）—— 才请他提供资料或原文，并说清为什么需要。
- 调研要落库才作数：fetch_url 只是看一眼，要让内容进草稿必须 add_research 存成 WEB 来源；再来 plan_exhibits 定展项清单，最后 start_generation。
- 你一旦调用了 start_generation，起草就会在你这轮说完之后自动开始。所以这时候别再说「还没生成」「需要你点头确认」——就说一句「正在起草，好了叫你」。员工真不想生成，他会自己叫停。
- 涉及别的生成类动作（比如合成语音、发布），只有员工明确要求才做。

项目现场（真实数据）：
%s""" % project_digest_text(project)


def agent_history(project, limit=10):
    items = []
    for entry in (project.get("chat") or [])[-limit:]:
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        role = "assistant" if entry.get("role") == "agent" else "user"
        items.append({"role": role, "content": text[:2000]})
    return items


def agent_tools():
    return list(websearch.TOOL_SPECS) + PROJECT_TOOL_SPECS


def tool_label(name, args):
    if name == "web_search":
        return "正在搜「%s」" % str(args.get("query") or "")[:40]
    if name == "fetch_url":
        return "正在打开网页"
    if name == "read_source":
        return "正在读资料 %s" % str(args.get("source_id") or "")
    if name == "add_material":
        return "正在登记资料「%s」" % str(args.get("name") or "")[:20]
    if name == "add_research":
        return "正在把这页存进项目"
    if name == "plan_exhibits":
        return "正在定展项清单"
    if name == "start_generation":
        return "准备按当前来源起草"
    return "正在处理 %s" % name


def _tool_project_digest(project, args):
    return project_digest_text(project), {"status": project.get("status")}


def _tool_read_source(project, args):
    source_id = str(args.get("source_id") or "").strip()
    paragraph_id = str(args.get("paragraph_id") or "").strip()
    sources = project.get("sources") or []
    source = next((s for s in sources if s.get("id") == source_id), None)
    if source is None:
        names = "、".join(s.get("id", "") for s in sources) or "（还没有任何资料）"
        return "没有这份资料。现有资料：%s" % names, None
    paragraphs = source.get("paragraphs") or []
    if paragraph_id:
        paragraph = next((p for p in paragraphs if p.get("id") == paragraph_id), None)
        if paragraph is None:
            first = paragraphs[0]["id"] if paragraphs else "无"
            return "%s 里没有 %s 这一段。它有 %d 段，从 %s 开始。" % (source_id, paragraph_id, len(paragraphs), first), None
        return "%s：%s" % (paragraph["id"], paragraph["text"]), {"source_id": source_id}
    body = "\n".join("%s %s" % (p["id"], p["text"]) for p in paragraphs)
    if len(body) > 6000:
        index = "\n".join("%s %s…" % (p["id"], p["text"][:40]) for p in paragraphs)
        return ("《%s》共 %d 段，太长，先给目录。要看某段就把 paragraph_id 给我：\n%s"
                % (source.get("name", ""), len(paragraphs), index)), {"source_id": source_id, "paragraphs": len(paragraphs)}
    return "《%s》共 %d 段：\n%s" % (source.get("name", ""), len(paragraphs), body), {"source_id": source_id}


def _tool_add_material(project, args):
    name = str(args.get("name") or "").strip()[:80] or "补充资料"
    text = str(args.get("text") or "").strip()
    if len(text) < 20:
        return "这段只有 %d 字，不像资料正文。至少 20 字再说，或者直接把文件拖进对话框上传。" % len(text), None
    source_id = add_source(project, name, text)
    source = project["sources"][-1]
    paragraphs = len(source.get("paragraphs") or [])
    return ("已登记《%s》为 %s，切出 %d 段。原有草稿不会自己变——要让它进草稿就得重做一遍。"
            % (name, source_id, paragraphs)), {"source_id": source_id, "paragraphs": paragraphs}


def _tool_add_research(project, args):
    """把网页存成可引用来源。服务端自己再抓一次正文，模型给的句子必须原样命中。"""
    url = str(args.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return "需要一个 http/https 网址。", None
    quotes = args.get("quotes")
    if isinstance(quotes, str):
        quotes = [line for line in quotes.split("\n") if line.strip()]
    page = websearch.fetch(url, 40000)
    text = page.get("text") or ""
    if len(_norm_space(text)) < 120:
        return ("这页没抓到正文（%s）。换一个页面，或者让员工把这段原文贴给你。"
                % (page.get("note") or "内容太少")), None
    web_id, kept, dropped = add_research(project, url, text, title=page.get("title") or url,
                                         quotes=quotes or [])
    save(project)
    stored = next((item for item in project.get("research") or [] if item.get("id") == web_id), {})
    tail = "，丢掉 %d 条（在正文里找不到原句）" % dropped if dropped else ""
    return ("已存《%s》为 %s，%d 条可引用摘录%s。起草时引用就写 %s·Q001 这样的编号。"
            % (stored.get("title") or url, web_id, kept, tail, web_id)), {
        "web_id": web_id, "quotes": kept}


def _tool_plan_exhibits(project, args):
    titles = args.get("titles") or []
    if isinstance(titles, str):
        titles = [item for item in re.split(r"[\n,，、;；]", titles) if item.strip()]
    titles = [str(item).strip()[:60] for item in titles if str(item).strip()]
    if not titles:
        return "至少给一个展项名称。", None
    if len(titles) > 12:
        return "一次最多 12 个展项，分两批吧。", None
    plan = [{"id": "EX%02d" % index, "title": title}
            for index, title in enumerate(titles, start=1)]
    project["plan"] = plan
    save(project)
    return ("定了 %d 个展项：%s。起草时每个展项各出一份主讲解，引用来自现有来源。"
            % (len(plan), "、".join(item["title"] for item in plan))), {"titles": titles}


def run_agent_tool(project, name, args, flags):
    """执行一个工具调用。永不抛异常：失败也返回一句能继续往下聊的话。"""
    try:
        if name in ("web_search", "fetch_url"):
            return websearch.run_tool(name, args)
        if name == "project_digest":
            return _tool_project_digest(project, args)
        if name == "read_source":
            return _tool_read_source(project, args)
        if name == "add_material":
            return _tool_add_material(project, args)
        if name == "add_research":
            return _tool_add_research(project, args)
        if name == "plan_exhibits":
            return _tool_plan_exhibits(project, args)
        if name == "start_generation":
            units = exhibit_units(project)
            if not units:
                return ("现在既没有资料也没有调研记录，起草没有依据。"
                        "先 add_research 存一两个网页，或者让员工导入资料。"), None
            flags["generate"] = True
            return ("好，等这轮说完我就按 %d 个展项、当前来源重做草稿。" % len(units)), {"queued": True}
        return "没有叫 %s 的工具。" % name, None
    except websearch.WebError as error:
        return "刚才没查成：%s" % error, None
    except Exception as error:  # 工具坏掉不能把整轮对话弄崩
        traceback.print_exc()
        return "这个操作没成功：%s: %s" % (type(error).__name__, error), None


# 模型偶尔会把工具调用的内部标记直接吐进正文（形如 <｜｜DSML｜｜ invoke name="…">）。
# 那不是给人看的东西：句子要清掉，能认出来的调用要照做，否则员工看到的是一堆乱码。
LEAK_BLOCK = re.compile(r"<[^<>\n]{0,120}?｜[^<>\n]{0,120}?>")
LEAK_INVOKE = re.compile(r"invoke\s+name\s*=\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?", re.I)


def strip_tool_leaks(text):
    text = LEAK_BLOCK.sub("", text or "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def leaked_tools(text):
    if not text or "｜" not in text:
        return []
    return [name for name in LEAK_INVOKE.findall(text)]


def thin_reply(text):
    """只剩一个链接、或者只有几个字，就不算回答了。"""
    bare = re.sub(r"https?://\S+", " ", text or "")
    bare = re.sub(r"[\s。，、；：！？,.!?;:()（）\[\]【】\"'“”‘’—-]+", "", bare)
    return len(bare) < 8


def ask_once_more(project, messages, content):
    """模型交白卷（只发了个链接/几个字）时，礼貌地催一句，让它把结论说出来。"""
    nudge = {"role": "user",
             "content": "别只发链接、也别只回一两个字：用一两句话把结论说给我听，链接放句末。"}
    try:
        again = model_chat(messages + [{"role": "assistant", "content": content}, nudge],
                           tools=None, project_id=project.get("id", "-"))
    except ModelError:
        return ""
    return strip_tool_leaks((again.get("content") or "").strip())


def chat_turn(project, message, flags):
    """跑一轮对话（可多轮工具调用）。返回 (回复文本, 工具轨迹)。"""
    messages = [{"role": "system", "content": agent_system_prompt(project)}]
    messages.extend(agent_history(project))
    trace, calls = [], 0
    for round_index in range(AGENT_MAX_ROUNDS):
        # 最后一轮把工具撤掉：模型必须拿已经查到的东西说话，而不是无限查下去。
        last_round = round_index == AGENT_MAX_ROUNDS - 1
        reply = model_chat(messages, tools=None if last_round else agent_tools(),
                           project_id=project.get("id", "-"))
        tool_calls = reply.get("tool_calls") or []
        content = (reply.get("content") or "").strip()
        if not tool_calls:
            leaked = leaked_tools(content)
            clean = strip_tool_leaks(content)
            if leaked:
                # 模型把调用写成了正文：能认出来的就替它执行，别让员工对着乱码发愣。
                for name in leaked:
                    if name not in ("start_generation", "plan_exhibits", "add_research", "add_material"):
                        continue
                    text, data = run_agent_tool(project, name, {}, flags)
                    trace.append({"tool": name, "arg": "模型把调用写进了正文", "ok": data is not None,
                                  "summary": text.split("\n")[0][:80]})
                return clean or "刚才那步没走通，我重来一遍——你说「生成」我就重新起草。", trace
            if thin_reply(clean):
                # 有人问一句，回一个链接就走，那不叫同事。催它把话说完整一次。
                fuller = ask_once_more(project, messages, content)
                if not thin_reply(fuller):
                    return fuller, trace
            return clean or "我在。需要我查点什么，或者直接动手改哪一块？", trace
        if last_round:
            text = strip_tool_leaks(content)
            if thin_reply(text):
                fuller = ask_once_more(project, messages, content)
                if not thin_reply(fuller):
                    return fuller, trace
            return text or "我把查到的先放这儿，你想继续我再往下深挖。", trace
        messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name") or ""
            try:
                args = json.loads(function.get("arguments") or "{}")
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            calls += 1
            if calls > AGENT_MAX_TOOL_CALLS:
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                 "content": "工具调用次数到上限了，请直接给结论。"})
                continue
            label = tool_label(name, args)
            event(project.get("id", "-"), "chat.tool",
                  {"tool": name, "arg": str(args.get("query") or args.get("url") or args.get("source_id")
                                             or args.get("name") or "")[:60],
                   "state": "start", "message": label})
            text, data = run_agent_tool(project, name, args, flags)
            ok = data is not None
            summary = text.split("\n")[0][:80]
            trace.append({"tool": name, "arg": label, "ok": ok, "summary": summary})
            event(project.get("id", "-"), "chat.tool",
                  {"tool": name, "arg": str(args.get("query") or args.get("url") or "")[:60],
                   "state": "done" if ok else "fail", "message": summary})
            if name == "add_material" and ok:
                save(project)
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": text})
    return "我这轮查得有点久，先说到这儿——你要继续我就接着往下查。", trace


def handle_chat(project, message):
    """一问一答：真调模型，模型可自己决定联网查证、读资料、重做草稿。"""
    history = project.setdefault("chat", [])
    history.append({"role": "user", "text": message, "at": now()})
    save(project)
    flags = {}
    try:
        text, trace = chat_turn(project, message, flags)
    except ModelError as error:
        text = "模型这边没接通：%s。你这句话我先记着了，等接通再回你。" % str(error)[:160]
        trace = []
    history.append({"role": "agent", "text": text, "at": now(), "tools": trace})
    return project, flags


def chat_worker(project_id, message):
    """后台跑一轮对话。前端靠 /events 轮询看到 streaming 的工具动静。"""
    try:
        project = load(project_id)
        project, flags = handle_chat(project, message)
        project.pop("chat_running", None)
        save(project)
        last = (project.get("chat") or [{}])[-1]
        event(project_id, "chat.agent", {"text": last.get("text", ""), "tools": last.get("tools") or []})
        if flags.get("generate"):
            if not exhibit_units(project):
                event(project_id, "chat.failed", {"message": "还没有内容依据，生成不了。"})
                return
            project["status"] = "running"
            project["issues"] = []
            save(project)
            run_pipeline(project_id)
    except Exception as error:
        traceback.print_exc()
        try:
            stale = load(project_id)
            stale.pop("chat_running", None)
            save(stale)
        except Exception:
            pass
        event(project_id, "chat.failed", {"message": "%s: %s" % (type(error).__name__, error)})


def chat_busy(project):
    """同一项目同时只跑一轮对话。超时的旧标记视为失效，否则一次崩溃会让对话永久卡住。"""
    started = project.get("chat_running")
    if not started:
        return False
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()
    except (TypeError, ValueError):
        return False
    return elapsed < CHAT_STALE_SECONDS


def main():
    initialize()
    # 启动护栏：没配口令却监听非本机地址，等于把生成/审批/发布和付费额度敞开给内网。
    # 这里选择「拒绝启动」而不是自动生成口令——自动生成的口令容易被当成没生效。
    if not ACCESS_TOKEN and not is_loopback(HOST):
        raise SystemExit(
            "拒绝启动：STUDIO_HOST=%s 不是本机地址，但没有配置访问口令。\n"
            "  · 正式/内网部署请设置 STUDIO_ACCESS_TOKEN（或 ACCESS_TOKEN）后再启动；\n"
            "  · 只做临时本机演示请用 STUDIO_HOST=127.0.0.1；\n"
            "  · 确认无鉴权风险、仍要对外监听，可显式设置 STUDIO_ALLOW_NO_AUTH=1 跳过这条护栏。"
            % HOST)
    if not ACCESS_TOKEN and os.environ.get("STUDIO_ALLOW_NO_AUTH") == "1":
        print("警告：已按 STUDIO_ALLOW_NO_AUTH=1 跳过鉴权护栏，本服务任何调用方都能触发生成与发布。")
    print("Studio listening on http://%s:%d" % (HOST, PORT))
    print("  鉴权：%s" % ("已启用（X-Access-Token / ?token=）" if ACCESS_TOKEN
                        else "未启用（仅本机监听，生产环境必须配置 STUDIO_ACCESS_TOKEN）"))
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
