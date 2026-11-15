"""审计脚本：不走接口，直接对 studio_server 的校验与自测逻辑做对抗测试。
每个用例都是一次「故意做错」，期望被测代码能识别。

夹具自备：这里不依赖任何内置示例项目（产品里已经不存在内置项目了），
三段资料文本是本脚本自己的测试文本。

注意：必须在 import studio_server 之前把 STUDIO_DB 指向临时库，否则会往真实的
studio.sqlite3 写入 fixture 项目，并因为更新时间最新而被前端 boot() 当成最近项目。"""
import copy
import json
import os
import sys
import tempfile

sys.path.insert(0, ".")

# 隔离数据库：studio_server 在 import 时读取 STUDIO_DB，所以必须抢在 import 之前设置。
_TMP_DB = os.path.join(tempfile.gettempdir(), "studio_audit_checks.sqlite3")
if os.path.exists(_TMP_DB):
    os.remove(_TMP_DB)
os.environ["STUDIO_DB"] = _TMP_DB

import studio_server as S

S.initialize()  # 临时库是空的，需要建表


# ---- 夹具：三段测试资料，每行切一段（build_sources 按换行分段，<8 字丢弃）
MATERIALS = [
    {"name": "审计夹具-光学.txt", "text": "\n".join([
        "光是一种电磁波，可以在真空中传播，不需要介质。",
        "在同一种均匀介质里，光沿直线传播。",
        "光在玻璃中约减慢三成，在水中的速度约为真空中的四分之三。",
        "光线从一种介质进入另一种介质时，传播方向通常会发生改变。",
        "把一支笔斜插进装水的透明杯子里，从侧面看，水面上下的笔仿佛断成了两截。",
        "太阳光经过棱镜后会分成红橙黄绿蓝紫几条色带。",
    ])},
    {"name": "审计夹具-声学.txt", "text": "\n".join([
        "声音是物体的振动通过介质传播形成的波。",
        "声音不能在真空中传播，它必须有介质。",
        "声音在固体中传播一般快于液体，液体中快于气体。",
        "在 15 摄氏度的空气中，声音的传播速度约为每秒 340 米。",
        "用手掌轻触喉咙说话时，能感觉到声带的振动。",
    ])},
    {"name": "审计夹具-色彩.txt", "text": "\n".join([
        "人眼看到颜色，靠的是视网膜上的三种视锥细胞。",
        "红绿蓝三种光按不同比例混合，可以配出大部分颜色。",
        "把红色和绿色颜料混在一起，得到的是暗黄或棕色。",
        "光的三原色相加变亮，颜料三原色相减变暗。",
    ])},
]


def make_project():
    return S.create_project(name="审计夹具项目", materials=MATERIALS, project_id="auditfix")


def base_fact(quote, ref):
    return {"id": "F-001", "text": "t", "quote": quote, "source_ref": ref}


results = []


def case(name, expect_verified, facts, sources=None):
    project = make_project()
    if sources is not None:
        project["sources"] = sources
    exhibit = {"id": "EX01", "facts": facts, "issues": []}
    S.verify(project, exhibit)
    actual = exhibit["verified"]
    ok = actual == expect_verified
    results.append((ok, name, "期望 verified=%s 实际=%s 问题数=%d"
                    % (expect_verified, actual, len(exhibit["issues"]))))
    return exhibit


sources = S.build_sources(MATERIALS)
src, src2 = sources[0], sources[1]
P = lambda n: src["paragraphs"][n - 1]["text"]  # noqa: E731  SRC-001·P00n 的原文

# 1 原文精确引用 → 通过
case("逐字原文引用应通过", True, [base_fact(P(5), "SRC-001·P005")])

# 2 改一个字 → 应被拦下或修复成原文后通过（两者都算合理，但必须不能以原引用保留）
project = make_project()
wrong = P(3).replace("三成", "三份")
ex = {"id": "EX01", "facts": [base_fact(wrong, "SRC-001·P003")], "issues": []}
S.verify(project, ex)
f = ex["facts"][0]
kept_wrong = (f["quote"] not in src["paragraphs"][2]["text"]) and f["verified"]
results.append((not kept_wrong, "轻微改写不得以错误文本通过",
                "verified=%s repaired=%s" % (f["verified"], f.get("repaired"))))

# 3 完全编造、资料里没有 → 必须失败
case("编造内容应失败", False, [base_fact("光线在真空中会弯曲成螺旋状。", "SRC-001·P004")])

# 4 跨展项串台：verify() 只核「这段原文在不在它自己引的那份资料里」，
#   它没有展项归属的概念——所以 EX01 引用 SRC-002 的原文，verify() 会判通过。
#   真正拦串台的是 content_tests 的「无跨展项串台」（按 exhibit.source_refs 比对），
#   这条门在下面的自测对抗段里验证。
project = make_project()
ex = {"id": "EX01", "facts": [base_fact(src2["paragraphs"][3]["text"], "SRC-002·P004")], "issues": []}
project["sources"] = [src, src2]
S.verify(project, ex)
only_if_scope_check = "SRC-002" not in (ex.get("source_refs") or [])
results.append((ex["verified"] is True and only_if_scope_check,
                "verify 不做展项归属判断（串台交给自测门）",
                "verified=%s（引用确实存在于 SRC-002 原文，故通过）" % ex["verified"]))

# 5 空 quote → 必须失败
case("空引用应失败", False, [base_fact("", "SRC-001·P004")])

# 6 quote 正确但 source_ref 指到别的段落 → 应被纠正到真实段落并记录修复
project = make_project()
ex = {"id": "EX01", "facts": [base_fact(P(5), "SRC-001·P001")], "issues": []}
S.verify(project, ex)
f = ex["facts"][0]
results.append((f["source_ref"].startswith("SRC-001·P005"), "错误段落号应被纠正",
                "最终 ref=%s verified=%s" % (f["source_ref"], f["verified"])))

# ---- 自测内容测试的对抗 ----
MAIN = "这是一段用来通过时长门字数控件的测试讲解文本，它需要足够长以便落在八十到四百字的区间内。" * 2
project = make_project()
project["exhibits"] = [
    {"id": m["id"], "title": m["title"], "source_refs": ["SRC-%03d" % (i + 1)],
     "facts": [{"id": "F-001", "verified": True, "text": "x",
                "source_ref": "SRC-%03d·P001" % (i + 1)},
               {"id": "F-002", "verified": True, "text": "y",
                "source_ref": "SRC-%03d·P002" % (i + 1)}],
     "main": {"text": MAIN},
     "followups": [{"q": "问", "a": "答"}], "fallback": [{"q": "问", "a": "答"}],
     "simplified": {"text": "简"},
     "verified": True}
    for i, m in enumerate(project["materials"])
]
tests = S.content_tests(project)
allpass = all(t["status"] == "passed" for t in tests)
results.append((allpass, "合法内容应全部通过自测",
                json.dumps([t["name"] for t in tests], ensure_ascii=False)))

# 缺一个展项 → 覆盖门应失败
broken = copy.deepcopy(project)
broken["exhibits"] = broken["exhibits"][:-1]
t = S.content_tests(broken)
fail = [x["name"] for x in t if x["status"] != "passed"]
results.append(("覆盖完整" in fail, "缺展项时覆盖门应失败", "失败项=" + str(fail)))

# 主讲解过短 → 时长门应失败
short = copy.deepcopy(project)
short["exhibits"][0]["main"]["text"] = "太短"
t = S.content_tests(short)
fail = [x["name"] for x in t if x["status"] != "passed"]
results.append((any("时长" in f for f in fail), "过短讲解时长门应失败", "失败项=" + str(fail)))

# 未核验事实 → 引文门应失败
bad = copy.deepcopy(project)
bad["exhibits"][1]["facts"][0]["verified"] = False
t = S.content_tests(bad)
fail = [x["name"] for x in t if x["status"] != "passed"]
results.append((any("引文" in f for f in fail), "未核验事实引文门应失败", "失败项=" + str(fail)))

# EX01 的事实引用了 EX02 的资料 → 串台门必须失败（这条才是真正拦串台的门）
crossed = copy.deepcopy(project)
crossed["exhibits"][0]["facts"][0]["source_ref"] = "SRC-002·P001"
t = S.content_tests(crossed)
fail = [x["name"] for x in t if x["status"] != "passed"]
results.append(("无跨展项串台" in fail, "跨展项引用应被串台门拦下", "失败项=" + str(fail)))

print()
fails = 0
for ok, name, detail in results:
    print(("PASS " if ok else "FAIL ") + name + " | " + detail)
    if not ok:
        fails += 1
print("\n%d/%d 通过" % (len(results) - fails, len(results)))
sys.exit(1 if fails else 0)
