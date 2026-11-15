#!/usr/bin/env python3
import difflib
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("EXHIBIT_DB", ROOT / "employee.sqlite3"))
SOUL_PATH = ROOT / "config" / "SOUL.md"
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "4181"))
API_BASE = os.environ.get("AI_BASE_URL", "https://api.gmi-serving.com/v1").rstrip("/")
API_KEY = os.environ.get("GMI_API_KEY", "")
MODEL = os.environ.get("AI_MODEL", "")
DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() in ("1", "true", "yes")
APP_VERSION = "2.0"
EXHIBIT_IDS = ("A", "B", "C")


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
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
        connection.execute("CREATE TABLE IF NOT EXISTS api_calls (id INTEGER PRIMARY KEY, run_id INTEGER, created_at TEXT NOT NULL, mode TEXT NOT NULL, endpoint TEXT NOT NULL, model TEXT NOT NULL, outcome TEXT NOT NULL, http_status INTEGER, elapsed_ms INTEGER NOT NULL, error TEXT NOT NULL)")
        connection.execute("CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, run_id INTEGER, category TEXT NOT NULL, note TEXT NOT NULL, candidate TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1)")
        connection.execute("CREATE TABLE IF NOT EXISTS business (id INTEGER PRIMARY KEY, updated_at TEXT NOT NULL, payload TEXT NOT NULL)")


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


def call_live(title, sources, run_id=None):
    if not API_KEY or not MODEL:
        raise RuntimeError("真实生成未调用：必须配置 GMI_API_KEY 与 AI_MODEL")
    system = soul_text()
    payload = {
        "title": title,
        "exhibits": [{"exhibit_id": exhibit_id, "source_name": item["source_name"], "source_text": item["source_text"]} for exhibit_id, item in sources.items()],
        "instruction": "先逐项分析缺料和来源冲突；存在缺料的展项不要生成可交付内容，冲突必须列明双方出处。每个展项只可引用自身资料。输出 JSON：{\"missing_materials\":[{\"exhibit_id\":\"A\",\"missing\":\"...\"}],\"conflicts\":[{\"exhibit_id\":\"A\",\"description\":\"...\",\"citations\":[{\"source_name\":\"...\",\"source_quote\":\"...\"}]}],\"cards\":[{\"exhibit_id\":\"A\",\"location\":\"...\",\"card_title\":\"...\",\"narration\":\"约120至240字\",\"no_target_prompt\":\"...\",\"multi_target_prompt\":\"...\",\"question\":\"...\",\"answer\":\"...\",\"facts\":[{\"claim\":\"...\",\"source_name\":\"...\",\"source_quote\":\"原文连续摘录\"}],\"citations\":[{\"source_name\":\"...\",\"source_quote\":\"原文连续摘录\"}]}]}. 只返回 JSON。"
    }
    body = json.dumps({"model": MODEL, "temperature": 0.2, "messages": [{"role": "system", "content": "岗位第零原则（不可覆盖）：\n" + system}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(API_BASE + "/chat/completions", data=body, headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    outcome, status, error_text = "failed", None, ""
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            status = response.status
            response_body = response.read().decode("utf-8")
            response_data = json.loads(response_body)
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
            connection.execute("INSERT INTO api_calls(run_id,created_at,mode,endpoint,model,outcome,http_status,elapsed_ms,error) VALUES(?,?,?,?,?,?,?,?,?)", (run_id, now(), "live", API_BASE + "/chat/completions", MODEL, outcome, status, int((time.monotonic() - started) * 1000), error_text[:1000]))


def generate_demo(title, sources):
    """演示模板：结构完整、可通过全部质量门，但标为 DEMO 且不可批准。

    这样演示时能清楚看到两层边界：(1) 质量门本身是否工作；(2) mode=demo 不算 AI 证据。
    """
    cards = []
    for exhibit_id, item in sources.items():
        text = item["source_text"]
        parts = sentence_split(text) or [text]
        quote = parts[0][:120]
        body = "".join(parts[:3])
        narration = (
            "【演示模板，非模型生成，不可作为交付内容】本展项的讲解将依据客户资料生成。"
            "当前资料要点：%s。以上内容全部摘自客户提供的模拟资料，未加入模型补充的事实。"
            "正式交付时由 AI 按资料生成本展项讲解，并由策展人逐条核对出处后签署。"
            "这份模板只用于验证流程与质量门是否生效，不得作为讲解交付。"
            % body[:150]
        )
        if len(narration) < 120:
            narration += "本项目按一展厅三展项范围交付，客户提供授权资料与一名审核人。"
        cards.append(
            {
                "exhibit_id": exhibit_id,
                "location": "展项 " + exhibit_id,
                "card_title": title + "｜演示卡 " + exhibit_id,
                "narration": narration[:240],
                "no_target_prompt": "您可以选择一个展项，听它的介绍。",
                "multi_target_prompt": "检测到多个候选，请在屏幕上选择要听的展项。",
                "question": "资料中记载了什么？",
                "answer": quote,
                "facts": [{"claim": quote, "source_name": item["source_name"], "source_quote": quote}] if quote in narration else [],
                "citations": [{"source_name": item["source_name"], "source_quote": quote}],
            }
        )
    return {"missing_materials": [], "conflicts": [], "cards": cards}


def normalize_sources(data):
    exhibits = data.get("exhibits")
    if not isinstance(exhibits, list) or len(exhibits) != 3:
        raise ValueError("必须提交 A、B、C 三个独立展项资料")
    result = {}
    for entry in exhibits:
        if not isinstance(entry, dict):
            raise ValueError("展项资料格式无效")
        exhibit_id = str(entry.get("exhibit_id", "")).strip().upper()
        if exhibit_id not in EXHIBIT_IDS or exhibit_id in result:
            raise ValueError("展项编号必须分别为 A、B、C")
        name = str(entry.get("source_name", "")).strip()[:200]
        text = str(entry.get("source_text", "")).strip()[:20000]
        result[exhibit_id] = {"source_name": name, "source_text": text}
    if set(result) != set(EXHIBIT_IDS):
        raise ValueError("必须完整提交 A、B、C 三个展项")
    return {key: result[key] for key in EXHIBIT_IDS}


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
CONFLICT_MARKERS = ("但另一种说法", "另据", "然而资料", "说法不一", "相互矛盾", "与此矛盾", "不一致")
YEAR_OR_NUM = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)|\d+(?:\.\d+)?")
# 中文数字年份：资料常写"一八五零年""一九五八年"，必须一并识别，否则冲突门会漏检
CN_DIGITS = {"〇": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9"}
CN_YEAR = re.compile(r"([〇零一二三四五六七八九]{4})\s*年")


def cn_years(text):
    """把资料中的中文数字年份转成阿拉伯数字，例如 一八五零年 → 1850。"""
    return [int("".join(CN_DIGITS[ch] for ch in match)) for match in CN_YEAR.findall(text or "")]


def all_years(text):
    """返回资料中的全部四位年份（阿拉伯 + 中文），用于冲突比对。"""
    found = [int(y) for y in re.findall(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)", text or "")]
    found.extend(cn_years(text))
    return found


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
        substantive = [s for s in sentences if len(s) >= 12]

        marked = [s for s in sentences if any(mark in s for mark in MISSING_MARKERS)]
        if marked:
            missing.append({"exhibit_id": exhibit_id, "missing": "资料显式标注缺项：%s" % marked[0][:60]})
        elif len(substantive) < 2:
            missing.append(
                {
                    "exhibit_id": exhibit_id,
                    "missing": "资料仅 %d 字、%d 句可用事实，不足以支撑一段 30–60 秒讲解，需客户补充"
                    % (len(text), len(substantive)),
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

        # 隐式冲突：同一展项资料内出现两个不同年份（阿拉伯或中文数字）
        found = False
        # 强信号：转述结构（据某资料/据记载/称）出现在多句里，且给出不同年份
        relay_sentences = [s for s in substantive if any(m in s for m in ("据", "记载", "称"))]
        relay_years = {}
        for sentence in relay_sentences:
            for year in all_years(sentence):
                relay_years.setdefault(year, sentence)
        if len(relay_years) >= 2:
            ordered = sorted(relay_years)
            conflicts.append(
                {
                    "exhibit_id": exhibit_id,
                    "description": "资料以转述方式给出 %d 个不同年份（%s），需客户确认哪个版本有效"
                    % (len(ordered), " / ".join(str(y) for y in ordered)),
                    "citations": [
                        {"source_name": item["source_name"], "source_quote": relay_years[y][:120]} for y in ordered
                    ],
                }
            )
            continue

        years_in_source = []
        for sentence in substantive:
            years_in_source.extend(all_years(sentence))
        distinct_years = set(years_in_source)
        if len(distinct_years) >= 2 and any(mark in text for mark in ("据", "记载", "称", "资料", "一说", "另说")):
            carriers = {}
            for sentence in substantive:
                for year in distinct_years:
                    if year in all_years(sentence):
                        carriers.setdefault(year, sentence)
            ordered = sorted(carriers)
            for index, first_year in enumerate(ordered):
                for second_year in ordered[index + 1 :]:
                    first, second = carriers[first_year], carriers[second_year]
                    if first is not second and lcs_len(first, second) >= 4:
                        conflicts.append(
                            {
                                "exhibit_id": exhibit_id,
                                "description": "资料对同一对象给出不同年份：%s / %s，需客户确认哪个版本有效"
                                % (first_year, second_year),
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

        # 兜底：不同数值出现在语境重叠的句子里
        if found:
            continue
        for i, first in enumerate(substantive):
            for second in substantive[i + 1 :]:
                if lcs_len(first, second) < 6:
                    continue
                a = set(YEAR_OR_NUM.findall(first)) - {"", None}
                b = set(YEAR_OR_NUM.findall(second)) - {"", None}
                if a and b and a != b and not (a & b):
                    conflicts.append(
                        {
                            "exhibit_id": exhibit_id,
                            "description": "资料对同一对象给出不同数值：%s / %s"
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


def validate_draft(sources, draft):
    issues, checks, total = [], 0, 0
    # 程序化检测资料的缺料与冲突，不再依赖模型自报
    detected_missing, detected_conflicts = detect_source_issues(sources)
    if not isinstance(draft, dict):
        return {"passed": False, "checks": 0, "total_checks": 1, "issues": ["草稿必须是对象"]}
    missing = draft.get("missing_materials", [])
    conflicts = draft.get("conflicts", [])
    for item in (missing if isinstance(missing, list) else []) + detected_missing:
        exhibit_id = item.get("exhibit_id") if isinstance(item, dict) else None
        if exhibit_id in EXHIBIT_IDS:
            issues.append("展项 %s 缺料：%s" % (exhibit_id, item.get("missing", "需客户补充")))
    for item in (conflicts if isinstance(conflicts, list) else []) + detected_conflicts:
        if isinstance(item, dict) and item.get("exhibit_id") in EXHIBIT_IDS:
            issues.append("展项 %s 存在未解决来源冲突：%s" % (item["exhibit_id"], item.get("description", "需人工确认")))
    missing = missing if isinstance(missing, list) else []
    conflicts = conflicts if isinstance(conflicts, list) else []
    cards = draft.get("cards")
    if not isinstance(cards, list):
        return {"passed": False, "checks": checks, "total_checks": total + 1, "issues": issues + ["内容必须包含 cards 数组"], "detected": {"missing_materials": missing, "conflicts": conflicts}}
    total += 1
    if len(cards) == 3 and {c.get("exhibit_id") for c in cards if isinstance(c, dict)} == set(EXHIBIT_IDS):
        checks += 1
    else:
        issues.append("P0覆盖门：必须且只能有 A、B、C 各一份内容")
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
            if (not isinstance(fact, dict) or not isinstance(fact.get("claim"), str) or not fact["claim"].strip()
                    or not isinstance(fact.get("source_quote"), str) or not fact["source_quote"].strip()
                    or fact["claim"].strip() not in narration
                    or fact["source_quote"].strip() not in source
                    or fact["claim"].strip() not in fact["source_quote"].strip()
                    or fact.get("source_name") != sources[eid]["source_name"]):
                issues.append("P0出处映射门：展项 %s 存在不能回溯到本项原文的事实" % eid)
        numbers = re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?", narration)
        unsupported_numbers = [number for number in numbers if number not in allowed_text]
        total += 1
        if not unsupported_numbers:
            checks += 1
        else:
            issues.append("P0数字门：展项 %s 讲解包含原文未支持数字：%s" % (eid, "、".join(unsupported_numbers)))
        named_entities = set(re.findall(r"(?<![A-Za-z])[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*", narration))
        named_entities.update(re.findall(r"[《“\"]([^》”\"]{2,30})[》”\"]", narration))
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
        if "演示模板" in narration or "演示草稿" in narration:
            issues.append("演示内容不可标记为可交付")
    return {"passed": not issues, "checks": checks, "total_checks": total, "issues": issues}


def compute_economics(payload):
    """项目经济模型：报价 − 实测直接成本 = 项目贡献；并给出保本价。

    所有输入必须来自实测或明确标注为假设；缺少实测时返回 missing 字段，
    不编造数字。口径：未计获客、税费、设备折旧与管理成本。
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
    hours = num("hours")
    rate = num("hourly_rate")
    model_cost = num("model_cost")
    voice_cost = num("voice_cost")
    other_cost = num("other_cost")
    baseline = num("baseline_minutes")
    employee_minutes = num("employee_minutes")

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
    parts = {"人工": None, "模型": model_cost, "语音": voice_cost, "其他": other_cost}
    if hours is not None and rate is not None:
        parts["人工"] = round(hours * rate, 2)
    direct_cost = None
    if all(v is not None for v in parts.values()):
        direct_cost = round(sum(parts.values()), 2)
    contribution = round(quote - direct_cost, 2) if quote is not None and direct_cost is not None else None
    margin = round(contribution / quote * 100, 1) if contribution is not None and quote else None
    result = {
        "inputs": {
            "quote": quote,
            "hours": hours,
            "hourly_rate": rate,
            "model_cost": model_cost,
            "voice_cost": voice_cost,
            "other_cost": other_cost,
            "baseline_minutes": baseline,
            "employee_minutes": employee_minutes,
        },
        "cost_parts": parts,
        "direct_cost": direct_cost,
        "contribution": contribution,
        "margin_percent": margin,
        "breakeven_quote": direct_cost,
        "missing_inputs": missing,
        "caveat": "未计获客、税费、设备折旧与管理成本；报价是访谈测试假设，不是市场价或收入预测。",
    }
    if baseline and employee_minutes:
        result["efficiency"] = {
            "baseline_minutes": baseline,
            "employee_minutes": employee_minutes,
            "saved_minutes": round(baseline - employee_minutes, 1),
            "note": "同一资料、同一质量与审核要求下的实测对照；样本量小，不构成稳定产能结论。",
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
        tests = connection.execute(
            "SELECT number,status,expected,actual,created_at,version,mode FROM test_records WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
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

    version_rows = ["| 版本 | 时间 | 操作者 | 变更 |", "|---|---|---|---|"]
    for version in versions:
        changes = json.loads(version["diff"] or "[]")
        summary = ("%d 处修改" % len(changes)) if isinstance(changes, list) and changes else "首次生成"
        version_rows.append("| v%s | %s | %s | %s |" % (version["version"], version["created_at"], version["actor"], summary))

    gate_rows = ["- 质量门：%s（%s / %s 项）" % ("通过" if validation.get("passed") else "未通过", validation.get("checks"), validation.get("total_checks"))]
    for issue in validation.get("issues", []):
        gate_rows.append("- 阻断项：%s" % issue)

    return {
        "01_需求与资料清单.md": "# 需求与资料清单\n\n- 项目：%s\n- 任务编号：#%s\n- 版本：v%s\n- 生成模式：%s\n- 审核状态：%s\n- 导出时间：%s\n\n## 资料\n\n%s\n" % (
            row["title"], run_id, row["version"], row["mode"], row["status"], now(), "\n".join(item_rows)),
        "02_展项知识卡与出处.md": "# 展项知识卡与出处\n\n> 每条事实均须可回溯到本展项授权资料。\n\n" + "\n\n".join(card_blocks) + "\n",
        "03_讲解及过渡文案.md": "# 讲解及过渡文案\n\n" + "\n\n".join(
            "## 展项 %s · %s\n\n%s\n\n**过渡话术**\n\n- 无目标：%s\n- 多目标：%s\n" % (
                c.get("exhibit_id"), c.get("card_title"), c.get("narration", ""),
                c.get("no_target_prompt", ""), c.get("multi_target_prompt", "")) for c in cards) + "\n",
        "04_音频/README.md": "# 音频说明\n\n本包不含音频文件。交付时按下列需求生成或人工录制，并在文件名标注来源（TTS / 人工）。\n\n"
            + "\n".join("- 展项 %s：%d 字，约 %d 秒" % (c.get("exhibit_id"), len(c.get("narration", "")), round(len(c.get("narration", "")) / 4)) for c in cards) + "\n",
        "05_场景测试记录.md": "# 场景测试记录\n\n" + "\n".join(test_rows) + "\n\n未运行用例：%s（未运行不代表通过）\n" % ("、".join(not_run) or "无"),
        "06_修改差异与待解决问题.md": "# 修改差异与待解决问题\n\n## 版本历史\n\n%s\n\n## 待解决问题\n\n- 本包未包含眼镜端实机验证。\n- 客户需自行确认展项资料授权范围与期限。\n" % "\n".join(version_rows),
        "07_客户审核与验收单.md": "# 客户审核与验收单\n\n- 项目：%s\n- 版本：v%s\n- 模式：%s\n\n%s\n\n| 验收项 | 状态 |\n|---|---|\n| 内容与来源逐条对应 | 是 |\n| 客户确认关键事实 | 待客户签署 |\n| 指定场景测试有记录 | 见 05 |\n| 素材与版本清单完整 | 是 |\n| 未解决问题已列明 | 见 06 |\n\n签收本内容包不等于硬件上线验收。\n" % (
            row["title"], row["version"], row["mode"], "\n".join(gate_rows)),
    }


def snapshot(draft, validation, version, actor="system"):
    return (version, now(), json_text(draft), json_text(validation), "", actor)


class Handler(BaseHTTPRequestHandler):
    server_version = "ExhibitEmployee/2.0"

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
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("请求超过 1 MB")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            try:
                page = (ROOT / "index.html").read_bytes()
            except OSError as error:
                return self.send_json(500, {"error": "index.html 读取失败：%s" % error})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(page)
        if path == "/api/health":
            return self.send_json(200, {"ok": True, "mode": "demo" if DEMO_MODE else "live", "demo_is_delivery_evidence": False, "model_configured": bool(MODEL), "api_key_configured": bool(API_KEY), "soul_configured": SOUL_PATH.is_file(), "version": APP_VERSION})
        if path == "/api/runs":
            with db() as connection:
                rows = connection.execute("SELECT id,created_at,title,status,mode,version,validation,error FROM runs ORDER BY id DESC LIMIT 50").fetchall()
            return self.send_json(200, {"runs": [dict(r) for r in rows]})
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
                        records.append(item)
                    return self.send_json(200, {"run_id": run_id, "tests": records})
                current = json.loads(row["draft"])
                validation = json.loads(row["validation"] or "{}")
                if row["status"] != "approved":
                    return self.send_json(409, {"error": "未通过人工审核的任务不能导出交付包", "status": row["status"], "validation": validation})
                if not validation.get("passed"):
                    return self.send_json(409, {"error": "P0 质量门未通过，不能导出交付包", "status": row["status"], "validation": validation})
                pieces = build_package(row, current, validation, run_id)
                record_event(db(), run_id, "exported", {"version": row["version"], "files": list(pieces)})
                return self.send_json(200, {"package": {"id": run_id, "title": row["title"], "version": row["version"], "mode": row["mode"], "status": row["status"], "files": pieces, "base_name": package_name(row)}})
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
                try:
                    if DEMO_MODE:
                        draft = generate_demo(title, sources)
                        log_mode = "demo"
                    else:
                        # live 模式：缺凭据必须失败，绝不降级成演示模板冒充 AI 产出
                        draft = call_live(title, sources, run_id)
                        log_mode = "live"
                except Exception as error:
                    message = str(error)[:1000]
                    with db() as connection:
                        connection.execute("UPDATE runs SET status='failed',error=? WHERE id=?", (message, run_id))
                        record_event(connection, run_id, "generation_failed", {"error": message})
                    return self.send_json(502, {"id": run_id, "mode": "live", "status": "failed", "error": message, "draft": None, "approval_allowed": False})
                validation = validate_draft(sources, draft)
                status = "draft" if validation["passed"] else "blocked"
                with db() as connection:
                    connection.execute("UPDATE runs SET draft=?,status=?,validation=? WHERE id=?", (json_text(draft), status, json_text(validation), run_id))
                    connection.execute("INSERT INTO versions(run_id,version,created_at,draft,validation,diff,actor) VALUES(?,?,?,?,?,?,?)", (run_id, 1, now(), json_text(draft), json_text(validation), "[]", "model" if not DEMO_MODE else "demo-template"))
                    record_event(connection, run_id, "generation_completed", {"status": status, "validation": validation})
                return self.send_json(200, {"id": run_id, "mode": "demo" if DEMO_MODE else "live", "status": status, "draft": draft, "validation": validation, "approval_allowed": False})
            if path in ("/api/review", "/api/revise"):
                run_id = int(data.get("run_id", 0))
                with db() as connection:
                    row = connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
                    if not row:
                        return self.send_json(404, {"error": "找不到该任务"})
                    sources = json.loads(row["sources"] or "{}")
                    if path == "/api/revise":
                        if row["status"] == "failed":
                            return self.send_json(409, {"error": "失败任务没有草稿，不能修订或批准"})
                        old_draft = json.loads(row["draft"])
                        draft = data.get("draft")
                        if not isinstance(draft, dict):
                            return self.send_json(400, {"error": "修订请求必须包含 draft 对象"})
                        validation = validate_draft(sources, draft)
                        old_text = json.dumps(old_draft, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
                        new_text = json.dumps(draft, ensure_ascii=False, indent=2, sort_keys=True).splitlines()
                        diff = list(difflib.unified_diff(old_text, new_text, fromfile="旧版本", tofile="新版本", lineterm=""))
                        version = row["version"] + 1
                        connection.execute("UPDATE runs SET draft=?,status='draft',validation=?,version=?,error='' WHERE id=?", (json_text(draft), json_text(validation), version, run_id))
                        connection.execute("INSERT INTO versions(run_id,version,created_at,draft,validation,diff,actor) VALUES(?,?,?,?,?,?,?)", (run_id, version, now(), json_text(draft), json_text(validation), json_text(diff), str(data.get("actor", "human-editor"))[:80]))
                        record_event(connection, run_id, "revised", {"version": version, "diff": diff, "validation": validation})
                        return self.send_json(200, {"id": run_id, "version": version, "status": "draft", "draft": draft, "diff": diff, "validation": validation, "requires_confirmation": True})
                    decision = data.get("decision")
                    if decision not in ("approved", "needs_revision"):
                        return self.send_json(400, {"error": "decision 必须为 approved 或 needs_revision"})
                    if row["status"] in ("failed", "processing") or not row["draft"] or row["draft"] == "{}":
                        return self.send_json(422, {"error": "该任务没有可审批草稿", "status": row["status"], "approval_allowed": False})
                    draft = data.get("draft") if isinstance(data.get("draft"), dict) else json.loads(row["draft"])
                    validation = validate_draft(sources, draft)
                    if decision == "approved" and (not validation["passed"] or row["mode"] == "demo"):
                        reason = "DEMO模板不是AI交付证据" if row["mode"] == "demo" else "校验未通过"
                        return self.send_json(422, {"error": reason + "，不能批准", "validation": validation, "approval_allowed": False})
                    status = "approved" if decision == "approved" else "needs_revision"
                    connection.execute("UPDATE runs SET draft=?,validation=?,status=? WHERE id=?", (json_text(draft), json_text(validation), status, run_id))
                    record_event(connection, run_id, "human_review", {"decision": decision, "status": status})
                return self.send_json(200, {"ok": True, "status": status, "validation": validation})
            if path == "/api/business":
                payload = {k: data.get(k) for k in ("quote", "hours", "hourly_rate", "model_cost", "voice_cost", "other_cost", "baseline_minutes", "employee_minutes") if k in data}
                computed = compute_economics(payload)
                with db() as connection:
                    connection.execute("INSERT INTO business(updated_at, payload) VALUES(?,?)", (now(), json_text(payload)))
                return self.send_json(200, {"saved": payload, "computed": computed})
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
            return self.send_json(500, {"error": "内部处理失败：%s" % str(error)[:500]})


if __name__ == "__main__":
    initialize()
    print("Exhibit AI Employee listening on %s:%s (mode=%s)" % (HOST, PORT, "demo" if DEMO_MODE else "live"), flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
