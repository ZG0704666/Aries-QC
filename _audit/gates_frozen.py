"""程序化质量门。

设计原则：
1. 所有判定都是确定性的、可复跑的，不依赖模型自评。
2. 每条规则可单独关闭/调参，便于 RSI 回归对比（见 Rules.version）。
3. 门的输出同时给出 checks/total 和逐条 issues，便于报告与审计。

门分级：
- P0（阻断）：结构、覆盖、串台、引用逐字、数字、支持度、长度、待确认标记
- 只有 P0 全部通过，review 接口才允许 approved。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

SENT_SPLIT = re.compile(r"(?<=[。！？!?；;])\s*")
NUM_RE = re.compile(r"\d+(?:\.\d+)?%?")
# 阿拉伯数字年份，避免把 1950s 里的 1950 当成年份之外的东西
YEAR_RE = re.compile(r"(?<!\d)(1[89]\d{2}|20\d{2})(?!\d)")
# 资料缺项时允许的显式标注；出现这些标记的句子免除支持度检查
PENDING_MARKS = ("待确认", "待客户补充", "待补", "需客户补充", "资料未提供", "资料未覆盖")
REQUIRED_CARD_FIELDS = ("item_code", "location", "card_title", "narration", "question", "answer")


@dataclass
class Rules:
    """可调规则集。RSI 改进候选本质就是提出这份对象的新版本。"""

    min_quote_len: int = 8
    support_min_lcs: int = 6
    support_min_sentence: int = 10
    narration_min: int = 120
    narration_max: int = 240
    require_pending_mark: bool = True
    require_numbers_supported: bool = True
    version: str = "rules-v1"

    def as_dict(self) -> dict:
        return {
            "min_quote_len": self.min_quote_len,
            "support_min_lcs": self.support_min_lcs,
            "support_min_sentence": self.support_min_sentence,
            "narration_min": self.narration_min,
            "narration_max": self.narration_max,
            "require_pending_mark": self.require_pending_mark,
            "require_numbers_supported": self.require_numbers_supported,
            "version": self.version,
        }


def sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text or "") if s.strip()]


def longest_common_substring(a: str, b: str) -> int:
    """返回最长公共连续子串长度。用于判断句子是否有原文支撑。"""
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


def _norm(text: str) -> str:
    # 全角数字/标点归一，避免校验被排版差异误伤
    table = str.maketrans("０１２３４５６７８９％", "0123456789%")
    return (text or "").translate(table)


def gate_item_sources(items: list[dict]) -> dict[str, dict]:
    return {str(it["item_code"]): it for it in items}


def run_gates(items: list[dict], draft: dict, rules: Rules | None = None) -> dict:
    """对一份草稿执行全部门。返回 passed / checks / total / issues / details。"""
    rules = rules or Rules()
    index = gate_item_sources(items)
    issues: list[str] = []
    details: list[dict] = []
    checks = 0
    total = 0

    def check(ok: bool, code: str, message: str, item_code: str | None = None) -> None:
        nonlocal checks, total
        total += 1
        if ok:
            checks += 1
        else:
            issues.append(message)
        details.append({"gate": code, "ok": ok, "message": message, "item_code": item_code})

    cards = draft.get("cards") if isinstance(draft, dict) else None
    check(isinstance(cards, list) and bool(cards), "structure", "内容必须包含至少一张卡片")
    cards = cards if isinstance(cards, list) else []

    # 覆盖门：一张卡对应一个展项，不多不少
    codes = [str(c.get("item_code", "")) for c in cards if isinstance(c, dict)]
    check(
        len(cards) == len(index) and sorted(codes) == sorted(index),
        "coverage",
        "覆盖门：卡片数 %d 与展项数 %d 不一致，或展项编号不匹配（期望 %s，实际 %s）"
        % (len(cards), len(index), sorted(index), sorted(codes)),
    )

    for position, card in enumerate(cards, 1):
        if not isinstance(card, dict):
            check(False, "structure", "第 %d 张卡不是对象" % position)
            continue
        code = str(card.get("item_code", ""))
        item = index.get(code)
        label = "第 %d 张卡（%s）" % (position, code or "未标展项")

        missing = [f for f in REQUIRED_CARD_FIELDS if not str(card.get(f, "")).strip()]
        check(not missing, "structure", "%s 缺少必填字段：%s" % (label, "、".join(missing)) if missing else "%s 字段完整" % label, code)
        if item is None:
            check(False, "cross_talk", "%s 的展项编号 %r 不在本任务展项清单中" % (label, code), code)
            continue

        source = _norm(item.get("source_text", ""))
        narration = _norm(str(card.get("narration", "")))

        # 串台门 + 引用逐字门
        citations = card.get("citations") or []
        quotes: list[str] = []
        verbatim_ok = False
        for cit in citations:
            if not isinstance(cit, dict):
                continue
            quote = _norm(str(cit.get("source_quote", ""))).strip()
            if len(quote) < rules.min_quote_len:
                check(False, "citation_verbatim", "%s 的出处过短（%d 字，要求 ≥%d）" % (label, len(quote), rules.min_quote_len), code)
                continue
            if quote in source:
                checks += 1
                total += 1
                verbatim_ok = True
                quotes.append(quote)
            else:
                check(False, "cross_talk", "%s 的出处「%s」不在该展项资料中（串台或已失效）" % (label, quote[:24]), code)
        check(bool(citations) and verbatim_ok, "citation_verbatim", "%s 没有可在本展项资料中逐字定位的出处" % label, code)

        # 支持度门：讲解的每一句都要有原文支撑，或显式标注待确认
        unsupported: list[str] = []
        support_probe = " ".join(quotes) + " " + source
        for sentence in sentences(narration):
            if len(sentence) < rules.support_min_sentence:
                continue
            if any(mark in sentence for mark in PENDING_MARKS):
                continue
            if longest_common_substring(sentence, support_probe) < rules.support_min_lcs:
                unsupported.append(sentence[:30])
        if unsupported and rules.require_pending_mark:
            check(
                False,
                "support",
                "%s 有 %d 句无原文支撑且未标注待确认：%s" % (label, len(unsupported), " / ".join(unsupported)),
                code,
            )
        else:
            check(True, "support", "%s 支持度通过" % label, code)

        # 数字门：讲解里的数字必须在出处或原文出现
        if rules.require_numbers_supported:
            bad_numbers = [n for n in NUM_RE.findall(narration) if n not in support_probe]
            check(
                not bad_numbers,
                "numbers",
                "%s 出现原文没有的数字：%s" % (label, "、".join(bad_numbers)) if bad_numbers else "%s 数字均可在原文找到" % label,
                code,
            )
            bad_years = [y for y in YEAR_RE.findall(narration) if y not in support_probe]
            check(
                not bad_years,
                "numbers",
                "%s 出现原文没有的年份：%s" % (label, "、".join(bad_years)) if bad_years else "%s 年份均可在原文找到" % label,
                code,
            )

        # 长度门：30–60 秒约 120–240 字
        length = len(str(card.get("narration", "")))
        check(
            rules.narration_min <= length <= rules.narration_max,
            "length",
            "%s 讲解 %d 字，超出 %d–%d 字（约 30–60 秒）"
            % (label, length, rules.narration_min, rules.narration_max)
            if not (rules.narration_min <= length <= rules.narration_max)
            else "%s 讲解长度合规（%d 字）" % (label, length),
            code,
        )

    return {
        "passed": not issues,
        "checks": checks,
        "total_checks": total,
        "issues": issues,
        "details": details,
        "rules_version": rules.version,
    }


# 固定回归集：用于 RSI 改进前后的对照。每条是"输入 + 期望判定"。
GOLDEN_CASES = [
    {
        "name": "合规草稿应通过",
        "expect": {"passed": True},
        "items": [{"item_code": "A", "source_name": "资料A", "source_text": "展项A的展品是一台一九五八年的机床，由市机械厂捐赠，用于演示车削加工的基本原理。"}],
        "draft": {
            "cards": [
                {
                    "item_code": "A",
                    "location": "展项A",
                    "card_title": "一九五八年的机床",
                    "narration": "这是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理，观众可以观察刀具与工件之间的相对运动，理解金属是如何被逐步切削成型的。",
                    "question": "这台机床是哪一年制造的？",
                    "answer": "一九五八年，由市机械厂捐赠。",
                    "citations": [{"source_quote": "展项A的展品是一台一九五八年的机床，由市机械厂捐赠", "source_name": "资料A"}],
                }
            ]
        },
    },
    {
        "name": "编造年份应被拦截",
        "expect": {"passed": False},
        "items": [{"item_code": "A", "source_name": "资料A", "source_text": "展项A的展品是一台机床，由市机械厂捐赠，用于演示车削加工的基本原理。"}],
        "draft": {
            "cards": [
                {
                    "item_code": "A",
                    "location": "展项A",
                    "card_title": "机床",
                    "narration": "这是一台1958年制造的机床，由市机械厂捐赠，用于演示车削加工的基本原理以及金属切削的过程，观众可以看到刀具的运动轨迹。",
                    "question": "这台机床是哪一年制造的？",
                    "answer": "1958年。",
                    "citations": [{"source_quote": "展项A的展品是一台机床，由市机械厂捐赠", "source_name": "资料A"}],
                }
            ]
        },
    },
    {
        "name": "串台引用应被拦截",
        "expect": {"passed": False},
        "items": [
            {"item_code": "A", "source_name": "资料A", "source_text": "展项A展示城市街巷的老照片，照片由市档案馆提供。"},
            {"item_code": "B", "source_name": "资料B", "source_text": "展项B展示复原的木制招牌，依据本地工匠口述制作。"},
        ],
        "draft": {
            "cards": [
                {
                    "item_code": "A",
                    "location": "展项A",
                    "card_title": "老照片",
                    "narration": "展项A展示城市街巷的老照片，照片由市档案馆提供，记录了二十世纪五十年代的街市生活，可以让观众看到当年的招牌和店铺形态。",
                    "question": "照片由谁提供？",
                    "answer": "市档案馆。",
                    "citations": [{"source_quote": "展项B展示复原的木制招牌，依据本地工匠口述制作", "source_name": "资料B"}],
                }
            ]
        },
    },
]


def run_golden(rules: Rules | None = None) -> dict:
    """在固定回归集上跑全部门，返回逐条结果与通过率。"""
    results = []
    passed = 0
    for case in GOLDEN_CASES:
        report = run_gates(case["items"], case["draft"], rules)
        ok = report["passed"] == case["expect"]["passed"]
        passed += 1 if ok else 0
        results.append(
            {
                "name": case["name"],
                "expected_passed": case["expect"]["passed"],
                "actual_passed": report["passed"],
                "matched": ok,
                "issues": report["issues"],
            }
        )
    return {"total": len(results), "matched": passed, "results": results}
