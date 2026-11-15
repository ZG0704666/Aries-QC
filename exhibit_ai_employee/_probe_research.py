# -*- coding: utf-8 -*-
"""联网调研当来源：离线验证（不调模型、不联网）。

验的是「知名作品没有上传资料也能起草」这条链路的底座：
调研摘录能不能当来源、引用能不能逐字核对、展项清单能不能兜住没有资料的项目。

    python _probe_research.py
"""
import json
import os
import shutil
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="studio_research_")
for key in ("STUDIO_ACCESS_TOKEN", "ACCESS_TOKEN", "STUDIO_ALLOW_NO_AUTH"):
    os.environ.pop(key, None)
os.environ["STUDIO_DB"] = os.path.join(TMP, "studio.sqlite3")
os.environ["STUDIO_AUDIO_DIR"] = os.path.join(TMP, "audio")

import studio_server as S  # noqa: E402  模块级读取环境变量，必须在设完之后导入

PAGE = """《蒙娜丽莎》（意大利语：La Gioconda）是列奥纳多·达·芬奇创作的木板油画，约创作于 1503 年至 1506 年。
画作现藏于法国巴黎卢浮宫，是该馆参观人数最多的展品之一。
画中人物普遍被认为是佛罗伦萨商人弗朗切斯科·德尔·乔孔多的妻子丽莎·盖拉尔迪尼。
达·芬奇在这幅画上使用了晕涂法，用极薄的透明油彩层层叠加，形成柔和的轮廓过渡。
画作曾于 1911 年被盗，两年后在佛罗伦萨被找回。"""

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print("%s %s%s" % ("✓" if ok else "✗", name, ("  — " + detail) if detail else ""))


def main():
    S.initialize()
    project = S.create_project(name="蒙娜丽莎", audience="亲子观众", language="中文",
                               brief="一件作品的单展项讲解")
    project = S.load(project["id"])

    check("空项目：没有可起草的展项", S.exhibit_units(project) == [],
          "exhibit_units=%r" % (S.exhibit_units(project),))

    # 1) 存一个调研网页，模型给的句子必须原样命中
    web_id, kept, dropped = S.add_research(
        project, "https://www.louvre.fr/example/mona-lisa.html", PAGE,
        title="蒙娜丽莎 · 卢浮宫",
        quotes=["画中人物普遍被认为是佛罗伦萨商人弗朗切斯科·德尔·乔孔多的妻子丽莎·盖拉尔迪尼。",
                "这句是我编的，页面上没有。"])
    check("登记网页返回编号", web_id == "WEB-001", web_id)
    check("逐字命中的摘录留下", kept >= 1, "kept=%d" % kept)
    check("页面上找不到的句子被丢掉", dropped == 1, "dropped=%d" % dropped)

    quotes = project["research"][0]["quotes"]
    check("摘录编号形如 WEB-001·Q001", quotes[0]["id"] == "WEB-001·Q001", quotes[0]["id"])
    for quote in quotes:
        if S._norm_space(quote["text"]) not in S._norm_space(PAGE):
            check("摘录都在正文里", False, quote["id"])
            break
    else:
        check("每条摘录都能在页面正文里原样找到", True, "共 %d 条" % len(quotes))

    # 2) 来源集合与展项清单
    ids = [item["id"] for item in S.all_sources(project)]
    check("网页摘录进入来源集合", ids == ["WEB-001"], str(ids))
    units = S.exhibit_units(project)
    check("没资料也能给出展项（按项目名兜底）",
          len(units) == 1 and units[0]["title"] == "蒙娜丽莎", str(units))

    text, data = S.run_agent_tool(project, "plan_exhibits", {"titles": ["蒙娜丽莎"]}, {})
    check("plan_exhibits 落库", [item["title"] for item in project.get("plan") or []] == ["蒙娜丽莎"], text)
    units = S.exhibit_units(project)
    check("展项清单生效", len(units) == 1 and units[0]["id"] == "EX01", str(units))

    # 3) 引用核对：逐字才算通过，改写必须被拦
    good = quotes[1]["text"]
    exhibit = {
        "id": "EX01", "title": "蒙娜丽莎", "source_refs": ["WEB-001"],
        "facts": [
            {"id": "F-001", "text": "现藏巴黎卢浮宫", "quote": quotes[0]["text"], "source_ref": "WEB-001·Q001"},
            {"id": "F-002", "text": "用了晕涂法", "quote": good, "source_ref": "WEB-001"},
        ],
        "main": {"text": "主讲解" * 20}, "simplified": {"text": "一句话"},
        "followups": [{"q": "在哪", "a": "卢浮宫"}], "fallback": [{"q": "门票", "a": "资料未覆盖"}],
    }
    exhibit = S.verify(project, exhibit)
    check("网页摘录引用通过核对", exhibit["verified"], "verified=%r" % exhibit["verified"])
    check("来源级编号被补全成段落级",
          exhibit["facts"][1]["source_ref"].startswith("WEB-001·Q"),
          exhibit["facts"][1]["source_ref"])

    bad = dict(exhibit)
    bad["facts"] = [{"id": "F-003", "text": "改写过的", "quote": "蒙娜丽莎是达芬奇画的一幅油画",
                     "source_ref": "WEB-001·Q001"}]
    bad = S.verify(project, bad)
    check("改写过的引用被拦下", not bad["verified"] and bad["issues"], (bad["issues"] or [{}])[0].get("title", ""))

    # 4) 自测门
    project["exhibits"] = [exhibit]
    project["tests"] = S.content_tests(project)
    gates = {item["name"]: item["status"] for item in project["tests"]}
    check("覆盖完整（按展项清单算，不是按资料）", gates.get("覆盖完整") == "passed", str(gates.get("覆盖完整")))
    check("引文逐字可定位", gates.get("引文逐字可定位") == "passed")
    check("无跨展项串台（网页来源也算自家）", gates.get("无跨展项串台") == "passed")

    # 5) 没有依据时如实拒绝
    empty = S.create_project(name="空项目", audience="亲子观众", language="中文")
    empty = S.load(empty["id"])
    text, data = S.run_agent_tool(empty, "start_generation", {}, {})
    check("没有来源时 start_generation 不排期", data is None and "没有依据" in text, text[:40])
    check("空项目自测不满覆盖完整",
          {i["name"]: i["status"] for i in S.content_tests(empty)}.get("覆盖完整") == "failed")

    passed = sum(1 for _, ok, _ in results if ok)
    print("\n%d/%d 通过" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
