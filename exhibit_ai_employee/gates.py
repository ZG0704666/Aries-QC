"""固定回归集。

这是对 app.validate_draft 的回归测试，不是第二套质量门。
设计原则：
1. 只有一套门——app.validate_draft。这里只给它喂输入、断言判定结果。
2. 每条用例是"输入 + 期望判定"，改动规则后必须全部仍然通过，否则视为回归。
3. 用例同时覆盖"应当拦下"和"不应误伤"两个方向，防止为了过测试而放宽门。

运行：
    python gates.py          # 命令行自检，返回非零表示有回归
"""

from __future__ import annotations

import json
import sys


def _item(code: str, text: str, name: str | None = None) -> dict:
    return {"exhibit_id": code, "source_name": name or ("资料" + code), "source_text": text}


def _card(code: str, narration: str, quote: str, name: str | None = None, **extra) -> dict:
    """构造一张卡。

    facts 按讲解的每个分句生成，并让每条 claim 用它自己整句作 source_quote——
    这正是"每句都有出处"的应有形态：claim 必须包含在 source_quote 里，
    而 source_quote 必须是原文片段。合规草稿的讲解直接取原文，因此天然满足；
    篡改用例会因 source_quote 不在原文中而正确失败。
    """
    source_name = name or ("资料" + code)
    sentences = [s.strip() for s in narration.split("。") if len(s.strip()) >= 8]
    # claim 不加句号：质量门要求 claim 必须是 source_quote 的子串，而 source_quote
    # 是原文片段。多一个句号就会对不上，这里保持与原文完全一致。
    facts = [
        {"claim": s, "source_name": source_name, "source_quote": s}
        for s in sentences
    ]
    if not facts:
        facts = [{"claim": quote, "source_name": source_name, "source_quote": quote}]
    card = {
        "exhibit_id": code,
        "location": "展项 " + code,
        "card_title": "回归用例卡 " + code,
        "narration": narration,
        "no_target_prompt": "您可以选择一个展项，听它的介绍。",
        "multi_target_prompt": "检测到多个候选，请在屏幕上选择要听的展项。",
        "question": "资料中记载了什么？",
        "answer": quote[:120],
        "facts": facts,
        "citations": [{"source_name": source_name, "source_quote": quote}],
    }
    card.update(extra)
    return card


# 三个信息充足的展项资料，供多数用例复用。每份 4 句、约 120–150 字，
# 足以支撑一段 30–60 秒讲解。
BASE_A = (
    "本展项展出一件西周青铜鼎，通高约三十厘米，器身饰有饕餮纹。"
    "该鼎于二十世纪八十年代在本地窖藏出土，现藏于市博物馆。"
    "鼎内壁铸有铭文，记录了当时的祭祀活动，是研究本地礼制的重要实物。"
    "鼎的通高与腹部形制，是判断同类器物年代与用途的重要依据。"
    "鼎足为柱状，足根饰有兽面，这类做法在西周早期较为常见。"
)
BASE_B = (
    "本展项展示的陶罐属于新石器时代晚期，采用泥条盘筑法制成，表面留有绳纹。"
    "陶罐出土于城郊遗址，器形完整，用于储存粮食。"
    "陶罐的发现说明当时已有稳定的农业定居生活，也为研究当时的聚落形态提供了实物依据。"
    "陶罐的腹部与口沿形制，反映了当时的制陶技术与日常使用方式。"
)
BASE_C = (
    "本展项展示的织物残片为汉代丝织品，采用平纹织造，残片出土于本地墓葬，颜色已褪。"
    "织物上的纹样显示了当时的纺织工艺水平，也反映本地与外地的手工业交流。"
    "这类残片常见于同一时期的墓葬，是研究纺织技术传播的重要材料。"
    "残片的织造密度与纹样组织，也是判断产地与工艺传统的主要线索。"
)

QUOTE_A = "本展项展出一件西周青铜鼎，通高约三十厘米，器身饰有饕餮纹"
QUOTE_B = "本展项展示的陶罐属于新石器时代晚期，采用泥条盘筑法制成，表面留有绳纹"
QUOTE_C = "本展项展示的织物残片为汉代丝织品，采用平纹织造，残片出土于本地墓葬"

# 合规讲解直接取资料原文（这正是"每句都有出处"的应有形态）。
NARR_A = BASE_A
NARR_B = BASE_B
NARR_C = BASE_C


def _base_sources() -> dict:
    return {"A": _item("A", BASE_A), "B": _item("B", BASE_B), "C": _item("C", BASE_C)}


CASES = [
    {
        "name": "合规草稿应通过（不得误伤正常资料）",
        "expect_passed": True,
        "sources": _base_sources,
        "draft": {
            "cards": [
                _card("A", NARR_A, QUOTE_A),
                _card("B", NARR_B, QUOTE_B),
                _card("C", NARR_C, QUOTE_C),
            ]
        },
    },
    {
        "name": "编造阿拉伯数字年份应被拦",
        "expect_passed": False,
        "sources": lambda: {
            "A": _item("A", "本展项展出一台机床，由市机械厂捐赠，用于演示车削加工的基本原理。"),
            "B": _item("B", BASE_B),
            "C": _item("C", BASE_C),
        },
        "draft": {
            "cards": [
                _card(
                    "A",
                    "本展项展出一台1958年制造的机床，由市机械厂捐赠，用于演示车削加工的基本原理以及金属切削的过程，观众可以看到刀具的运动轨迹与工件表面变化。",
                    "本展项展出一台机床，由市机械厂捐赠",
                ),
                _card("B", NARR_B, QUOTE_B),
                _card("C", NARR_C, QUOTE_C),
            ]
        },
    },
    {
        "name": "编造中文数字年份应被拦（审计 #1）",
        "expect_passed": False,
        "sources": lambda: {
            "A": _item("A", "本展项展出一台一九五八年的机床，由市机械厂捐赠，用于演示车削加工的基本原理。"),
            "B": _item("B", BASE_B),
            "C": _item("C", BASE_C),
        },
        "draft": {
            "cards": [
                _card(
                    "A",
                    "本展项展出一台一九五零年的机床，由市机械厂捐赠，用于演示车削加工的基本原理以及金属切削的过程，观众可以看到刀具的运动轨迹与工件表面变化。",
                    "本展项展出一台一九五八年的机床，由市机械厂捐赠",
                ),
                _card("B", NARR_B, QUOTE_B),
                _card("C", NARR_C, QUOTE_C),
            ]
        },
    },
    {
        "name": "编造中文专名应被拦（审计 #1）",
        "expect_passed": False,
        "sources": lambda: {
            "A": _item("A", "本展项展出一台一九五八年的机床，由市机械厂捐赠，用于演示车削加工的基本原理。"),
            "B": _item("B", BASE_B),
            "C": _item("C", BASE_C),
        },
        "draft": {
            "cards": [
                _card(
                    "A",
                    "本展项展出一台一九五八年的机床，由郑州机床厂捐赠，用于演示车削加工的基本原理以及金属切削的过程，观众可以看到刀具的运动轨迹与工件表面变化。",
                    "本展项展出一台一九五八年的机床，由市机械厂捐赠",
                ),
                _card("B", NARR_B, QUOTE_B),
                _card("C", NARR_C, QUOTE_C),
            ]
        },
    },
    {
        "name": "串台引用（引用了别的展项的资料）应被拦",
        "expect_passed": False,
        "sources": _base_sources,
        "draft": {
            "cards": [
                _card("A", NARR_A, QUOTE_B, name="资料B"),
                _card("B", NARR_B, QUOTE_B),
                _card("C", NARR_C, QUOTE_C),
            ]
        },
    },
    {
        "name": "完全没有出处应被拦",
        "expect_passed": False,
        "sources": _base_sources,
        "draft": {
            "cards": [
                _card("A", NARR_A, QUOTE_A, citations=[], facts=[]),
                _card("B", NARR_B, QUOTE_B),
                _card("C", NARR_C, QUOTE_C),
            ]
        },
    },
    {
        "name": "讲解超长（超过 240 字）应被拦",
        "expect_passed": False,
        "sources": _base_sources,
        "draft": {
            "cards": [
                _card("A", NARR_A * 3, QUOTE_A),
                _card("B", NARR_B, QUOTE_B),
                _card("C", NARR_C, QUOTE_C),
            ]
        },
    },
    {
        "name": "漏掉一个展项（覆盖门）应被拦",
        "expect_passed": False,
        "sources": _base_sources,
        "draft": {"cards": [_card("A", NARR_A, QUOTE_A), _card("B", NARR_B, QUOTE_B)]},
    },
    {
        "name": "资料缺料时不得生成可交付内容",
        "expect_passed": False,
        "sources": lambda: {
            "A": _item("A", "展项 A 未提供任何事实参数，待补。"),
            "B": _item("B", BASE_B),
            "C": _item("C", BASE_C),
        },
        "draft": {
            "cards": [
                _card("A", "展项A未提供任何事实参数，待补。", "展项 A 未提供任何事实参数，待补。"),
                _card("B", NARR_B, QUOTE_B),
                _card("C", NARR_C, QUOTE_C),
            ]
        },
    },
    {
        "name": "来源冲突未解决时不得通过",
        "expect_passed": False,
        "sources": lambda: {
            "A": _item("A", BASE_A),
            "B": _item(
                "B",
                "据资料甲记载，展项 B 的陶罐为一八五零年本地工匠烧制。据资料乙记载，该陶罐实际烧制于一八七零年前后，器表留有绳纹。两批资料对烧制年代说法不同。",
            ),
            "C": _item("C", BASE_C),
        },
        "draft": {
            "cards": [
                _card("A", NARR_A, QUOTE_A),
                _card("B", NARR_B, QUOTE_B),
                _card("C", NARR_C, QUOTE_C),
            ]
        },
    },
    {
        "name": "规范展签体（短句、信息完整）不得误判缺料",
        "expect_passed": None,  # 只断言"不被缺料门拦"，其余门可不过
        "sources": lambda: {
            "A": _item("A", "青铜鼎。西周时期铸造。通高三十厘米，腹深十八厘米。器身饰饕餮纹，双耳立耳。本地窖藏出土。现藏市博物馆。"),
            "B": _item("B", "陶罐一件。新石器时代晚期。泥条盘筑法制成。表面留有绳纹。器形完整，用于储存粮食。城郊遗址出土。"),
            "C": _item("C", "织物残片。汉代丝织品。平纹织造。颜色已褪。出土于本地墓葬。纹样显示当时纺织工艺水平。"),
        },
        "draft": {"cards": []},
        "forbid_issue_contains": "缺料",
    },
]


def run(verbose: bool = True) -> dict:
    """对 app.validate_draft 跑全部用例。返回逐条结果与通过情况。"""
    import app  # 延迟导入，避免循环依赖

    results = []
    matched = 0
    for case in CASES:
        sources = case["sources"]() if callable(case["sources"]) else case["sources"]
        report = app.validate_draft(sources, json.loads(json.dumps(case["draft"])))
        issues = report.get("issues", [])

        if case["expect_passed"] is None:
            forbid = case.get("forbid_issue_contains", "")
            ok = not any(forbid in issue for issue in issues)
            detail = "不应出现含「%s」的阻断项" % forbid
        else:
            ok = report["passed"] == case["expect_passed"]
            detail = "期望 passed=%s，实际 passed=%s" % (case["expect_passed"], report["passed"])

        matched += 1 if ok else 0
        results.append(
            {
                "name": case["name"],
                "matched": ok,
                "detail": detail,
                "issues": issues,
                "checks": "%s / %s" % (report.get("checks"), report.get("total_checks")),
            }
        )
        if verbose:
            print(("  PASS  " if ok else "  FAIL  ") + case["name"])
            if not ok:
                print("        " + detail)
                for issue in issues[:6]:
                    print("        - " + issue)
    return {"total": len(results), "matched": matched, "results": results}


if __name__ == "__main__":
    summary = run()
    print("\n回归结果：%d / %d 通过" % (summary["matched"], summary["total"]))
    sys.exit(0 if summary["matched"] == summary["total"] else 1)
