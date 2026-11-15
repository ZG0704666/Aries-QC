#!/usr/bin/env python3
import difflib
import json
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("EXHIBIT_DB", ROOT / "employee.sqlite3"))
SOUL_PATH = ROOT / "config" / "SOUL.md"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "4181"))


def load_local_env():
    """读取本机 .env.local（已在 .gitignore 中），不覆盖已存在的环境变量。"""
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
# 兼容多种密钥命名：通用 AI_API_KEY 优先，其次各家专名
API_KEY = (
    os.environ.get("AI_API_KEY")
    or os.environ.get("DEEPSEEK_API_KEY")
    or os.environ.get("GMI_API_KEY")
    or ""
)
MODEL = os.environ.get("AI_MODEL", "deepseek-chat")
DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() in ("1", "true", "yes")
# 审计 #10：全站零鉴权，/api/review、/export、/api/runs 可被任意调用。
# 设 ACCESS_TOKEN 后所有接口需带 X-Access-Token 头或 ?token= 参数。
# 默认空值表示不启用（仅供本机 127.0.0.1 演示）；部署到公网必须设置。
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "")
APP_VERSION = "3.0"
EXHIBIT_IDS = ("A", "B", "C")

# Breeze Blue 语音合成。只在配置了 key 时启用，未配置就如实报"未配置"，不用浏览器 TTS 冒充。
BREEZE_BASE = os.environ.get("BREEZE_BASE_URL", "https://api.breeze.blue").rstrip("/")
BREEZE_KEY = os.environ.get("BREEZE_API_KEY", "")
BREEZE_VOICE = os.environ.get("BREEZE_VOICE_ID", "")
BREEZE_MODEL = os.environ.get("BREEZE_MODEL_ID", "")
AUDIO_DIR = Path(os.environ.get("EXHIBIT_AUDIO_DIR", ROOT / "audio"))


def db():
    connection = sqlite3.connect(DB_PATH, timeout=15.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def initialize():
    with db() as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, title TEXT NOT NULL, source_name TEXT NOT NULL, source_text TEXT NOT NULL, draft TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', validation TEXT NOT NULL DEFAULT '{}', mode TEXT NOT NULL DEFAULT 'demo', version INTEGER NOT NULL DEFAULT 1, sources TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '')")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        for name, declaration in (("mode", "TEXT NOT NULL DEFAULT 'demo'"), ("version", "INTEGER NOT NULL DEFAULT 1"), ("sources", "TEXT NOT NULL DEFAULT '{}'"), ("error", "TEXT NOT NULL DEFAULT ''")):
            if name not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN %s %s" % (name, declaration))
        connection.execute("CREATE TABLE IF NOT EXISTS versions (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL, draft TEXT NOT NULL, validation TEXT NOT NULL, diff TEXT NOT NULL, actor TEXT NOT NULL, UNIQUE(run_id,version))")
        connection.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, run_id INTEGER, created_at TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS test_records (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, number TEXT NOT NULL, test_input TEXT NOT NULL, expected TEXT NOT NULL, actual TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('passed','failed','not_run')), created_at TEXT NOT NULL, version INTEGER NOT NULL, mode TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS api_calls (id INTEGER PRIMARY KEY, run_id INTEGER, created_at TEXT NOT NULL, mode TEXT NOT NULL, endpoint TEXT NOT NULL, model TEXT NOT NULL, outcome TEXT NOT NULL, http_status INTEGER, elapsed_ms INTEGER NOT NULL, error TEXT NOT NULL, prompt_tokens INTEGER, completion_tokens INTEGER)")
        # token 用量列用于成本自动核算（商业审计 ②），旧库需补列
        api_columns = {row[1] for row in connection.execute("PRAGMA table_info(api_calls)")}
        for name in ("prompt_tokens", "completion_tokens"):
            if name not in api_columns:
                connection.execute("ALTER TABLE api_calls ADD COLUMN %s INTEGER" % name)
        connection.execute("CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, run_id INTEGER, category TEXT NOT NULL, note TEXT NOT NULL, candidate TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1)")
        connection.execute("CREATE TABLE IF NOT EXISTS business (id INTEGER PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL)")
        # 商业审计 ①：付费逻辑此前只活在文档里。补客户、报价、验收凭据三张表，
        # 让"谁付钱、付了多少、是否复购"可被查询和计算，而不是只能靠嘴说。
        connection.execute(
            "CREATE TABLE IF NOT EXISTS customers ("
            " id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, name TEXT NOT NULL,"
            " contact TEXT NOT NULL DEFAULT '', budget_owner TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '')"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS quotes ("
            " id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, customer_id INTEGER NOT NULL,"
            " run_id INTEGER, amount REAL, currency TEXT NOT NULL DEFAULT 'CNY',"
            " basis TEXT NOT NULL DEFAULT 'assumed' CHECK(basis IN ('assumed','interviewed','signed')),"
            " scope TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '')"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS acceptances ("
            " id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, run_id INTEGER NOT NULL,"
            " quote_id INTEGER, signed_by TEXT NOT NULL DEFAULT '', signed_at TEXT NOT NULL DEFAULT '',"
            " amount REAL, criteria TEXT NOT NULL DEFAULT '[]', note TEXT NOT NULL DEFAULT '')"
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        if "customer_id" not in columns:
            connection.execute("ALTER TABLE runs ADD COLUMN customer_id INTEGER")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def record_event(connection, run_id, event, detail):
    connection.execute("INSERT INTO events(run_id,created_at,event,detail) VALUES(?,?,?,?)", (run_id, now(), event, json_text(detail)))


def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型未返回 JSON 对象")
    return json.loads(text[start:end + 1])


def soul_text():
    if not SOUL_PATH.is_file():
        raise RuntimeError("缺少岗位原则文件：%s；按第零原则停止生成" % SOUL_PATH)
    content = SOUL_PATH.read_text(encoding="utf-8-sig").strip()
    if not content:
        raise RuntimeError("config/SOUL.md 为空；按第零原则停止生成")
    return content


INTENTS = ("intake", "generate", "ask", "tests", "tts", "approve", "reject", "export", "help", "chat", "reset")


def chat_completion(system, user, temperature=0.2, run_id=None, timeout=60):
    """一次纯文本模型调用，供意图路由使用。失败就抛错，由调用方降级到规则路由。"""
    if not API_KEY or not MODEL:
        raise RuntimeError("未配置模型凭据")
    body = json.dumps({
        "model": MODEL,
        "temperature": temperature,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(API_BASE + "/chat/completions", data=body,
                                     headers={"Authorization": "Bearer " + API_KEY,
                                              "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    outcome, status, error_text = "failed", None, ""
    prompt_tokens = completion_tokens = None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            payload = json.loads(response.read().decode("utf-8"))
        usage = payload.get("usage") or {}
        prompt_tokens, completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
        outcome = "success"
        return payload["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as error:
        status = error.code
        error_text = error.read(600).decode("utf-8", errors="replace")
        raise RuntimeError("模型 API HTTP %s：%s" % (status, error_text[:300]))
    except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as error:
        error_text = str(error)
        raise RuntimeError("模型调用失败：%s" % error_text[:300])
    finally:
        with db() as connection:
            connection.execute(
                "INSERT INTO api_calls(run_id,created_at,mode,endpoint,model,outcome,http_status,"
                "elapsed_ms,error,prompt_tokens,completion_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, now(), "live", API_BASE + "/chat/completions", MODEL, outcome, status,
                 int((time.monotonic() - started) * 1000), error_text[:500], prompt_tokens, completion_tokens),
            )


def route_intent(text, state):
    """让模型判断这句话要做什么，而不是靠关键词匹配。

    返回 {intent, exhibit_id, question, reply, materials}。
    模型不可用时抛错，调用方退回规则路由。
    """
    system = (
        "你是展陈项目助手的意图识别器。用户会用自然语言说话，你要判断他想做什么。\n"
        "可选 intent：\n"
        "  intake —— 用户贴了展项资料/介绍/文案，想让你整理\n"
        "  generate —— 资料已经就绪，用户要开始整理成讲解稿\n"
        "  ask —— 用户在问某个展项的具体问题（需要 exhibit_id 和 question）\n"
        "  tests —— 用户要测试用例 / 验收 / 测试\n"
        "  tts —— 用户要把讲解合成语音 / 配音 / 朗读\n"
        "  approve —— 用户表示认可、通过、可以交付\n"
        "  reject —— 用户表示不行、退回、要改\n"
        "  export —— 用户要导出 / 下载交付包\n"
        "  help —— 用户在问你能做什么、怎么用\n"
        "  chat —— 打招呼、闲聊、与业务无关的话（你自己写一句自然的回复）\n"
        "  reset —— 用户想重新开始 / 换一个项目\n"
        "规则：\n"
        "  · 用户消息里有大段展项资料，一定是 intake，资料放进 materials 字段。\n"
        "  · ask 要尽量认出展项编号（A/B/C）；认不出就留空，由程序按内容去匹配。\n"
        "  · 不要因为用户说了“你好”就让他去贴资料；那是 chat，回一句自然的话，并简短说明你现在处在哪一步、下一步能做什么。\n"
        "  · reply 只在 chat / help 时使用，写成给用户看的自然语言，不要提“意图”“分类”这类词。\n"
        "只返回 JSON：{\"intent\":\"...\",\"exhibit_id\":\"A\",\"question\":\"...\",\"reply\":\"...\",\"materials\":\"...\"}"
    )
    user = json.dumps({"message": text[:20000], "state": state}, ensure_ascii=False)
    raw = chat_completion(system, user, temperature=0.0)
    result = extract_json(raw)
    intent = str(result.get("intent") or "").strip()
    if intent not in INTENTS:
        raise RuntimeError("未知意图：%s" % intent)
    return {
        "intent": intent,
        "exhibit_id": str(result.get("exhibit_id") or "").strip().upper()[:1],
        "question": str(result.get("question") or "").strip()[:500],
        "reply": str(result.get("reply") or "").strip()[:800],
        "materials": str(result.get("materials") or "").strip()[:40000],
    }


def rule_intent(text, state):
    """模型不可用时的规则兜底。比关键词宽松：识别不了的当聊天处理。"""
    t = (text or "").strip()
    if not t:
        return {"intent": "chat", "exhibit_id": "", "question": "", "reply": "", "materials": ""}
    material = EXHIBIT_MARKER.search(t) or len(t) > 120
    if material and EXHIBIT_MARKER.search(t):
        return {"intent": "intake", "exhibit_id": "", "question": "", "reply": "", "materials": t}
    if re.search(r"开始|生成|整理|开工|出稿", t) and state.get("has_exhibits"):
        return {"intent": "generate", "exhibit_id": "", "question": "", "reply": "", "materials": ""}
    if re.search(r"测试|用例|验收", t) and state.get("has_draft"):
        return {"intent": "tests", "exhibit_id": "", "question": "", "reply": "", "materials": ""}
    if re.search(r"语音|配音|朗读|合成|音频", t) and state.get("has_draft"):
        mid = re.search(r"([A-Ca-c])", t)
        return {"intent": "tts", "exhibit_id": mid.group(1).upper() if mid else "", "question": "", "reply": "", "materials": ""}
    if re.search(r"通过|批准|可以了|没问题", t) and state.get("run_id"):
        return {"intent": "approve", "exhibit_id": "", "question": "", "reply": "", "materials": ""}
    if re.search(r"退回|重做|不行|改一下", t) and state.get("run_id"):
        return {"intent": "reject", "exhibit_id": "", "question": "", "reply": "", "materials": ""}
    if re.search(r"导出|下载|交付包", t) and state.get("run_id"):
        return {"intent": "export", "exhibit_id": "", "question": "", "reply": "", "materials": ""}
    if re.search(r"帮助|怎么用|能做什么", t):
        return {"intent": "help", "exhibit_id": "", "question": "", "reply": "", "materials": ""}
    if re.search(r"[？?]|讲了什么|是什么|多少|什么时候|谁", t) and state.get("run_id"):
        mid = re.search(r"([A-Ca-c])\s*展项|展项\s*([A-Ca-c])", t)
        eid = (mid.group(1) or mid.group(2)).upper() if mid else ""
        return {"intent": "ask", "exhibit_id": eid, "question": t, "reply": "", "materials": ""}
    if len(t) > 60:
        return {"intent": "intake", "exhibit_id": "", "question": "", "reply": "", "materials": t}
    return {"intent": "chat", "exhibit_id": "", "question": "", "reply": "", "materials": ""}


def call_live(title, sources, run_id=None):
    if not API_KEY or not MODEL:
        raise RuntimeError("真实生成未调用：必须配置 GMI_API_KEY 与 AI_MODEL")
    system = soul_text()
    payload = {
        "title": title,
        "exhibits": [{"exhibit_id": exhibit_id, "source_name": item["source_name"], "source_text": item["source_text"]} for exhibit_id, item in sources.items()],
        "instruction": (
            "任务：为每个展项各写一张语音讲解卡，供展陈集成商交付客户审核。\n\n"
            "一、先判断这份资料能不能支撑讲解，但判据从严限定：\n"
            "  · 只有下列两种情况才算 missing_materials：\n"
            "    (a) 资料里明确写了缺项（如「未提供」「待补」「不详」）；\n"
            "    (b) 资料中没有任何可用于描述该展品的事实（例如只有编号，没有形制、年代、来源等）。\n"
            "  · 严禁把「资料没写展厅位置」「没写观众须知」「没写开放时间」这类讲解不必需的信息算作缺料。\n"
            "  · location 字段请直接填「展项 A/B/C」，不要因位置未写明而报缺料。\n"
            "  · 只要资料有可描述的事实，就必须正常生成卡片。\n\n"
            "二、conflicts 仅在同一对象出现互相矛盾的具体事实时填写（如两个不同年份、两种材质鉴定），"
            "并引用双方原文；没有矛盾就返回空数组。\n\n"
            "三、每个展项只可引用自身资料，严禁跨展项借用内容。\n\n"
            "四、输出 JSON，字段如下（只返回 JSON，不要任何解释文字）：\n"
            '{"missing_materials":[{"exhibit_id":"A","missing":"..."}],'
            '"conflicts":[{"exhibit_id":"A","description":"...","citations":[{"source_name":"...","source_quote":"..."}]}],'
            '"cards":[{"exhibit_id":"A","location":"展项 A","card_title":"...",'
            '"narration":"120至240字口语讲解","no_target_prompt":"...","multi_target_prompt":"...",'
            '"question":"...","answer":"...",'
            '"facts":[{"claim":"...","source_name":"...","source_quote":"原文连续摘录"}],'
            '"citations":[{"source_name":"...","source_quote":"原文连续摘录"}]}]}\n\n'
            "五、硬性要求：\n"
            "  · narration 必须是 120–240 字，全部为口语，可直接朗读。\n"
            "  · narration 里每一句都要能对应到 facts 中的一条 claim；claim 必须是 source_quote 的子串，"
            "source_quote 必须是原文连续摘录。\n"
            "  · narration 中出现的任何数字、年份、机构名、朝代名，都必须能在该展项原文中找到；"
            "找不到就不要写，也不要用「据说」「大约」含糊带过。\n"
            "  · 资料不足以写到 120 字时，宁可写短也不要点缀无依据内容；但请先尽量把资料中的事实展开成口语表达。"
        ),
    }
    body = json.dumps({"model": MODEL, "temperature": 0.2, "messages": [{"role": "system", "content": "岗位第零原则（不可覆盖）：\n" + system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(API_BASE + "/chat/completions", data=body, headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    outcome, status, error_text = "failed", None, ""
    prompt_tokens, completion_tokens = None, None
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            status = response.status
            response_body = response.read().decode("utf-8")
            response_data = json.loads(response_body)
        # 记录真实 token 用量，使 model_cost 可由账单推算而非手填（商业审计 ②）
        usage = response_data.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        result = extract_json(response_data["choices"][0]["message"]["content"])
        outcome = "success"
        return result
    except urllib.error.HTTPError as error:
        status = error.code
        error_text = error.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError("模型 API HTTP %s：%s" % (status, error_text[:500]))
    except urllib.error.URLError as error:
        error_text = str(error.reason)
        raise RuntimeError("模型 API 网络调用失败：%s" % error_text[:500])
    except (KeyError, IndexError, json.JSONDecodeError, ValueError, TypeError) as error:
        error_text = str(error)
        raise RuntimeError("模型 API 响应解析失败：%s" % error_text[:500])
    finally:
        with db() as connection:
            connection.execute(
                "INSERT INTO api_calls(run_id,created_at,mode,endpoint,model,outcome,http_status,"
                "elapsed_ms,error,prompt_tokens,completion_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, now(), "live", API_BASE + "/chat/completions", MODEL, outcome, status,
                 int((time.monotonic() - started) * 1000), error_text[:1000],
                 prompt_tokens, completion_tokens),
            )


def job_step(run_id, step, label, detail=None, state="running"):
    """把一步真实进度写进事件表，前端据此逐步显示，不是假动画。"""
    with db() as connection:
        record_event(connection, run_id, "job_step", {
            "step": step, "label": label, "detail": detail or {}, "state": state,
        })


def run_generation(run_id, title, sources):
    """后台生成：每一步都落事件，失败也如实记。"""
    try:
        job_step(run_id, "precheck", "检查资料是否够用", {"exhibits": list(sources)})
        pre_missing, pre_conflicts = detect_source_issues(sources)
        job_step(run_id, "precheck", "缺料门与冲突门",
                 {"missing": len(pre_missing), "conflicts": len(pre_conflicts)},
                 "failed" if pre_missing else "done")
        # 只有缺料才阻断：资料里没有事实，写不出有依据的讲解。
        # 来源冲突（同一对象两处说法不一致）不阻断生成，改为传给模型并在
        # 校验结果里作为警告抛出，由人确认采用哪种说法。
        if pre_conflicts:
            job_step(run_id, "precheck", "发现 %d 处来源冲突，将作为待确认项" % len(pre_conflicts),
                     {"conflicts": pre_conflicts}, "done")
        if pre_missing:
            message = "资料缺料，需客户补充后再生成"
            with db() as connection:
                connection.execute("UPDATE runs SET status='blocked',error=? WHERE id=?", (message, run_id))
                record_event(connection, run_id, "blocked_before_generation",
                             {"missing": pre_missing, "conflicts": pre_conflicts})
            return
        job_step(run_id, "generate", "按展项写讲解与出处", {"mode": "demo" if DEMO_MODE else "live"})
        if DEMO_MODE:
            draft = generate_demo(title, sources)
        else:
            draft = call_live(title, sources, run_id)
        cards = draft.get("cards") or []
        job_step(run_id, "generate", "已写出 %d 张知识卡" % len(cards),
                 {"cards": [{"exhibit_id": c.get("exhibit_id"), "chars": len(c.get("narration") or "")} for c in cards
                            if isinstance(c, dict)]}, "done")
        job_step(run_id, "validate", "逐门核对")
        validation = validate_draft(sources, draft, progress=lambda name, detail: job_step(
            run_id, "validate", name, {"detail": detail}))
        job_step(run_id, "validate",
                 "质量门 %d/%d" % (validation.get("checks", 0), validation.get("total_checks", 0)),
                 {"issues": validation.get("issues", [])}, "done" if validation.get("passed") else "failed")
        status = "draft" if validation["passed"] else "blocked"
        with db() as connection:
            connection.execute("UPDATE runs SET draft=?,status=?,validation=? WHERE id=?",
                               (json_text(draft), status, json_text(validation), run_id))
            connection.execute("INSERT INTO versions(run_id,version,created_at,draft,validation,diff,actor) VALUES(?,?,?,?,?,?,?)",
                               (run_id, 1, now(), json_text(draft), json_text(validation), "[]",
                                "model" if not DEMO_MODE else "demo-template"))
            record_event(connection, run_id, "generation_completed",
                         {"status": status, "validation": validation})
    except Exception as error:
        message = str(error)[:1000]
        with db() as connection:
            connection.execute("UPDATE runs SET status='failed',error=? WHERE id=?", (message, run_id))
            record_event(connection, run_id, "generation_failed", {"error": message})
        job_step(run_id, "generate", "生成失败", {"error": message}, "failed")


def generate_demo(title, sources):
    """演示模板：只摘录原文拼成讲解，不含任何模型补写，因此能如实通过覆盖门。

    demo 标识放在 card 的 _demo 字段和导出水印上，不塞进讲解正文——
    讲解正文是给观众听的，不能混入流程说明。
    """
    cards = []
    for exhibit_id, item in sources.items():
        text = item["source_text"]
        parts = [s for s in sentence_split(text) if len(s) >= 8] or [text]
        narration = ""
        for sentence in parts:
            if len(narration) >= 120:
                break
            narration += sentence
        # 资料不足以凑满 120 字时，不循环拼接原文——那会让讲解出现重复句，
        # 客户一眼看出是机器凑数。改为如实保留较短内容，并在 facts 里只映射
        # 真实用到的句子；长度门会因此不过，这正是"资料不足"的诚实体现。
        narration = narration[:240]
        # 按出现顺序去重，避免同一句被算作两条事实
        used = []
        for sentence in parts:
            if sentence in narration and sentence not in used:
                used.append(sentence)
        cards.append(
            {
                "exhibit_id": exhibit_id,
                "location": "展项 " + exhibit_id,
                "card_title": title + "｜演示卡 " + exhibit_id,
                "narration": narration,
                "no_target_prompt": "您可以选择一个展项，听它的介绍。",
                "multi_target_prompt": "检测到多个候选，请在屏幕上选择要听的展项。",
                "question": "资料中记载了什么？",
                "answer": used[0][:120] if used else text[:120],
                "facts": [{"claim": s, "source_name": item["source_name"], "source_quote": s} for s in used],
                "citations": [{"source_name": item["source_name"], "source_quote": s} for s in used],
                "_demo": True,
            }
        )
    return {"missing_materials": [], "conflicts": [], "cards": cards}


def normalize_sources(data):
    exhibits = data.get("exhibits")
    if not isinstance(exhibits, list) or not (1 <= len(exhibits) <= 3):
        raise ValueError("请提供 1–3 个展项资料")
    result = {}
    for entry in exhibits:
        if not isinstance(entry, dict):
            raise ValueError("展项资料格式无效")
        exhibit_id = str(entry.get("exhibit_id", "")).strip().upper()
        if exhibit_id not in EXHIBIT_IDS or exhibit_id in result:
            raise ValueError("展项编号必须是 A、B、C 之一且不能重复")
        name = str(entry.get("source_name", "")).strip()[:200]
        text = str(entry.get("source_text", "")).strip()[:20000]
        result[exhibit_id] = {"source_name": name, "source_text": text}
    if not result:
        raise ValueError("没有可用的展项资料")
    return {key: result[key] for key in sorted(result)}


def sentence_split(text):
    return [s.strip() for s in re.split(r"(?<=[。！？!?；;])\s*", text or "") if s.strip()]


def lcs_len(a, b):
    """最长公共连续子串长度，用于判断两句话是否在讲同一件事。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for ca in a:
        cur = [0] * (len(b) + 1)
        for j, cb in enumerate(b, 1):
            if ca == cb:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


MISSING_MARKERS = ("未提供", "待补", "待客户补充", "资料缺", "暂无资料", "资料未覆盖", "未说明", "不详")
CONFLICT_MARKERS = (
    "但另一种说法", "另据", "然而资料", "说法不一", "说法不同", "说法各异", "相互矛盾", "相互冲突",
    "与此矛盾", "不一致", "存在冲突", "有出入", "两种说法", "记载不一", "口径不同", "尚存争议",
)
YEAR_OR_NUM = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)|\d+(?:\.\d+)?")
# 中文数字年份：资料常写"一八五零年""一九五八年"，必须一并识别，否则冲突门会漏检
CN_DIGITS = {"〇": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
CN_YEAR = re.compile(r"([〇零一二三四五六七八九]{4})\s*年")
# 中文数字（非年份）：三、十五、二百、三十厘米等，用于数字门
CN_NUMERAL = re.compile(r"[〇零一二三四五六七八九十百千万两]+(?=[个件年月日米度秒分种层号位种])")


def cn_years(text):
    """把资料中的中文数字年份转成阿拉伯数字，例如 一八五零年 → 1850。"""
    return [int("".join(CN_DIGITS[ch] for ch in match)) for match in CN_YEAR.findall(text or "")]


def cn_numerals(text):
    """提取中文数字串（含年份），用于数字门比对中文表述。"""
    found = set(CN_YEAR.findall(text or ""))
    found.update(CN_NUMERAL.findall(text or ""))
    return found


def all_years(text):
    """返回资料中的全部四位年份（阿拉伯 + 中文），用于冲突比对。"""
    found = [int(y) for y in re.findall(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)", text or "")]
    found.extend(cn_years(text))
    return found


# 中文专名识别：机构后缀是最可靠的信号（厂/馆/院/所/公司/大学/政府…）。
# 不匹配"X纹""X器"这类器物描述——"器""纹"是泛字，会把"同类器物""判断器物"等
# 普通表述误判为专名。器物层面的编造由反向覆盖门和数字门拦截，更准确。
ORG_SUFFIX = "厂|馆|院|所|公司|大学|学院|政府|局|委员会|协会|学会|研究院|博物馆|美术馆|档案馆|图书馆"
# 机构名前不能把整句吞进去：允许的字符集排除虚词和动词，长度上限收紧到 8
ORG_TAIL = re.compile(r"((?:[一-鿿]{2,8})(?:%s))(?![一-鿿])" % ORG_SUFFIX)
# 常见的"某地某馆"式机构名，前面是地名或修饰语时只在紧邻处匹配
ORG_STOP = set("现在收藏在市县区省国各地本馆该这那个件些有是了在于从对把被让给和与及或的都也还很更最已经曾将要会能可")


def cn_proper_nouns(text):
    """提取中文专名候选：机构名与朝代名。

    只取紧邻的机构后缀，且前面必须像地名/专名——避免把
    "现在收藏在市博物馆" 整句当成机构名（那是动词短语，不是专名）。
    """
    found = set()
    for match in ORG_TAIL.findall(text or ""):
        # 去掉前导虚词与动词，只保留真正的名字部分
        name = match
        while name and name[0] in ORG_STOP:
            name = name[1:]
        if len(name) >= 3 and not any(ch in ORG_STOP for ch in name[:-2]):
            found.add(name)
    for match in re.findall(r"((?:夏|商|西周|东周|春秋|战国|秦|西汉|东汉|三国|隋|唐|五代|宋|辽|金|元|明|清)(?:代|时期))", text or ""):
        found.add(match)
    return found


def same_fact(claim, narration, threshold=0.55):
    """判断 claim 与 narration 是否在讲同一件事。

    模型会做口语化改写（"织物残片为汉代丝织品" → "一片汉代丝织品残片"），
    逐字匹配或要求长公共子串都会误伤。这里用"claim 的字符有多少能在
    narration 的局部窗口里找到"来判定，既容忍改写，又能拒绝完全无关的表述。
    """
    claim = re.sub(r"\s+", "", claim or "")
    narration = re.sub(r"\s+", "", narration or "")
    if not claim or not narration:
        return False
    if claim in narration:
        return True
    window = min(len(narration), max(len(claim) * 2, 24))
    best = 0.0
    for start in range(0, max(1, len(narration) - window + 1), max(1, window // 3)):
        segment = narration[start : start + window]
        # 统计 claim 中有多少字符出现在该片段里（按字符种类计，不重复计同字）
        hit = sum(1 for ch in set(claim) if ch in segment)
        best = max(best, hit / max(1, len(set(claim))))
        if best >= threshold:
            return True
    return best >= threshold


COVER_STOP = set("的了是在和与及或吗呢吧啊这那个些一有不我你他她它请问能可要会还就很也都被把对从向于为之其以则而并且但所")

def _support_score(clause, blob):
    """一个分句有多少支撑：取"最长公共子串"和"实义字重合率"里更强的那个。

    模型做口语化改写（"本展项展出一件西周青铜鼎" → "这件展品是一件西周时期的青铜鼎"）
    时，长公共子串只有三四个字，纯 LCS 会全部误判成无依据。
    但两句话的实义字高度重合，所以补一个重合率判据。
    """
    if not clause or not blob:
        return 0.0
    best = 0
    step = 200
    for start in range(0, max(1, len(blob)), step):
        best = max(best, lcs_len(clause, blob[start : start + step + 40]))
    # LCS 已经够长，直接算有支撑
    if best >= 6:
        return 1.0
    content = [ch for ch in set(clause) if ch not in COVER_STOP]
    if not content:
        return 1.0
    overlap = sum(1 for ch in content if ch in blob) / len(content)
    # 重合率高且至少有一小段连续匹配，才算同一件事
    return overlap if best >= 3 else overlap * 0.6


def coverage_gaps(narration, supports, min_len=12):
    """返回讲解中没有事实映射支撑的句子。

    判定：一句里至少有一个分句能在 claim/引用中找到支撑，
    或显式标注待确认。全部无支撑才算无依据补写。
    """
    support_blob = " ".join(s for s in supports if s)
    if not support_blob:
        return [s[:24] for s in sentence_split(narration) if len(s) >= min_len]
    gaps = []
    for sentence in sentence_split(narration):
        if len(sentence) < min_len:
            continue
        if any(mark in sentence for mark in MISSING_MARKERS) or "待确认" in sentence:
            continue
        clauses = [c.strip() for c in re.split(r"[，,、；;]", sentence) if len(c.strip()) >= 6] or [sentence]
        scores = [_support_score(clause, support_blob) for clause in clauses]
        # 只要有一个分句有足够支撑，这句就算有依据（整句是同一事实的展开）
        if not scores or max(scores) < 0.5:
            gaps.append(sentence[:24])
    return gaps


def detect_source_issues(sources):
    """程序化检测资料本身的缺料与冲突，不依赖模型自报。

    缺料：资料里出现"未提供/待补"等标记，或该展项没有任何一句达到可支撑讲解的长度。
    冲突：同一展项资料内部，两个不同数值出现在语境高度重叠的句子里（例如同一展品的两个年份），
          或出现"另据/说法不一"等显式冲突标记。
    """
    missing, conflicts = [], []
    for exhibit_id, item in sources.items():
        text = item["source_text"]
        sentences = sentence_split(text)
        # 审计 #7：原来按"≥12 字的句子 ≥2 句"判断，会误伤规范展签体
        # （4 句各 7–9 字、内容完整）。改为按实义总字数兜底：
        # 展签体句子虽短，但总字数够，仍可支撑一段讲解。
        substantive = [s for s in sentences if len(s) >= 4]
        substantive_chars = sum(len(s) for s in substantive)

        marked = [s for s in sentences if any(mark in s for mark in MISSING_MARKERS)]
        if marked:
            missing.append({"exhibit_id": exhibit_id, "missing": "资料显式标注缺项：%s" % marked[0][:60]})
        elif substantive_chars < 40:
            # 只做字数下限兜底。不按"信息条数"卡——规范展签常是 2 句长句，
            # 按条数卡会误伤正常资料。显式缺料由 MISSING_MARKERS 捕获。
            missing.append(
                {
                    "exhibit_id": exhibit_id,
                    "missing": "资料实义内容仅 %d 字，不足以支撑一段 30–60 秒讲解，需客户补充"
                    % substantive_chars,
                }
            )

        # 显式冲突标记
        explicit = [s for s in sentences if any(mark in s for mark in CONFLICT_MARKERS)]
        if explicit:
            conflicts.append(
                {
                    "exhibit_id": exhibit_id,
                    "description": "资料含冲突表述：%s" % explicit[0][:60],
                    "citations": [{"source_name": item["source_name"], "source_quote": explicit[0][:120]}],
                }
            )
            continue

        # 隐式冲突：只有"同一对象被给出两个不同数值"才算冲突。
        # 一份长资料里出现多个年份是常态（1911 年被盗、1956 年被破坏），
        # 不能因为都含"据/记载"就判为矛盾——那会把正常长文全部拦下。
        # 判据收紧为：两句讲的是同一件事（公共子串足够长）但数值不同。
        found = False
        for i, first in enumerate(substantive):
            for second in substantive[i + 1 :]:
                if lcs_len(first, second) < 12:
                    continue
                a = set(YEAR_OR_NUM.findall(first)) - {"", None}
                b = set(YEAR_OR_NUM.findall(second)) - {"", None}
                if a and b and a != b and not (a & b):
                    conflicts.append(
                        {
                            "exhibit_id": exhibit_id,
                            "description": "资料对同一对象给出不同数值：%s / %s，需客户确认哪个版本有效"
                            % ("、".join(sorted(a))[:40], "、".join(sorted(b))[:40]),
                            "citations": [
                                {"source_name": item["source_name"], "source_quote": first[:120]},
                                {"source_name": item["source_name"], "source_quote": second[:120]},
                            ],
                        }
                    )
                    found = True
                    break
            if found:
                break
    return missing, conflicts


def validate_draft(sources, draft, progress=None):
    """progress(step_name, detail) 可选：把每道门的核对结果实时上报给调用方。"""
    def note(name, detail):
        if progress:
            try:
                progress(name, detail)
            except Exception:
                pass
    issues, checks, total = [], 0, 0
    # 程序化检测资料的缺料与冲突，不再依赖模型自报
    detected_missing, detected_conflicts = detect_source_issues(sources)
    if not isinstance(draft, dict):
        return {"passed": False, "checks": 0, "total_checks": 1, "issues": ["草稿必须是对象"]}
    missing = draft.get("missing_materials", [])
    conflicts = draft.get("conflicts", [])
    for item in (missing if isinstance(missing, list) else []) + detected_missing:
        exhibit_id = item.get("exhibit_id") if isinstance(item, dict) else None
        # 缺料是资料本身不够，属于硬阻断：没有事实就无法写讲解，谁也不能批准
        if exhibit_id in EXHIBIT_IDS:
            issues.append("展项 %s 缺料：%s" % (exhibit_id, item.get("missing", "需客户补充")))
    # 来源冲突是"两处说法不一致"，属于需要人确认的警告，不是硬阻断：
    # 人看过原文、确认采用哪一种说法后可以批准，批准会记进事件表。
    warnings = []
    for item in (conflicts if isinstance(conflicts, list) else []) + detected_conflicts:
        if isinstance(item, dict) and item.get("exhibit_id") in EXHIBIT_IDS:
            warnings.append("展项 %s 来源冲突待确认：%s" % (item["exhibit_id"], item.get("description", "需人工确认")))
    missing = missing if isinstance(missing, list) else []
    conflicts = conflicts if isinstance(conflicts, list) else []
    cards = draft.get("cards")
    if not isinstance(cards, list):
        return {"passed": False, "checks": checks, "total_checks": total + 1, "issues": issues + ["内容必须包含 cards 数组"], "detected": {"missing_materials": missing, "conflicts": conflicts}}
    total += 1
    # 覆盖门：每份资料都要有对应的卡，且不许多、不许串号。展项数量由资料决定。
    expected = set(sources)
    got = {c.get("exhibit_id") for c in cards if isinstance(c, dict)}
    if got == expected and len(cards) == len(expected):
        checks += 1
        note("覆盖门", "%s 各一份，数量正确" % " / ".join(sorted(expected)))
    else:
        issues.append("P0覆盖门：应为 %s 各一份内容，实际为 %s"
                      % ("、".join(sorted(expected)) or "无", "、".join(sorted(str(x) for x in got)) or "无"))
        note("覆盖门", "卡片数量或展项编号不对")
    for card in cards:
        eid = card.get("exhibit_id") if isinstance(card, dict) else None
        total += 1
        if eid not in EXHIBIT_IDS:
            issues.append("内容含无效展项编号")
            continue
        required = ("location", "card_title", "narration", "no_target_prompt", "multi_target_prompt", "question", "answer")
        if all(isinstance(card.get(key), str) and card[key].strip() for key in required):
            checks += 1
        else:
            issues.append("展项 %s 缺少必填内容或提示话术" % eid)
        source = sources[eid]["source_text"]
        citations = card.get("citations", [])
        valid_citations = [c for c in citations if isinstance(c, dict) and isinstance(c.get("source_quote"), str) and c["source_quote"].strip() and c.get("source_name") == sources[eid]["source_name"] and c["source_quote"].strip() in source]
        total += 1
        if valid_citations:
            checks += 1
        else:
            issues.append("P0引文门：展项 %s 无法在本展项来源中逐字定位出处" % eid)
        narration = card.get("narration", "")
        facts = card.get("facts", [])
        allowed_text = source + " " + " ".join(c["source_quote"] for c in valid_citations)
        if not isinstance(facts, list) or not facts:
            issues.append("P0出处映射门：展项 %s 缺少逐条事实映射" % eid)
            facts = []
        for fact in facts:
            if not isinstance(fact, dict):
                issues.append("P0出处映射门：展项 %s 存在不能回溯到本项原文的事实" % eid)
                continue
            claim = str(fact.get("claim", "")).strip()
            quote = str(fact.get("source_quote", "")).strip()
            # claim 是"这条事实在讲解里怎么说的"，模型会做口语化改写，
            # 因此不要求 claim 逐字出现在 narration 里，而要求两者语义相邻：
            # claim 与 narration 有足够长的公共片段，且 claim 能与原文
            # source_quote 对齐（说明它确实是原文的忠实转述，不是另编的）。
            if (not claim or not quote
                    or quote not in source
                    or fact.get("source_name") != sources[eid]["source_name"]):
                issues.append("P0出处映射门：展项 %s 存在不能回溯到本项原文的事实" % eid)
                continue
            # claim 必须与原文有实质重合：否则就是"随便写个 claim 挂个真引文"
            if lcs_len(claim, quote) < 6 and claim not in source:
                issues.append(
                    "P0出处映射门：展项 %s 的事实「%s」与所引原文不符" % (eid, claim[:30])
                )
                continue
            # claim 必须能在讲解里找到对应表述。模型会做口语化改写
            # （"本展项展示的织物残片为汉代丝织品" → "这件展品是一片汉代丝织品残片"），
            # 逐字匹配和长公共片段都会误伤，因此改用"字符重合率"判定同一事实。
            if claim not in narration and not same_fact(claim, narration):
                issues.append(
                    "P0出处映射门：展项 %s 的事实「%s」在讲解中找不到对应表述" % (eid, claim[:30])
                )
        # 反向覆盖门（审计 #1）：只查"事实能否回溯"不够，补一句伪造成本为零。
        # 要求讲解里每个实义句都命中某条 claim / 引用，或显式标注待确认。
        claims = [f.get("claim", "").strip() for f in facts if isinstance(f, dict) and f.get("claim")]
        uncovered = coverage_gaps(narration, claims + [c["source_quote"].strip() for c in valid_citations])
        total += 1
        if not uncovered:
            checks += 1
        else:
            issues.append("P0覆盖门：展项 %s 有 %d 句没有事实映射支撑：%s" % (eid, len(uncovered), " / ".join(uncovered)))
        numbers = re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?", narration)
        unsupported_numbers = [number for number in numbers if number not in allowed_text]
        # 中文数字门：讲解里的中文数字（年份、"三十厘米"）必须能在原文或引用中找到原串
        cn_in_narration = cn_numerals(narration)
        cn_in_source = cn_numerals(allowed_text)
        unsupported_cn = sorted(n for n in cn_in_narration if n not in cn_in_source)
        total += 1
        if not unsupported_numbers and not unsupported_cn:
            checks += 1
        else:
            parts = []
            if unsupported_numbers:
                parts.append("阿拉伯数字：" + "、".join(unsupported_numbers))
            if unsupported_cn:
                parts.append("中文数字：" + "、".join(unsupported_cn))
            issues.append("P0数字门：展项 %s 讲解包含原文未支持的数字（%s）" % (eid, "；".join(parts)))
        named_entities = set(re.findall(r"(?<![A-Za-z])[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*", narration))
        named_entities.update(re.findall(r"[《“\"]([^》”\"]{2,30})[》”\"]", narration))
        # 中文专名门：识别"市机械厂""郑州机床厂""饕餮纹"这类机构/专名，
        # 覆盖 ASCII 正则看不见的中文实体（审计 #1：伪造中文专名可绕过实体门）
        named_entities.update(cn_proper_nouns(narration))
        # DEMO/AI 等是流程标记，不是事实实体，不参与实体门
        named_entities -= {"DEMO", "AI", "TTS", "JSON"}
        unsupported_entities = [entity for entity in named_entities if entity not in allowed_text]
        total += 1
        if not unsupported_entities:
            checks += 1
        else:
            issues.append("P0实体门：展项 %s 讲解包含出处未支持实体：%s" % (eid, "、".join(sorted(unsupported_entities))))
        if len(narration) < 120 or len(narration) > 240:
            issues.append("展项 %s 讲解需为约 120–240 字，当前 %d 字" % (eid, len(narration)))
    return {"passed": not issues, "checks": checks, "total_checks": total,
            "issues": issues, "warnings": warnings}


def compute_economics(payload):
    """项目经济模型：报价 − 实测直接成本 = 项目贡献。

    商业审计修正（2026-11-14）：
    1. contribution/quote 不是毛利率，是变动贡献率。字段改名为 contribution_ratio，
       并显式标注它不含获客、税费、折旧、管理摊销。
    2. 报价未签约前不输出任何利润率——避免用假设价算出"毛利率 XX%"。
    3. 给出两个保本价：cash_breakeven（只算现金支出：模型+语音+其他）与
       full_breakeven（含团队人时）。两者可能差一个数量级，只给一个会答错。
    4. efficiency 必须两端口径一致（scope_mismatch 时拒绝计算），并记录 n/操作者/资料。
    """
    def num(key):
        value = payload.get(key)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    quote = num("quote")
    quote_basis = str(payload.get("quote_basis") or "assumed").strip()
    if quote_basis not in ("assumed", "interviewed", "signed"):
        quote_basis = "assumed"
    hours_source = str(payload.get("hours_source") or "manual").strip()
    hours = num("hours")
    rate = num("hourly_rate")
    model_cost = num("model_cost")
    voice_cost = num("voice_cost")
    other_cost = num("other_cost")
    customer_alt_cost = num("customer_alt_cost")
    baseline = num("baseline_minutes")
    baseline_scope = str(payload.get("baseline_scope") or "").strip()
    employee_minutes = num("employee_minutes")
    employee_scope = str(payload.get("employee_scope") or "").strip()
    sample_n = num("sample_n")

    missing = [
        label
        for key, label in (
            (quote, "试点报价"),
            (hours, "实测人工小时"),
            (rate, "内部时薪"),
            (model_cost, "模型调用费"),
            (voice_cost, "语音成本"),
            (other_cost, "其他直接成本"),
        )
        if key is None
    ]

    cash_parts = {"模型": model_cost, "语音": voice_cost, "其他": other_cost}
    cash_cost = None
    if all(v is not None for v in cash_parts.values()):
        cash_cost = round(sum(cash_parts.values()), 2)

    labor = round(hours * rate, 2) if hours is not None and rate is not None else None
    full_cost = round(cash_cost + labor, 2) if cash_cost is not None and labor is not None else None

    contribution = round(quote - full_cost, 2) if quote is not None and full_cost is not None else None

    # 报价未签约前不出利润率
    ratio = None
    ratio_blocked = None
    if quote_basis != "signed":
        ratio_blocked = "报价状态为 %s，尚未签约，不输出利润率。签约后才有分母意义。" % quote_basis
    elif contribution is not None and quote:
        ratio = round(contribution / quote * 100, 1)

    result = {
        "inputs": {
            "quote": quote,
            "quote_basis": quote_basis,
            "hours": hours,
            "hours_source": hours_source,
            "hourly_rate": rate,
            "model_cost": model_cost,
            "voice_cost": voice_cost,
            "other_cost": other_cost,
            "customer_alt_cost": customer_alt_cost,
            "baseline_minutes": baseline,
            "baseline_scope": baseline_scope,
            "employee_minutes": employee_minutes,
            "employee_scope": employee_scope,
            "sample_n": sample_n,
        },
        "cost_parts": {"人工": labor, "模型": model_cost, "语音": voice_cost, "其他": other_cost},
        "cash_cost": cash_cost,
        "direct_cost": full_cost,
        # 两个保本价：只算现金支出 vs 含人时全成本
        "cash_breakeven": cash_cost,
        "full_breakeven": full_cost,
        "contribution": contribution,
        "contribution_ratio": ratio,
        "contribution_ratio_blocked_reason": ratio_blocked,
        "missing_inputs": missing,
        "caveat": "贡献率未计获客、税费、设备折旧与管理摊销，不等于毛利率。人时为手工填报，系统未从日志汇总。",
    }

    if customer_alt_cost is not None:
        result["customer_value"] = {
            "customer_alt_cost": customer_alt_cost,
            "customer_saving": round(customer_alt_cost - quote, 2) if quote is not None else None,
            "note": "客户现状成本（自写+配音/内容公司）需访谈取得，用于回答'为什么值这个价'。",
        }
    else:
        result["customer_value"] = None

    # 效率对照：两端口径必须一致，否则拒绝计算
    if baseline and employee_minutes:
        if baseline_scope and employee_scope and baseline_scope != employee_scope:
            result["efficiency"] = {
                "status": "scope_mismatch",
                "baseline_scope": baseline_scope,
                "employee_scope": employee_scope,
                "note": "两侧统计范围不一致，不能相减。请用同一步骤集合重测。",
            }
        else:
            result["efficiency"] = {
                "status": "ok",
                "baseline_minutes": baseline,
                "employee_minutes": employee_minutes,
                "saved_minutes": round(baseline - employee_minutes, 1),
                "sample_n": sample_n,
                "scope": baseline_scope or employee_scope or "未声明",
                "note": "同一资料、同一质量与审核要求下的实测对照；样本量 %s，不构成稳定产能结论。"
                        % (int(sample_n) if sample_n else "未填"),
            }
    else:
        result["efficiency"] = None

    result["complete"] = not missing and contribution is not None
    return result


def diff_drafts_semantic(old, new):
    """按展项与字段做结构化 diff，并给出需要重测的用例。"""
    changes, affected = [], set()
    old_cards = {str(c.get("exhibit_id", i)): c for i, c in enumerate(old.get("cards", []), 1) if isinstance(c, dict)}
    new_cards = {str(c.get("exhibit_id", i)): c for i, c in enumerate(new.get("cards", []), 1) if isinstance(c, dict)}
    for code in sorted(set(old_cards) | set(new_cards)):
        before, after = old_cards.get(code, {}), new_cards.get(code, {})
        for field in ("location", "card_title", "narration", "no_target_prompt", "multi_target_prompt", "question", "answer"):
            a, b = str(before.get(field, "")), str(after.get(field, ""))
            if a != b:
                affected.add(code)
                changes.append({"exhibit_id": code, "field": field, "before": a, "after": b})
        if before.get("citations") != after.get("citations"):
            affected.add(code)
            changes.append({"exhibit_id": code, "field": "citations", "before": "原引用", "after": "新引用"})
        if before.get("facts") != after.get("facts"):
            affected.add(code)
            changes.append({"exhibit_id": code, "field": "facts", "before": "原事实映射", "after": "新事实映射"})
    retest = []
    if affected:
        retest.extend(["T1", "T6"])
    if any(c["field"] in ("narration", "answer") for c in changes):
        retest.append("T8")
    if any(c["field"] == "citations" for c in changes):
        retest.append("T5")
    return {
        "changed": bool(changes),
        "changes": changes,
        "affected_exhibits": sorted(affected),
        "unaffected_exhibits": sorted(set(old_cards) - affected),
        "retest_cases": sorted(set(retest)),
    }


def package_name(row):
    safe = re.sub(r"[^\w一-鿿-]+", "_", str(row["title"]))[:40]
    return "%s_v%s_%s" % (safe, row["version"], datetime.now().strftime("%Y%m%d"))


def build_package(row, draft, validation, run_id):
    """按 7 个文件生成真实交付内容，全部来自已批准版本。"""
    cards = draft.get("cards", []) or []
    sources = json.loads(row["sources"] or "{}")
    with db() as connection:
        # 只取本导出版本的测试记录。旧版本的记录不能混进来，否则客户会把
        # v1 的验证结果当成本版（v3）的验证结果——这是交付物可信度的根本问题。
        all_tests = connection.execute(
            "SELECT number,status,expected,actual,created_at,version,mode FROM test_records WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
        tests = [t for t in all_tests if int(t["version"]) == int(row["version"])]
        stale_tests = [t for t in all_tests if int(t["version"]) != int(row["version"])]
        versions = connection.execute(
            "SELECT version,created_at,actor,diff FROM versions WHERE run_id=? ORDER BY version", (run_id,)
        ).fetchall()

    item_rows = ["| 展项 | 资料名称 | 资料字数 | 状态 |", "|---|---|---|---|"]
    for code in sorted(sources):
        item = sources[code]
        item_rows.append("| %s | %s | %d | 已用于生成本版内容 |" % (code, item.get("source_name", ""), len(item.get("source_text", ""))))

    card_blocks = []
    for card in cards:
        code = card.get("exhibit_id", "")
        block = ["## 展项 %s · %s" % (code, card.get("card_title", "")), ""]
        block.append("- 位置：%s" % card.get("location", ""))
        block.append("- 讲解（%d 字）：" % len(card.get("narration", "")))
        block.append("")
        block.append("> " + str(card.get("narration", "")).replace("\n", "\n> "))
        block.append("")
        block.append("- 无目标提示：%s" % card.get("no_target_prompt", ""))
        block.append("- 多目标提示：%s" % card.get("multi_target_prompt", ""))
        block.append("- 观众提问：%s" % card.get("question", ""))
        block.append("- 参考答案：%s" % card.get("answer", ""))
        block.append("")
        block.append("**引用出处**")
        for cit in card.get("citations", []):
            block.append("- 「%s」（%s）" % (cit.get("source_quote", ""), cit.get("source_name", "")))
        facts = card.get("facts") or []
        if facts:
            block.append("")
            block.append("**事实映射**")
            for fact in facts:
                block.append("- %s → 原文「%s」" % (fact.get("claim", ""), fact.get("source_quote", "")))
        card_blocks.append("\n".join(block))

    test_rows = ["| 用例 | 状态 | 版本 | 模式 | 时间 |", "|---|---|---|---|---|"]
    for test in tests:
        test_rows.append(
            "| %s | %s | v%s | %s | %s |"
            % (test["number"], {"passed": "通过", "failed": "失败", "not_run": "未运行"}.get(test["status"], test["status"]),
               test["version"], test["mode"], test["created_at"])
        )
    ran = [t["number"] for t in tests]
    not_run = [n for n in ("T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9") if n not in ran]

    # 旧版本跑过的用例，本版没有重测：必须显式列出，不能让人误以为本版已验证
    stale_rows = []
    for test in stale_tests:
        stale_rows.append(
            "- %s 在 v%s 记录为「%s」（%s），本版 v%s 未重测"
            % (test["number"], test["version"],
               {"passed": "通过", "failed": "失败", "not_run": "未运行"}.get(test["status"], test["status"]),
               test["mode"], row["version"])
        )

    version_rows = ["| 版本 | 时间 | 操作者 | 变更 |", "|---|---|---|---|"]
    diff_blocks = []
    for version in versions:
        changes = json.loads(version["diff"] or "[]")
        lines = ["### v%s（%s，%s）" % (version["version"], version["created_at"], version["actor"])]
        if isinstance(changes, list) and changes:
            # 两种格式都要兼容：revise 存的是 difflib.unified_diff 的字符串行；
            # 早期版本可能存结构化 dict（含 exhibit_id/field/before/after）。
            if all(isinstance(c, str) for c in changes):
                summary = "统一差异 %d 行" % len([c for c in changes if c.strip()])
                lines.append("")
                lines.append("```diff")
                lines.extend(changes[:400])
                lines.append("```")
            else:
                summary = "%d 处结构化修改" % len(changes)
                for change in changes:
                    if not isinstance(change, dict):
                        continue
                    lines.append("")
                    lines.append("- 展项 **%s** · 字段 `%s`" % (change.get("exhibit_id", "?"), change.get("field", "?")))
                    if "before" in change:
                        lines.append("  - 原：%s" % str(change.get("before", ""))[:400])
                        lines.append("  - 现：%s" % str(change.get("after", ""))[:400])
        else:
            summary = "首次生成"
            lines.append("")
            lines.append("首次生成，无历史差异。")
        diff_blocks.append("\n".join(lines))
        version_rows.append("| v%s | %s | %s | %s |" % (version["version"], version["created_at"], version["actor"], summary))

    gate_rows = ["- 质量门：%s（%s / %s 项）" % ("通过" if validation.get("passed") else "未通过", validation.get("checks"), validation.get("total_checks"))]
    for issue in validation.get("issues", []):
        gate_rows.append("- 阻断项：%s" % issue)

    # 验收单：逐条结构化，带金额/签收位，可作收款触发物
    accept_rows = [
        "| # | 验收项 | 判据 | 状态 |",
        "|---|---|---|---|",
        "| 1 | 内容与来源逐条对应 | 每条事实都能回到本展项授权资料 | %s |" % ("通过" if validation.get("passed") else "未通过"),
        "| 2 | 客户确认关键事实 | 策展/教育负责人逐条签署 | ☐ 待签 |",
        "| 3 | 指定场景测试有记录 | 见 05，未运行为未运行 | %s |" % ("有记录" if tests else "无记录"),
        "| 4 | 素材与版本清单完整 | 见 01 与 06 | 是 |",
        "| 5 | 未解决问题已列明 | 见 06 待解决问题 | 是 |",
    ]

    # 签收区块：若已有登记记录则填入真实签收信息，否则保留待填栏位。
    # 这样导出的验收单与数据库一致，不会出现"已签收但导出仍是空白栏"的矛盾。
    with db() as connection:
        signed_rows = connection.execute(
            "SELECT signed_by,signed_at,amount,quote_id,note FROM acceptances WHERE run_id=? ORDER BY id DESC", (run_id,)
        ).fetchall()
        latest_quote = connection.execute(
            "SELECT amount,basis FROM quotes WHERE run_id=? ORDER BY id DESC LIMIT 1", (run_id,)
        ).fetchone()
    if signed_rows:
        sig = signed_rows[0]
        quote_basis = "已签约" if latest_quote and latest_quote["basis"] == "signed" else "见报价记录"
        acceptance_block = (
            "| 项目 | 内容 |\n|---|---|\n"
            "| 验收金额 | %s CNY（%s） |\n"
            "| 付款节点 | 见合同约定 |\n"
            "| 客户签收人 | %s |\n"
            "| 签收日期 | %s |\n"
            "| 我方交付人 | 待填写 |\n"
            "| 签收记录数 | %d |\n\n"
            "> 本单已有签收登记，以数据库记录为准。\n"
            % (
                sig["amount"] if sig["amount"] is not None else "待填写",
                quote_basis, sig["signed_by"] or "待填写",
                sig["signed_at"] or "待填写", len(signed_rows),
            )
        )
    else:
        quote_note = "已签约" if latest_quote and latest_quote["basis"] == "signed" else "待访谈确认"
        amount_hint = latest_quote["amount"] if latest_quote and latest_quote["amount"] is not None else "__________"
        acceptance_block = (
            "| 项目 | 内容 |\n|---|---|\n"
            "| 验收金额 | %s CNY（报价状态：%s） |\n"
            "| 付款节点 | 签收后 ____ 日内支付 |\n"
            "| 客户签收人 | __________ |\n"
            "| 签收日期 | __________ |\n"
            "| 我方交付人 | __________ |\n\n"
            "> 尚未登记签收。客户签署后通过 /api/acceptances 登记，导出本单将自动填入。\n"
            % (amount_hint, quote_note)
        )

    return {
        "01_需求与资料清单.md": "# 需求与资料清单\n\n- 项目：%s\n- 任务编号：#%s\n- 版本：v%s\n- 生成模式：%s\n- 审核状态：%s\n- 导出时间：%s\n\n## 资料\n\n%s\n" % (
            row["title"], run_id, row["version"], row["mode"], row["status"], now(), "\n".join(item_rows)),
        "02_展项知识卡与出处.md": "# 展项知识卡与出处\n\n> 每条事实均须可回溯到本展项授权资料。\n\n" + "\n\n".join(card_blocks) + "\n",
        "03_讲解及过渡文案.md": "# 讲解及过渡文案\n\n" + "\n\n".join(
            "## 展项 %s · %s\n\n%s\n\n**过渡话术**\n\n- 无目标：%s\n- 多目标：%s\n" % (
                c.get("exhibit_id"), c.get("card_title"), c.get("narration", ""),
                c.get("no_target_prompt", ""), c.get("multi_target_prompt", "")) for c in cards) + "\n",
        "04_音频/README.md": "# 音频说明\n\n> ⚠ 本包不完整：不含任何音频文件。\n\n"
            "本岗位名为“语音体验交付员”，但系统当前**不产出音频**。客户签收前必须明确：录音与下发由谁完成、何时完成。\n\n"
            "若客户接受以文字稿+人工录音方式降级交付，需在 07 验收单中书面注明 `accept_degraded=true` 并签署。\n\n"
            "## 录音需求清单\n\n"
            + "\n".join("- 展项 %s：%d 字，约 %d 秒（来源标注：待录 / TTS / 人工）"
                        % (c.get("exhibit_id"), len(c.get("narration", "")), round(len(c.get("narration", "")) / 4)) for c in cards) + "\n",
        "05_场景测试记录.md": "# 场景测试记录\n\n"
            + ("以下为本次运行实际执行过的用例记录。\n\n" + "\n".join(test_rows) + "\n\n" if tests else "本次运行没有任何测试记录。\n\n")
            + "未运行用例：%s\n\n" % ("、".join(not_run) or "无")
            + (("## 旧版本记录（本版未重测）\n\n" + "\n".join(stale_rows) + "\n\n"
                "> 以上为本版之前的测试记录，**不能作为本版 v%s 的验收依据**。\n\n" % row["version"]) if stale_rows else "")
            + "> 未运行不代表通过。客户验收时应要求补齐或书面接受未覆盖项。\n",
        "06_修改差异与待解决问题.md": "# 修改差异与待解决问题\n\n## 版本历史\n\n%s\n\n## 变更明细\n\n%s\n\n## 待解决问题\n\n%s\n"
            % (
                "\n".join(version_rows),
                "\n\n".join(diff_blocks) if diff_blocks else "无版本记录。",
                "\n".join(
                    [
                        "- 本包不含眼镜端实机验证，设备上线需另行验收。",
                        "- 客户需自行确认展项资料授权范围与期限。",
                        "- 本包不含音频文件，录音与下发需客户或合作方完成。",
                        "- 未开展客户访谈，价格与需求均为待验证假设。" if not latest_quote else
                        "- 报价状态：%s；%s" % (latest_quote["basis"], "已签约" if latest_quote["basis"] == "signed" else "尚未签约，价格仍属假设"),
                        "- 质量门通过仅代表内部程序校验，不代表客户事实审定。",
                    ]
                ),
            ),
        "07_客户审核与验收单.md": "# 客户审核与验收单\n\n"
            "- 项目：%s\n- 版本：v%s\n- 模式：%s\n- 导出时间：%s\n\n"
            "## 质量门记录\n\n%s\n\n"
            "## 验收项\n\n%s\n\n"
            "## 签收\n\n%s\n\n"
            "> 签收本内容包**不等于**硬件上线验收。设备联调、录音制作与现场下发不在本包范围内。\n"
            % (
                row["title"], row["version"], row["mode"], now(),
                "\n".join(gate_rows), "\n".join(accept_rows), acceptance_block,
            ),
    }


def snapshot(draft, validation, version, actor="system"):
    return (version, now(), json_text(draft), json_text(validation), "", actor)


# ==================== 纯文本资料 → A/B/C 展项 ====================

# 只把全角字母和数字转半角，保留全角标点——中文逗号、句号不能被吞成 ASCII。
FULLWIDTH_MAP = {code: code - 0xFEE0 for code in
                 list(range(0xFF10, 0xFF1A)) + list(range(0xFF21, 0xFF3B)) + list(range(0xFF41, 0xFF5B))}


def halfwidth(text):
    return str(text or "").translate(FULLWIDTH_MAP)


EXHIBIT_MARKER = re.compile(r"^\s*(?:#{1,6}\s*)?(?:展项|展品|展位|exhibit)\s*([A-Ca-c])\s*[：:.、\-\)）]?\s*(.*)$", re.I)


def split_materials(raw_text):
    """把客户给的纯文本介绍切成展项。

    规则，按优先级：
    1. 有"展项A：""展品B："这类标记 → 按标记切，1–3 个都接受；
    2. 没有标记 → 整份文本作为**一个**展项，不按空行硬拆。
       （客户粘一整篇文章是常态；按空行取前三段会丢掉绝大部分内容，
        还会把开头的元数据当成展项，这是错的。）
    只有标记格式明显写错时才报错。
    """
    text = halfwidth(raw_text).strip()
    if not text:
        raise ValueError("资料为空，先把客户给的介绍粘贴进来")
    blocks, order, current, buffer = {}, [], None, []
    for line in text.splitlines():
        match = EXHIBIT_MARKER.match(line)
        if match:
            if current is not None and buffer:
                blocks[current] = "\n".join(buffer).strip()
            key = match.group(1).upper()
            if key not in order:
                order.append(key)
            current = key
            buffer = [match.group(2).strip()] if match.group(2).strip() else []
        else:
            buffer.append(line)
    if current is not None and buffer:
        blocks[current] = "\n".join(buffer).strip()

    if not blocks:
        # 没有标记：整份资料就是一个展项
        title = next((line.strip() for line in text.splitlines()
                      if line.strip() and len(line.strip()) <= 40), "客户资料")
        return [{"exhibit_id": "A", "source_name": title[:60], "source_text": text}]

    keys = [key for key in EXHIBIT_IDS if key in blocks]
    if not keys:
        raise ValueError("识别到展项标记但编号不是 A/B/C，请改用“展项A：”“展项B：”的写法")
    exhibits = []
    for key in keys:
        body = blocks[key].strip()
        if not body:
            continue
        first_line = body.splitlines()[0][:40] if body else ""
        exhibits.append({
            "exhibit_id": key,
            "source_name": "展项 %s 资料%s" % (key, "·" + first_line if first_line else ""),
            "source_text": body,
        })
    if not exhibits:
        raise ValueError("展项标记后面没有内容")
    return exhibits


# ==================== 只用原文回答（资料外显式说边界） ====================

QUESTION_STOP = set("的了吗呢吧啊是在和与及或什怎么为哪这那个些一有不我你他她它请问能可以要会还就很也说")


def _content_set(text):
    return {ch for ch in str(text or "") if ch not in QUESTION_STOP and ch not in "，。、；；：？！“”‘’（）《》〈〉 \n\t\r·—…"}


def answer_from_source(sources, exhibit_id, question):
    """程序检索：从该展项原文里找最相关的句子作答。

    命中率不够就明确回答“资料里没有”，不调用模型猜测，也不跨展项借内容。
    """
    exhibit_id = str(exhibit_id or "").strip().upper()
    item = sources.get(exhibit_id)
    if not item:
        return {"in_source": False, "exhibit_id": exhibit_id, "answer": "这个展项编号不存在，只能回答 A、B、C 三个展项。", "evidence": []}
    asked = _content_set(question)
    if not asked:
        return {"in_source": False, "exhibit_id": exhibit_id, "answer": "问题太短，没看出你想问哪件事，换个说法再问一次。", "evidence": []}
    sentences = [s for s in sentence_split(item["source_text"]) if len(s) >= 4]
    scored = []
    for sentence in sentences:
        overlap = len(asked & _content_set(sentence))
        if overlap:
            scored.append((overlap / len(asked), sentence))
    scored.sort(key=lambda pair: -pair[0])
    best = scored[0][0] if scored else 0.0
    if best < 0.34:
        return {
            "in_source": False,
            "exhibit_id": exhibit_id,
            "answer": "资料里没有写到这个问题。这一段展项资料只涉及：%s。其余的我不补猜，需要客户补充资料或请策展人确认。"
                      % ("；".join(s[:24] for s in sentences[:3]) or "暂无可用内容"),
            "evidence": [],
            "matched": round(best, 2),
        }
    evidence = [sentence for score, sentence in scored[:3] if score >= best * 0.6]
    return {
        "in_source": True,
        "exhibit_id": exhibit_id,
        "answer": "".join(evidence[:2]),
        "evidence": [{"source_name": item["source_name"], "source_quote": sentence} for sentence in evidence],
        "matched": round(best, 2),
    }


# ==================== 四类测试用例 ====================

OUT_OF_SOURCE_TEMPLATES = (
    "这个展项是哪一年被发现的？",
    "它现在值多少钱？",
    "它是由谁设计的？",
)


def build_test_cases(sources, draft):
    """按展项生成四类测试用例：资料内、资料外、歧义、连续追问。

    全部取材于原文与卡片字段，答案与期望判定都由程序写死，不让模型自评。
    """
    cards = {card.get("exhibit_id"): card for card in (draft or {}).get("cards", []) if isinstance(card, dict)}
    cases = []
    ids = [key for key in EXHIBIT_IDS if key in sources]
    for exhibit_id in ids:
        item = sources.get(exhibit_id) or {}
        card = cards.get(exhibit_id) or {}
        text = item.get("source_text", "")
        sentences = [s for s in sentence_split(text) if len(s) >= 6]
        if not sentences:
            continue
        # 1 资料内：拿卡片里的问句问一次，要求答出原文内容
        question = (card.get("question") or "").strip() or ("%s讲了什么？" % ("展项 " + exhibit_id))
        answer_probe = answer_from_source(sources, exhibit_id, question)
        cases.append({
            "case_id": "IN-%s" % exhibit_id,
            "type": "资料内",
            "exhibit_id": exhibit_id,
            "turns": [question],
            "expected": "应回答，且内容能在原文中找到出处",
            "pass_criteria": "回答与原文有可核对的重合，且引用本展项资料",
            "evidence": answer_probe.get("evidence", []),
            "program_check": {"in_source": answer_probe.get("in_source"), "matched": answer_probe.get("matched")},
        })
        # 2 资料外：问原文里没有的事实，要求说明边界
        probe = OUT_OF_SOURCE_TEMPLATES[(EXHIBIT_IDS.index(exhibit_id)) % len(OUT_OF_SOURCE_TEMPLATES)]
        out_probe = answer_from_source(sources, exhibit_id, probe)
        cases.append({
            "case_id": "OUT-%s" % exhibit_id,
            "type": "资料外",
            "exhibit_id": exhibit_id,
            "turns": [probe],
            "expected": "应说明资料里没有，不得编造",
            "pass_criteria": "回答含“资料里没有/需补充/待确认”，且未给出具体新事实",
            "evidence": [],
            "program_check": {"in_source": out_probe.get("in_source"), "matched": out_probe.get("matched")},
        })
        # 3 歧义：同时看到多个展项，要求只提示选择，不自动播
        cases.append({
            "case_id": "AMB-%s" % exhibit_id,
            "type": "歧义问题",
            "exhibit_id": exhibit_id,
            "turns": ["观众同时站在 %s 和 %s 前，没有明确指向" % (exhibit_id, EXHIBIT_IDS[(EXHIBIT_IDS.index(exhibit_id) + 1) % 3])],
            "expected": card.get("multi_target_prompt") or "提示观众选择要听的展项，不自动播放",
            "pass_criteria": "输出为选择提示，未开始播放任一条讲解",
            "evidence": [],
            "program_check": {},
        })
        # 4 连续追问：顺着上一轮答案再追问一句原文能答的事
        follow = sentences[1] if len(sentences) > 1 else sentences[0]
        follow_question = "那%s呢？" % follow[:14]
        follow_probe = answer_from_source(sources, exhibit_id, follow_question)
        cases.append({
            "case_id": "SEQ-%s" % exhibit_id,
            "type": "连续追问",
            "exhibit_id": exhibit_id,
            "turns": [question, follow_question],
            "expected": "第二问应承接上一轮，仍只答原文本展项内容",
            "pass_criteria": "第二轮回答有本展项出处，且未串到其他展项",
            "evidence": follow_probe.get("evidence", []),
            "program_check": {"in_source": follow_probe.get("in_source"), "matched": follow_probe.get("matched")},
        })
    return {"cases": cases, "total": len(cases), "source": "程序按原文与卡片生成，未经模型评判"}


# ==================== Breeze Blue 语音合成 ====================

def breeze_ready():
    return bool(BREEZE_KEY)


def breeze_call(path, payload=None, method="POST", timeout=90):
    if not BREEZE_KEY:
        raise RuntimeError("未配置 BREEZE_API_KEY：在 .env.local 里设置后重启服务，或先在本机环境变量里导出")
    url = BREEZE_BASE + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "xi-api-key": BREEZE_KEY,
        "Content-Type": "application/json",
    })
    return urllib.request.urlopen(request, timeout=timeout)


def breeze_voices():
    with breeze_call("/v1/voices?language_code=zh&voice_type=default&page_size=20", method="GET", timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    voices = []
    for voice in payload.get("voices", []):
        voices.append({
            "voice_id": voice.get("voice_id"),
            "name": voice.get("name"),
            "gender": voice.get("gender"),
            "age": voice.get("age"),
            "tone": voice.get("tone"),
            "language_code": voice.get("language_code"),
        })
    return voices


def breeze_synthesize(text, instructions="", voice_id="", speed=None):
    """合成一段讲解语音，落盘为 mp3，返回可播放地址。"""
    import hashlib
    text = str(text or "").strip()
    if not text:
        raise ValueError("要合成的文本为空")
    if len(text) > 1000:
        raise ValueError("单次最多 1000 字，当前 %d 字；请先拆分讲解" % len(text))
    voice = voice_id or BREEZE_VOICE
    if not voice:
        voices = breeze_voices()
        if not voices:
            raise RuntimeError("账号下没有可用音色，请先在 Breeze 后台保存一个中文音色")
        voice = voices[0]["voice_id"]
    payload = {"text": text, "language_code": "zh"}
    if instructions.strip():
        payload["instructions"] = instructions.strip()
        payload["voice_settings"] = {"guidance_scale": 4.0}
    if speed:
        payload.setdefault("voice_settings", {})["speed"] = float(speed)
    if BREEZE_MODEL:
        payload["model_id"] = BREEZE_MODEL
    started = time.monotonic()
    try:
        with breeze_call("/v1/text-to-speech/%s?output_format=mp3_24000_128" % voice, payload) as response:
            audio = response.read()
            history_id = response.headers.get("history-item-id", "")
    finally:
        with db() as connection:
            connection.execute(
                "INSERT INTO api_calls(run_id,created_at,mode,endpoint,model,outcome,http_status,elapsed_ms,error,prompt_tokens,completion_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (None, now(), "live", BREEZE_BASE + "/v1/text-to-speech", "breeze-tts-2", "success", 200,
                 int((time.monotonic() - started) * 1000), "", None, None),
            )
    digest = hashlib.sha256((text + instructions + voice).encode("utf-8")).hexdigest()[:16]
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    target = AUDIO_DIR / (digest + ".mp3")
    target.write_bytes(audio)
    return {"file": target.name, "url": "/api/audio/" + target.name, "bytes": len(audio), "voice_id": voice, "history_id": history_id}



class Handler(BaseHTTPRequestHandler):
    server_version = "ExhibitEmployee/" + APP_VERSION

    def log_message(self, fmt, *args):
        print("%s %s" % (self.log_date_time_string(), fmt % args), flush=True)

    def send_json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def read_json(self):
        # 审计 #9：原来只拦 >1MB，Content-Length: -1 会让 read(-1) 读到 EOF 挂起连接
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            raise ValueError("Content-Length 无效")
        if length < 0:
            raise ValueError("Content-Length 无效")
        if length > 1_000_000:
            raise ValueError("请求超过 1 MB")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ValueError("请求体不完整")
        return json.loads(raw or b"{}")

    def authorized(self) -> bool:
        """校验访问口令。未设置 ACCESS_TOKEN 时（仅本机演示）放行。"""
        if not ACCESS_TOKEN:
            return True
        supplied = self.headers.get("X-Access-Token", "")
        if not supplied:
            supplied = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
        return supplied == ACCESS_TOKEN

    def do_GET(self):
        path = urlparse(self.path).path
        # 静态页放行（页面本身不含数据）；数据接口需口令
        if path.startswith("/api/") and not self.authorized():
            return self.send_json(401, {"error": "需要访问口令"})
        if path in ("/", "/index.html", "/console"):
            page_name = "console.html" if path == "/console" else "index.html"
            try:
                page = (ROOT / page_name).read_bytes()
            except OSError as error:
                return self.send_json(500, {"error": "%s 读取失败：%s" % (page_name, error)})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(page)
        audio_match = re.fullmatch(r"/api/audio/([A-Za-z0-9_-]+\.mp3)", path)
        if audio_match:
            target = AUDIO_DIR / audio_match.group(1)
            if not target.is_file():
                return self.send_json(404, {"error": "音频不存在"})
            raw = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(raw)
        if path == "/api/health":
            return self.send_json(200, {"ok": True, "mode": "demo" if DEMO_MODE else "live", "demo_is_delivery_evidence": False, "model_configured": bool(MODEL), "api_key_configured": bool(API_KEY), "soul_configured": SOUL_PATH.is_file(), "tts_configured": breeze_ready(), "version": APP_VERSION})
        if path == "/api/runs":
            with db() as connection:
                rows = connection.execute("SELECT id,created_at,title,status,mode,version,validation,error FROM runs ORDER BY id DESC LIMIT 50").fetchall()
            return self.send_json(200, {"runs": [dict(r) for r in rows]})
        job_match = re.fullmatch(r"/api/jobs/(\d+)", path)
        if job_match:
            run_id = int(job_match.group(1))
            with db() as connection:
                row = connection.execute(
                    "SELECT id,title,status,mode,version,draft,validation,error FROM runs WHERE id=?", (run_id,)
                ).fetchone()
                if not row:
                    return self.send_json(404, {"error": "找不到该任务"})
                events = connection.execute(
                    "SELECT created_at,event,detail FROM events WHERE run_id=? AND event IN "
                    "('job_step','generation_completed','generation_failed','blocked_before_generation') ORDER BY id",
                    (run_id,)
                ).fetchall()
            steps = []
            for item in events:
                detail = json.loads(item["detail"] or "{}")
                if item["event"] == "job_step":
                    steps.append({
                        "step": detail.get("step"), "label": detail.get("label"),
                        "detail": detail.get("detail"), "state": detail.get("state", "running"),
                        "at": item["created_at"],
                    })
                elif item["event"] == "generation_completed":
                    steps.append({"step": "done", "label": "完成", "detail": {}, "state": "done", "at": item["created_at"]})
                elif item["event"] == "generation_failed":
                    steps.append({"step": "failed", "label": "生成失败", "detail": detail, "state": "failed", "at": item["created_at"]})
                elif item["event"] == "blocked_before_generation":
                    steps.append({"step": "blocked", "label": "资料不足，已拦下", "detail": detail, "state": "failed", "at": item["created_at"]})
            finished = row["status"] not in ("processing",)
            return self.send_json(200, {
                "id": row["id"], "title": row["title"], "status": row["status"], "mode": row["mode"],
                "version": row["version"], "steps": steps, "finished": finished,
                "draft": json.loads(row["draft"]) if finished else None,
                "validation": json.loads(row["validation"] or "{}"),
                "error": row["error"],
            })
        match = re.fullmatch(r"/api/runs/(\d+)/(versions|events|tests|export)", path)
        if match:
            run_id, action = int(match.group(1)), match.group(2)
            with db() as connection:
                row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
                if not row:
                    return self.send_json(404, {"error": "找不到该任务"})
                if action == "versions":
                    rows = connection.execute("SELECT version,created_at,draft,validation,diff,actor FROM versions WHERE run_id=? ORDER BY version", (run_id,)).fetchall()
                    return self.send_json(200, {"versions": [{**dict(v), "draft": json.loads(v["draft"]), "validation": json.loads(v["validation"]), "diff": json.loads(v["diff"])} for v in rows]})
                if action == "events":
                    rows = connection.execute("SELECT created_at,event,detail FROM events WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
                    return self.send_json(200, {"events": [{**dict(e), "detail": json.loads(e["detail"])} for e in rows]})
                if action == "tests":
                    rows = connection.execute("SELECT id,number,test_input,expected,actual,status,created_at,version,mode FROM test_records WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
                    records = []
                    for test in rows:
                        item = dict(test)
                        item["input"] = json.loads(item.pop("test_input"))
                        item["expected"] = json.loads(item["expected"])
                        item["actual"] = json.loads(item["actual"])
                        # 每条记录带上 run_id，便于客户端按记录逐条核对，不必依赖外层字段
                        item["run_id"] = run_id
                        records.append(item)
                    return self.send_json(200, {"run_id": run_id, "tests": records})
                current = json.loads(row["draft"])
                validation = json.loads(row["validation"] or "{}")
                if row["status"] not in ("approved", "approved_demo"):
                    return self.send_json(409, {"error": "未通过人工审核的任务不能导出交付包", "status": row["status"], "validation": validation})
                if not validation.get("passed"):
                    return self.send_json(409, {"error": "P0 质量门未通过，不能导出交付包", "status": row["status"], "validation": validation})
                pieces = build_package(row, current, validation, run_id)
                if row["mode"] == "demo":
                    warn = (
                        "# ⚠ DEMO 演示包 · 不可作为客户交付\n\n"
                        "本包由演示模板生成，未调用模型，不是 AI 交付证据，不得交付客户或作为能力证明。\n"
                        "仅用于验证流程与质量门是否生效。正式交付必须使用 live 模式并重新审核。\n\n---\n\n"
                    )
                    pieces = {name: (warn + body if name.endswith(".md") else body) for name, body in pieces.items()}
                record_event(db(), run_id, "exported", {"version": row["version"], "files": list(pieces), "demo": row["mode"] == "demo"})
                return self.send_json(200, {"package": {"id": run_id, "title": row["title"], "version": row["version"], "mode": row["mode"], "status": row["status"], "files": pieces, "base_name": package_name(row), "is_demo": row["mode"] == "demo"}})
        if path == "/api/ledger":
            # 商业审计 ①：让"0 访谈、0 报价、0 成交"这个事实从接口就能看见，
            # 而不是靠路演时口头解释。数字来自数据库，不是手填。
            with db() as connection:
                customers = connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
                quotes = connection.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
                by_basis = {row["basis"]: row["n"] for row in connection.execute(
                    "SELECT basis, COUNT(*) AS n FROM quotes GROUP BY basis")}
                signed = connection.execute(
                    "SELECT COUNT(*) AS n, COALESCE(SUM(amount),0) AS total FROM acceptances").fetchone()
                revisit = connection.execute(
                    "SELECT COUNT(*) AS n FROM (SELECT customer_id FROM quotes WHERE customer_id IS NOT NULL"
                    " GROUP BY customer_id HAVING COUNT(*) > 1)").fetchone()[0]
            return self.send_json(200, {
                "customers": customers,
                "quotes": quotes,
                "quotes_by_basis": {
                    "assumed": by_basis.get("assumed", 0),
                    "interviewed": by_basis.get("interviewed", 0),
                    "signed": by_basis.get("signed", 0),
                },
                "acceptances": signed["n"],
                "signed_amount_total": signed["total"],
                "repeat_customers": revisit,
                "note": "全部为数据库实际记录。0 表示尚未发生，不代表不存在需求。",
            })
        if path == "/api/customers":
            with db() as connection:
                rows = connection.execute(
                    "SELECT id,created_at,name,contact,budget_owner,note FROM customers ORDER BY id DESC LIMIT 50"
                ).fetchall()
            return self.send_json(200, {"customers": [dict(r) for r in rows]})
        if path == "/api/quotes":
            with db() as connection:
                rows = connection.execute(
                    "SELECT q.id,q.created_at,q.customer_id,c.name AS customer_name,q.run_id,q.amount,"
                    "q.currency,q.basis,q.scope FROM quotes q LEFT JOIN customers c ON c.id=q.customer_id"
                    " ORDER BY q.id DESC LIMIT 50"
                ).fetchall()
            return self.send_json(200, {"quotes": [dict(r) for r in rows]})
        if path == "/api/acceptances":
            with db() as connection:
                rows = connection.execute(
                    "SELECT id,created_at,run_id,quote_id,signed_by,signed_at,amount,note FROM acceptances"
                    " ORDER BY id DESC LIMIT 50"
                ).fetchall()
            return self.send_json(200, {"acceptances": [dict(r) for r in rows]})
        if path == "/api/business":
            with db() as connection:
                row = connection.execute("SELECT updated_at, payload FROM business ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return self.send_json(200, {"saved": None, "computed": compute_economics({}), "description": "尚未录入实测数据；返回空模型，不预填数字"})
            payload = json.loads(row["payload"])
            return self.send_json(200, {"saved": payload, "updated_at": row["updated_at"], "computed": compute_economics(payload)})
        if path == "/api/feedback":
            with db() as connection:
                rows = connection.execute("SELECT id,created_at,run_id,category,note,candidate,version FROM feedback ORDER BY id DESC LIMIT 50").fetchall()
            return self.send_json(200, {"items": [dict(r) for r in rows], "description": "改进候选台账；不代表模型自我改进"})
        return self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self.authorized():
            return self.send_json(401, {"error": "需要访问口令"})
        try:
            data = self.read_json()
            path = urlparse(self.path).path
            test_match = re.fullmatch(r"/api/runs/(\d+)/tests", path)
            if test_match:
                run_id = int(test_match.group(1))
                number = str(data.get("number", "")).strip()[:32]
                test_status = data.get("status")
                if not number:
                    return self.send_json(400, {"error": "number 必填"})
                if test_status not in ("passed", "failed", "not_run"):
                    return self.send_json(400, {"error": "status 必须为 passed、failed 或 not_run"})
                required = ("input", "expected", "actual")
                if any(key not in data for key in required):
                    return self.send_json(400, {"error": "input、expected、actual 均为必填"})
                if test_status == "passed" and (data["actual"] is None or data["actual"] == ""):
                    return self.send_json(400, {"error": "通过记录必须包含实际结果"})
                if number.upper() == "T3" and test_status == "passed":
                    actual = data["actual"]
                    events = actual.get("events") if isinstance(actual, dict) else None
                    event_keys = [(item.get("event"), item.get("exhibit_id")) for item in events if isinstance(item, dict)] if isinstance(events, list) else []
                    try:
                        selected = event_keys.index(("selected", "B"))
                        stopped = event_keys.index(("stopped", "A"), selected + 1)
                        started = event_keys.index(("started", "B"), stopped + 1)
                    except ValueError:
                        return self.send_json(400, {"error": "T3 通过需提供 selected(B) → stopped(A) → started(B) 的有序实际事件"})
                    if actual.get("no_overlap") is not True or not (selected < stopped < started):
                        return self.send_json(400, {"error": "T3 通过需明确 no_overlap=true 且事件顺序正确"})
                try:
                    input_json, expected_json, actual_json = (json_text(data[key]) for key in required)
                except (TypeError, ValueError) as error:
                    return self.send_json(400, {"error": "测试内容必须可序列化为 JSON：%s" % error})
                with db() as connection:
                    run = connection.execute("SELECT version,mode FROM runs WHERE id=?", (run_id,)).fetchone()
                    if not run:
                        return self.send_json(404, {"error": "找不到该任务"})
                    version = data.get("version", run["version"])
                    if not isinstance(version, int) or version < 1:
                        return self.send_json(400, {"error": "version 必须为正整数"})
                    if not connection.execute("SELECT 1 FROM versions WHERE run_id=? AND version=?", (run_id, version)).fetchone():
                        return self.send_json(400, {"error": "关联版本不存在"})
                    created_at = now()
                    cursor = connection.execute("INSERT INTO test_records(run_id,number,test_input,expected,actual,status,created_at,version,mode) VALUES(?,?,?,?,?,?,?,?,?)", (run_id, number, input_json, expected_json, actual_json, test_status, created_at, version, run["mode"]))
                    record_event(connection, run_id, "test_recorded", {"test_id": cursor.lastrowid, "number": number, "status": test_status, "version": version, "mode": run["mode"]})
                return self.send_json(201, {"id": cursor.lastrowid, "run_id": run_id, "number": number, "input": data["input"], "expected": data["expected"], "actual": data["actual"], "status": test_status, "created_at": created_at, "version": version, "mode": run["mode"]})
            if path == "/api/route":
                text = str(data.get("text", "")).strip()
                state = data.get("state") if isinstance(data.get("state"), dict) else {}
                if not text:
                    return self.send_json(400, {"error": "消息为空"})
                routed_by = "model"
                try:
                    result = route_intent(text, state)
                except Exception as error:
                    result = rule_intent(text, state)
                    routed_by = "rule"
                    print("[route fallback] %s" % error, flush=True)
                result["routed_by"] = routed_by
                return self.send_json(200, result)
            if path == "/api/intake":
                raw = str(data.get("text", ""))
                exhibits = split_materials(raw)
                preview = []
                for item in exhibits:
                    pre = detect_source_issues({item["exhibit_id"]: item})
                    preview.append({
                        "exhibit_id": item["exhibit_id"],
                        "source_name": item["source_name"],
                        "chars": len(item["source_text"]),
                        "missing": pre[0],
                        "conflicts": pre[1],
                    })
                return self.send_json(200, {"exhibits": exhibits, "check": preview,
                                            "note": "已按标记切分；缺料与冲突在这里先报出来，生成时会再次检测"})
            if path == "/api/ask":
                run_id = int(data.get("run_id", 0) or 0)
                exhibit_id = str(data.get("exhibit_id", "")).strip().upper()
                question = str(data.get("question", "")).strip()
                if not question:
                    return self.send_json(400, {"error": "问题为空"})
                if not run_id:
                    return self.send_json(400, {"error": "先选一个任务；回答只依据该任务的授权资料"})
                with db() as connection:
                    row = connection.execute("SELECT sources FROM runs WHERE id=?", (run_id,)).fetchone()
                if not row:
                    return self.send_json(404, {"error": "找不到该任务"})
                result = answer_from_source(json.loads(row["sources"] or "{}"), exhibit_id, question)
                result["question"] = question
                return self.send_json(200, result)
            if path == "/api/testcases":
                run_id = int(data.get("run_id", 0) or 0)
                with db() as connection:
                    row = connection.execute("SELECT sources,draft,version FROM runs WHERE id=?", (run_id,)).fetchone()
                if not row:
                    return self.send_json(404, {"error": "找不到该任务"})
                cases = build_test_cases(json.loads(row["sources"] or "{}"), json.loads(row["draft"] or "{}"))
                cases["run_id"] = run_id
                cases["version"] = row["version"]
                return self.send_json(200, cases)
            if path == "/api/tts":
                run_id = int(data.get("run_id", 0) or 0)
                exhibit_id = str(data.get("exhibit_id", "")).strip().upper()
                text = str(data.get("text", "")).strip()
                if not text and run_id and exhibit_id:
                    with db() as connection:
                        row = connection.execute("SELECT draft FROM runs WHERE id=?", (run_id,)).fetchone()
                    if not row:
                        return self.send_json(404, {"error": "找不到该任务"})
                    for card in json.loads(row["draft"] or "{}").get("cards", []):
                        if card.get("exhibit_id") == exhibit_id:
                            text = card.get("narration", "")
                if not text:
                    return self.send_json(400, {"error": "没有可合成的讲解文本"})
                try:
                    audio = breeze_synthesize(text, str(data.get("instructions", "")), str(data.get("voice_id", "")), data.get("speed"))
                except RuntimeError as error:
                    return self.send_json(503, {"error": str(error), "tts_configured": breeze_ready()})
                except urllib.error.HTTPError as error:
                    detail = error.read(400).decode("utf-8", errors="replace")
                    return self.send_json(502, {"error": "Breeze 返回 HTTP %s：%s" % (error.code, detail[:300])})
                with db() as connection:
                    if run_id:
                        record_event(connection, run_id, "tts_rendered", {"exhibit_id": exhibit_id, "file": audio["file"], "voice_id": audio["voice_id"]})
                return self.send_json(200, audio)
            if path == "/api/tts/voices":
                try:
                    return self.send_json(200, {"voices": breeze_voices(), "tts_configured": breeze_ready()})
                except RuntimeError as error:
                    return self.send_json(503, {"error": str(error), "tts_configured": breeze_ready()})
                except urllib.error.HTTPError as error:
                    detail = error.read(400).decode("utf-8", errors="replace")
                    return self.send_json(502, {"error": "Breeze 返回 HTTP %s：%s" % (error.code, detail[:300])})
            if path == "/api/generate":
                title = str(data.get("title", "")).strip()[:120]
                if not title:
                    return self.send_json(400, {"error": "请填写展览名称"})
                sources = normalize_sources(data)
                source_map = json_text(sources)
                too_short = [eid for eid, item in sources.items() if not item["source_name"] or len(item["source_text"]) < 10]
                if too_short:
                    return self.send_json(400, {"error": "每项须提供来源名称及至少 10 字授权资料", "exhibits": too_short})
                # 缺料在生成前先检出，作为业务结果返回，而不是让模型凭常识补齐
                pre_missing, pre_conflicts = detect_source_issues(sources)
                if pre_missing or pre_conflicts:
                    with db() as connection:
                        cursor = connection.execute("INSERT INTO runs(created_at,title,source_name,source_text,draft,status,validation,mode,sources,error) VALUES(?,?,?,?,?,?,?,?,?,?)", (now(), title, "A/B/C 独立来源", json_text(sources), "{}", "blocked", json_text({"passed": False, "checks": 0, "total_checks": 0, "issues": ["资料缺料：%d 项" % len(pre_missing), "来源冲突：%d 项" % len(pre_conflicts)], "detected": {"missing_materials": pre_missing, "conflicts": pre_conflicts}}), "demo" if DEMO_MODE else "live", json_text(sources), "资料缺料或存在来源冲突，需客户补充后再生成"))
                        run_id = cursor.lastrowid
                        record_event(connection, run_id, "blocked_before_generation", {"missing": pre_missing, "conflicts": pre_conflicts})
                    return self.send_json(409, {"id": run_id, "status": "blocked", "approval_allowed": False, "generated": False, "missing_materials": pre_missing, "conflicts": pre_conflicts, "error": "资料缺料或存在未解决来源冲突：按第零原则不生成可交付内容，请客户补充资料或确认冲突后重试"})
                with db() as connection:
                    cursor = connection.execute("INSERT INTO runs(created_at,title,source_name,source_text,draft,status,validation,mode,sources,error) VALUES(?,?,?,?,?,?,?,?,?,?)", (now(), title, "A/B/C 独立来源", source_map, "{}", "processing", "{}", "demo" if DEMO_MODE else "live", source_map, ""))
                    run_id = cursor.lastrowid
                    record_event(connection, run_id, "task_created", {"mode": "demo" if DEMO_MODE else "live", "exhibits": list(sources)})
                # 后台执行，接口立即返回 run_id，前端轮询 /api/jobs/{id} 看真实进度
                worker = threading.Thread(target=run_generation, args=(run_id, title, sources), daemon=True)
                worker.start()
                return self.send_json(202, {"id": run_id, "status": "processing", "mode": "demo" if DEMO_MODE else "live"})
            if path == "/api/review/sync":
                # 兼容旧前端：同步跑完再返回
                title = str(data.get("title", "")).strip()[:120]
                sources = normalize_sources(data)
                with db() as connection:
                    cursor = connection.execute("INSERT INTO runs(created_at,title,source_name,source_text,draft,status,validation,mode,sources,error) VALUES(?,?,?,?,?,?,?,?,?,?)", (now(), title, "A/B/C 独立来源", json_text(sources), "{}", "processing", "{}", "demo" if DEMO_MODE else "live", json_text(sources), ""))
                    run_id = cursor.lastrowid
                run_generation(run_id, title, sources)
                with db() as connection:
                    row = connection.execute("SELECT status,draft,validation FROM runs WHERE id=?", (run_id,)).fetchone()
                return self.send_json(200, {"id": run_id, "status": row["status"], "draft": json.loads(row["draft"]), "validation": json.loads(row["validation"]), "mode": "demo" if DEMO_MODE else "live"})
            if path in ("/api/review", "/api/revise"):
                run_id = int(data.get("run_id", 0))
                with db() as connection:
                    row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
                    if not row:
                        return self.send_json(404, {"error": "找不到该任务"})
                    sources = json.loads(row["sources"] or "{}")
                    if path == "/api/revise":
                        if row["status"] in ("failed", "processing"):
                            return self.send_json(409, {"error": "该任务没有草稿，不能修订或批准", "status": row["status"]})
                        # 审计 #8：blocked 任务（资料缺料/冲突）不得被 revise 洗成 draft，
                        # 否则会掩盖"资料本身有问题"的事实。必须补充资料后重新生成。
                        if row["status"] == "blocked":
                            return self.send_json(409, {"error": "该任务因资料缺料或来源冲突被阻断，修改文案无法解除；请补充资料后重新生成", "status": "blocked"})
                        old_draft = json.loads(row["draft"])
                        draft = data.get("draft")
                        if not isinstance(draft, dict):
                            return self.send_json(400, {"error": "修订请求必须包含 draft 对象"})
                        validation = validate_draft(sources, draft)
                        old_text = json.dumps(old_draft, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
                        new_text = json.dumps(draft, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
                        diff = list(difflib.unified_diff(old_text, new_text, fromfile="旧版本", tofile="新版本", lineterm=""))
                        # 审计 #3：版本号必须在同一写事务内自增，避免并发读到同一个版本号
                        # 触发 UNIQUE 冲突并丢更新。用 BEGIN IMMEDIATE + RETURNING 原子取号。
                        try:
                            connection.execute("BEGIN IMMEDIATE")
                            version = connection.execute(
                                "UPDATE runs SET version=version+1 WHERE id=? RETURNING version", (run_id,)
                            ).fetchone()[0]
                            connection.execute(
                                "UPDATE runs SET draft=?,status='draft',validation=?,error='' WHERE id=?",
                                (json_text(draft), json_text(validation), run_id),
                            )
                            connection.execute("INSERT INTO versions(run_id,version,created_at,draft,validation,diff,actor) VALUES(?,?,?,?,?,?,?)", (run_id, version, now(), json_text(draft), json_text(validation), json_text(diff), str(data.get("actor", "human-editor"))[:80]))
                            record_event(connection, run_id, "revised", {"version": version, "diff_len": len(diff), "validation_passed": validation["passed"]})
                            connection.execute("COMMIT")
                        except sqlite3.IntegrityError:
                            connection.execute("ROLLBACK")
                            return self.send_json(409, {"error": "该任务正在被其他人修改，请刷新后重试"})
                        except Exception:
                            connection.execute("ROLLBACK")
                            raise
                        return self.send_json(200, {"id": run_id, "version": version, "status": "draft", "draft": draft, "diff": diff, "validation": validation, "requires_confirmation": True})
                    decision = data.get("decision")
                    if decision not in ("approved", "needs_revision"):
                        return self.send_json(400, {"error": "decision 必须为 approved 或 needs_revision"})
                    if "draft" in data:
                        return self.send_json(400, {"error": "审批不能替换草稿；请先通过修订接口提交新版本"})
                    if row["status"] in ("failed", "processing") or not row["draft"] or row["draft"] == "{}":
                        return self.send_json(422, {"error": "该任务没有可审批草稿", "status": row["status"], "approval_allowed": False})
                    # blocked 任务不得经 needs_revision 绕回可编辑状态：
                    # 否则"退回 → revise → draft"能洗掉"资料本身有问题"这个事实。
                    # 阻断只能通过补充资料后重新生成来解除。
                    if row["status"] == "blocked":
                        return self.send_json(
                            409,
                            {
                                "error": "该任务因资料缺料或来源冲突被阻断，审批操作无法解除；请补充资料后重新生成",
                                "status": "blocked",
                                "approval_allowed": False,
                            },
                        )
                    draft = json.loads(row["draft"])
                    validation = validate_draft(sources, draft)
                    if decision == "approved" and not validation["passed"]:
                        return self.send_json(422, {"error": "质量门未通过，不能批准", "validation": validation, "approval_allowed": False})
                    # demo 允许走完流程以便演示，但状态单独记为 approved_demo，
                    # 导出包带显著 DEMO 水印，且不进入交付台账，避免冒充 AI 交付证据。
                    if decision == "approved" and row["mode"] == "demo":
                        status = "approved_demo"
                    else:
                        status = "approved" if decision == "approved" else "needs_revision"
                    connection.execute("UPDATE runs SET draft=?,validation=?,status=? WHERE id=?", (json_text(draft), json_text(validation), status, run_id))
                    record_event(connection, run_id, "human_review", {"decision": decision, "status": status})
                return self.send_json(200, {"ok": True, "status": status, "validation": validation})
            if path == "/api/business":
                payload = {k: data.get(k) for k in (
                    "quote", "quote_basis", "hours", "hours_source", "hourly_rate",
                    "model_cost", "voice_cost", "other_cost", "customer_alt_cost",
                    "baseline_minutes", "baseline_scope", "employee_minutes", "employee_scope", "sample_n",
                ) if k in data}
                computed = compute_economics(payload)
                with db() as connection:
                    connection.execute("INSERT INTO business(updated_at, payload) VALUES(?,?)", (now(), json_text(payload)))
                return self.send_json(200, {"saved": payload, "computed": computed})
            if path == "/api/customers":
                name = str(data.get("name", "")).strip()[:120]
                if not name:
                    return self.send_json(400, {"error": "请填写客户名称"})
                with db() as connection:
                    cursor = connection.execute(
                        "INSERT INTO customers(created_at,name,contact,budget_owner,note) VALUES(?,?,?,?,?)",
                        (now(), name, str(data.get("contact", ""))[:120],
                         str(data.get("budget_owner", ""))[:120], str(data.get("note", ""))[:500]),
                    )
                return self.send_json(201, {"id": cursor.lastrowid, "name": name})
            if path == "/api/quotes":
                customer_id = int(data.get("customer_id", 0) or 0)
                if not customer_id:
                    return self.send_json(400, {"error": "缺少 customer_id"})
                basis = str(data.get("basis", "assumed"))
                if basis not in ("assumed", "interviewed", "signed"):
                    return self.send_json(400, {"error": "basis 必须为 assumed、interviewed 或 signed"})
                with db() as connection:
                    if not connection.execute("SELECT 1 FROM customers WHERE id=?", (customer_id,)).fetchone():
                        return self.send_json(404, {"error": "找不到该客户"})
                    cursor = connection.execute(
                        "INSERT INTO quotes(created_at,customer_id,run_id,amount,currency,basis,scope,note) VALUES(?,?,?,?,?,?,?,?)",
                        (now(), customer_id, int(data.get("run_id", 0) or 0) or None,
                         data.get("amount"), str(data.get("currency", "CNY"))[:8], basis,
                         str(data.get("scope", ""))[:300], str(data.get("note", ""))[:500]),
                    )
                return self.send_json(201, {"id": cursor.lastrowid, "basis": basis})
            if path == "/api/acceptances":
                run_id = int(data.get("run_id", 0) or 0)
                if not run_id:
                    return self.send_json(400, {"error": "缺少 run_id"})
                signed_by = str(data.get("signed_by", "")).strip()[:120]
                if not signed_by:
                    return self.send_json(400, {"error": "签收必须有签收人；未签收不能计入成交"})
                with db() as connection:
                    run = connection.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
                    if not run:
                        return self.send_json(404, {"error": "找不到该任务"})
                    if run["status"] not in ("approved", "approved_demo"):
                        return self.send_json(409, {"error": "任务尚未通过人工审核，不能登记签收", "status": run["status"]})
                    cursor = connection.execute(
                        "INSERT INTO acceptances(created_at,run_id,quote_id,signed_by,signed_at,amount,criteria,note) VALUES(?,?,?,?,?,?,?,?)",
                        (now(), run_id, int(data.get("quote_id", 0) or 0) or None, signed_by,
                         str(data.get("signed_at", now()))[:40], data.get("amount"),
                         json_text(data.get("criteria", [])), str(data.get("note", ""))[:500]),
                    )
                    record_event(connection, run_id, "accepted", {"signed_by": signed_by, "amount": data.get("amount")})
                return self.send_json(201, {"id": cursor.lastrowid, "run_id": run_id})
            if path == "/api/feedback":
                run_id = int(data.get("run_id", 0)) or None
                category, note = str(data.get("category", "")).strip()[:80], str(data.get("note", "")).strip()[:1000]
                if not category or not note:
                    return self.send_json(400, {"error": "请填写反馈类别和具体观察"})
                candidate = "候选规则：针对“%s”增加检查，负责人审批后才启用。" % category
                with db() as connection:
                    version = connection.execute("SELECT COALESCE(MAX(version),0)+1 FROM feedback").fetchone()[0]
                    cursor = connection.execute("INSERT INTO feedback(created_at,run_id,category,note,candidate,version) VALUES(?,?,?,?,?,?)", (now(), run_id, category, note, candidate, version))
                return self.send_json(200, {"id": cursor.lastrowid, "version": version, "candidate": candidate, "requires_human_approval": True, "type": "改进候选台账"})
            return self.send_json(404, {"error": "not found"})
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json(400, {"error": str(error)})
        except Exception as error:
            # 审计 #11：不把底层异常原文回给客户端，避免泄露表结构与实现细节。
            # 详细错误只写服务端日志和事件表，便于排查。
            trace_id = uuid.uuid4().hex[:8]
            print("[error %s] %s" % (trace_id, error), flush=True)
            try:
                with db() as connection:
                    record_event(connection, None, "server_error", {"trace_id": trace_id, "error": str(error)[:500]})
            except Exception:
                pass
            return self.send_json(500, {"error": "内部处理失败，请稍后重试", "trace_id": trace_id})


if __name__ == "__main__":
    initialize()
    print("Exhibit AI Employee listening on %s:%s (mode=%s)" % (HOST, PORT, "demo" if DEMO_MODE else "live"), flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
