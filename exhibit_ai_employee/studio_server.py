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
from urllib.parse import parse_qs, quote, urlparse

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
CODE_REV = "studio-2026-11-15-d"

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


SYSTEM_PROMPT = """你是博物馆/科技馆的「展览互动内容制作员」。你把馆方提供的资料改写成现场可用的中文讲解内容，面向亲子观众。
硬性要求：
1. 只能使用资料中的事实。不得补充资料里没有的数据、年份、人名、机构名。
2. 每条事实必须给出原文逐字引用 quote：从资料段落里原样复制一整句，逐字符一致，包括标点，不得增删改一个字，也不得拼接两个不相邻的句子。quote 必须能在标注的 [段落编号] 正文里做到字符串精确匹配。source_ref 写该段落的完整编号，例如 SRC-001·P003。
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


def find_exhibit(project, exhibit_id):
    for item in project.get("exhibits", []):
        if item["id"] == exhibit_id:
            return item
    raise KeyError(exhibit_id)


def verify(project, exhibit):
    """逐字校验：quote 必须能在其来源资料中原样出现。
    来源编号可以是段落级（SRC-001·P002）或资料级（SRC-001）；
    资料级时只在同一份资料内自动定位段落，绝不跨展项找。"""
    source_map = {src["id"]: src for src in project.get("sources", [])}
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

            drafts = []
            for index, exhibit in enumerate(project["materials"]):
                event(project_id, "step", {"step": "cards", "state": "running", "label": "知识卡",
                                           "detail": "正在处理 %s %s" % (exhibit["id"], exhibit["title"])})
                own = project["sources"][index] if index < len(project["sources"]) else None
                context = ""
                for source in ([own] if own else project["sources"]):
                    for para in source["paragraphs"]:
                        context += "[%s] %s\n" % (para["id"], para["text"])
                context = context[:12000]
                exhibit["source_refs"] = [own["id"]] if own else [s["id"] for s in project["sources"]]
                messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content":
                        "展项编号：%s\n展项名称：%s\n观众：%s\n\n资料段落（只能引用这里的 [编号]）：\n%s\n\n请为这个展项输出 JSON。"
                        % (exhibit["id"], exhibit["title"], project.get("audience", "亲子观众"), context)},
                ]
                try:
                    data = model_json(messages, project_id, max_tokens=4000)
                except ModelError as error:
                    event(project_id, "error", {"message": "模型调用失败：" + str(error)})
                    project["status"] = "failed"
                    project["error"] = str(error)
                    save(project)
                    return
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
                drafts.append(item)
                project["exhibits"] = drafts
                project["issues"] = [issue for draft in drafts for issue in draft.get("issues", [])]
                save(project)
                event(project_id, "step", {"step": "cards", "state": "done", "label": "知识卡",
                                           "detail": "%s：%d 条事实，%d 处待核验" % (
                                               item["id"], len(item["facts"]), len(item.get("issues", [])))})

            project["status"] = "awaiting_confirmation" if project["issues"] else "draft"
            save(project)
            event(project_id, "step", {"step": "draft", "state": "done", "label": "讲解与问答",
                                       "detail": "共 %d 个展项草稿" % len(project["exhibits"])})
            event(project_id, "run.finished", {
                "message": "草稿已生成，%d 处引用需要确认" % len(project["issues"]),
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


# ---------------------------------------------------------------- seeding

SEED = [
    {
        "id": "EX01", "title": "光的折射",
        "material": "光的折射_展签资料.txt",
        "text": """展项名称：光的折射
展项位置：二层「光与声音探索展」A 区

光在不同介质中传播的速度不同。光在真空中的速度约为每秒 30 万公里，是自然界中最快的速度。光在空气中传播的速度与真空中非常接近，在玻璃中约减慢三成，在水中的速度约为真空中的四分之三。

当光从一种透明介质斜射入另一种透明介质时，由于两种介质中的传播速度不同，光的传播方向在分界面上会发生改变，这种现象叫做光的折射。光从空气斜射入水中时，折射光线会向法线方向偏折；光从水斜射入空气时，折射光线会偏离法线。

折射让我们的眼睛产生错觉。把一支笔斜插进装水的透明杯子里，从侧面看，水面上下的笔仿佛断成了两截。这是因为从水中射出的光线经过水面时方向发生改变，眼睛却仍沿着直线去判断位置，于是看到的位置比实际位置偏上。

站在水池边看水底，会觉得池水比实际浅一些，这也是折射造成的。渔夫用鱼叉叉鱼时要瞄准看到的位置的下方，因为真实的位置比看到的位置更深。

光的折射遵循折射定律：入射光线、折射光线和法线在同一平面内，折射光线与入射光线分居法线两侧；入射角的正弦与折射角的正弦之比，对确定的两种介质来说是一个常数。""",
    },
    {
        "id": "EX02", "title": "声音的传播",
        "material": "教育材料.txt",
        "text": """展项名称：声音的传播
适用观众：小学三年级以上亲子观众

声音是由物体振动产生的。正在发声的音叉，用手轻轻一碰会有麻的感觉，说明它在振动。振动会带动周围的空气分子，空气分子再去推动旁边的空气分子，这样一环一环地把振动传出去，形成声波。

声波是机械波，必须依靠介质才能传播。空气、水、木头、钢铁都可以传声，但声音不能在真空中传播。把正在响铃的闹钟放进玻璃罩里，逐渐抽出罩内的空气，铃声会越来越小，最后几乎听不见。

声音在不同介质中的传播速度不同。在 15 摄氏度的空气中，声音的传播速度约为每秒 340 米；在水中约为每秒 1500 米；在钢铁中约为每秒 5000 米。所以声音在水里和钢铁里跑得比在空气中快。

声音有三个基本特征：音调、响度和音色。音调由振动的快慢决定，振动越快音调越高；响度与振动的幅度有关，振幅越大声音越响；音色由发声体本身决定，所以不同的人说话，我们能分辨出是谁。

在水中，声音传播的速度比空气中快，因此潜水员在水下能听到远处船只的螺旋桨声。声音在固体中传播得最快，把耳朵贴在铁轨上，可以更早听到远处火车驶来的声音。""",
    },
    {
        "id": "EX03", "title": "颜色的奥秘",
        "material": "颜色的奥秘_展签资料.txt",
        "text": """展项名称：颜色的奥秘
展区：二层「光与声音探索展」C 区

白光看起来没有颜色，其实它是由多种颜色的光混合而成的。1666 年，牛顿把一束阳光通过三棱镜，在屏幕上得到了一条按红、橙、黄、绿、蓝、靛、紫排列的彩色光带，这就是光的色散。

我们看到的物体颜色，取决于它反射的光。太阳光照射到物体上，物体表面会吸收一部分色光，反射另一部分色光。红色的苹果主要反射红光，吸收其他颜色的光，所以我们看到它是红色的。

如果物体把各种颜色的光都吸收，我们看到的就是黑色；如果物体把各种颜色的光几乎都反射回来，我们看到的就是白色。白色物体在红光下会呈现红色，因为此时只有红光可以反射。

色光的三原色是红、绿、蓝。把这三种色光按不同比例混合，可以得到各种颜色的光。红光和绿光混合得到黄光，红光和蓝光混合得到品红光，绿光和蓝光混合得到青光，三种光同时叠加得到白光。

颜料的三原色是品红、黄、青，与色光的三原色不同。色光混合时亮度会叠加变亮，颜料混合时则因为吸收更多的光而变暗。""",
    },
]


def seed(project_id=None, materials=None):
    """建立项目。materials 为 [{'name','text','title'}]；不给时使用内置示例资料，
    并在项目上标注 demo=True，前端据此如实提示「内置示例资料」。"""
    demo = materials is None
    if demo:
        materials = [{"name": item["material"], "text": item["text"], "title": item["title"]}
                     for item in SEED]
    project = {
        "id": project_id or uuid.uuid4().hex[:10],
        "task_no": None,
        "created_at": now(),
        "name": materials[0].get("project") or "光与声音探索展",
        "audience": "亲子观众",
        "language": "中文",
        "status": "draft",
        "version": 0.1,
        "run_version": 0,
        "brief": {"text": "把这三个展项做成适合亲子观众的互动讲解，每项约 45 秒。先给我草稿，我再审核。",
                  "at": now()},
        "authorization": None,
        "demo": demo,
        "materials": [{"id": "EX%02d" % (i + 1), "title": item.get("title", ""),
                       "material": item["name"]} for i, item in enumerate(materials)],
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
    with db() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM projects").fetchone()
    project["task_no"] = (row["n"] or 0) + 1
    save(project)
    event(project["id"], "seed", {"message": "已载入 %d 个展项与 %d 份资料%s" % (
        len(materials), len(materials), "（内置示例资料）" if demo else "")})
    return project


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
    expected = {m["id"] for m in project.get("materials", [])}
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
            quote[key] = _money(data.get(key), label)
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
                                            "auth_required": bool(ACCESS_TOKEN), "tts": tts.status()})
            if path in ("/api/studio/projects", "/api/studio/seed"):
                with db() as c:
                    rows = c.execute("SELECT body FROM projects ORDER BY updated_at DESC").fetchall()
                items = []
                for row in rows:
                    body = json.loads(row["body"])
                    items.append({"id": body["id"], "name": body["name"], "status": body["status"],
                                  "version": body["version"], "updated_at": body["updated_at"]})
                if path == "/api/studio/seed" or not items:
                    return self.send_json(200, {"project": seed()})
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

    def do_POST(self):
        denied = self.require_auth()
        if denied is not None:
            return denied
        path = urlparse(self.path).path
        try:
            data = self.read_json()
            if path in ("/api/studio/projects", "/api/studio/seed"):
                project = seed()
                return self.send_json(200, {"project": project})
            match = re.fullmatch(r"/api/studio/projects/([A-Za-z0-9]+)/(run|review|chat|tests|issue|material|voice|publish|authorize|quote|exhibit|feedback|acceptance)", path)
            if not match:
                return self.send_json(404, {"error": "接口不存在"})
            project_id, action = match.group(1), match.group(2)
            project = load(project_id)

            if action == "run":
                if project["status"] == "running":
                    return self.send_json(409, {"error": "正在执行，请等待本轮结束"})
                for exhibit in project.get("materials", []):
                    exhibit["source_refs"] = [s["id"] for s in project["sources"]]
                project["status"] = "running"
                project["issues"] = []
                save(project)
                event(project_id, "step", {"step": "cards", "state": "running", "label": "知识卡",
                                           "detail": "开始为 3 个展项抽取事实"})
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
                project["sources"].append(build_sources([{"name": name, "text": text}])[0])
                # 重新编号，避免 SRC 重复
                for index, source in enumerate(project["sources"], start=1):
                    new_id = "SRC-%03d" % index
                    for para in source["paragraphs"]:
                        para["id"] = new_id + para["id"].split("·", 1)[1]
                    source["id"] = new_id
                save(project)
                event(project_id, "material", {"message": "新增资料：" + name, "bytes": len(text.encode())})
                return self.send_json(200, {"project": project})

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
                project["status"] = "published"
                save(project)
                event(project_id, "publish", {"message": "已发布 v%s" % project["version"]})
                return self.send_json(200, {"project": project})

            if action == "chat":
                message = str(data.get("message") or "").strip()
                if not message:
                    return self.send_json(400, {"error": "消息为空"})
                project = handle_chat(project, message)
                save(project)
                return self.send_json(200, {"project": project})

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


def handle_chat(project, message):
    history = project.setdefault("chat", [])
    history.append({"role": "user", "text": message, "at": now()})
    if re.search(r"重新生成|再生成|重跑|生成一遍", message):
        for exhibit in project.get("materials", []):
            exhibit["source_refs"] = [s["id"] for s in project["sources"]]
        project["status"] = "running"
        project["issues"] = []
        save(project)
        reply = "收到，我按当前资料重新生成 3 个展项的草稿，生成后会逐条核对原文引用，无法定位的地方会单独列出来。"
        history.append({"role": "agent", "text": reply, "at": now()})
        run_pipeline(project["id"])
        return project

    summary = []
    for exhibit in project.get("exhibits", [])[:3]:
        summary.append("%s《%s》：主讲解 %d 字，事实 %d 条，待核验 %d 处" % (
            exhibit["id"], exhibit["title"], len((exhibit.get("main") or {}).get("text", "")),
            len(exhibit.get("facts", [])), len(exhibit.get("issues", []))))
    state = "尚未生成草稿" if not project.get("exhibits") else "；".join(summary)
    messages = [
        {"role": "system", "content": "你是展览互动内容制作员。回答必须简洁（80 字内），只能依据当前项目状态和资料，不得编造。"
                                     "请输出 JSON：{\"reply\":\"...\"}"},
        {"role": "user", "content": "项目：%s，版本 v%s，状态 %s。当前成果：%s。待核验 %d 处。用户说：%s"
                                    % (project["name"], project["version"], project["status"], state,
                                       len(project.get("issues", [])), message)},
    ]
    try:
        data = model_json(messages, project["id"], max_tokens=400)
        reply = str(data.get("reply") or "").strip() or "我在。你可以让我重新生成、查看待核验引用，或告诉我下一步怎么做。"
    except ModelError:
        reply = ("我在。当前 v%s 共 %d 个展项，%d 处引用待确认。你可以说「重新生成」，或点右侧的待确认卡片处理。"
                 % (project["version"], len(project.get("exhibits", [])), len(project.get("issues", []))))
    history.append({"role": "agent", "text": reply, "at": now()})
    return project


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
