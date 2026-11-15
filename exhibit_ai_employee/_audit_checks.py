"""审计脚本：不走接口，直接对 studio_server 的校验与自测逻辑做对抗测试。
每个用例都是一次「故意做错」，期望被测代码能识别。

注意：本脚本会调用 S.seed() 建项目。必须在 import studio_server 之前把
STUDIO_DB 指向临时库，否则每次运行都会往真实的 studio.sqlite3 写入一个空的
auditfix 项目，并因为更新时间最新而被前端 boot() 当成「最近项目」加载。"""
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


def make_project():
    return S.seed(project_id="auditfix")


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


src = S.build_sources([{"name": "a.txt", "text": S.SEED[0]["text"]}])[0]
para = src["paragraphs"][3]["text"]  # 含「当光从一种透明介质斜射入另一种介质时…」

# 1 原文精确引用 → 通过
case("逐字原文引用应通过", True, [base_fact("把一支笔斜插进装水的透明杯子里，从侧面看，水面上下的笔仿佛断成了两截。", "SRC-001·P005")])

# 2 改一个字 → 应被拦下或修复成原文后通过（两者都算合理，但必须不能以原引用保留）
project = make_project()
ex = {"id": "EX01", "facts": [base_fact("光在玻璃中约减慢三成，在水中的速度约为真空中的四分之三。", "SRC-001·P003")], "issues": []}
S.verify(project, ex)
f = ex["facts"][0]
kept_wrong = (f["quote"] not in src["paragraphs"][2]["text"]) and f["verified"]
results.append((not kept_wrong, "轻微改写不得以错误文本通过",
                "verified=%s repaired=%s" % (f["verified"], f.get("repaired"))))

# 3 完全编造、资料里没有 → 必须失败
case("编造内容应失败", False, [base_fact("光线在真空中会弯曲成螺旋状。", "SRC-001·P004")])

# 4 跨展项串台：EX01 引用 SRC-002 的内容 → 必须失败
src2 = S.build_sources([{"name": "b.txt", "text": S.SEED[1]["text"]}])[0]
case("跨展项引用应失败", False,
     [base_fact("在 15 摄氏度的空气中，声音的传播速度约为每秒 340 米。", "SRC-002·P004")],
     sources=[src, src2])

# 5 空 quote → 必须失败
case("空引用应失败", False, [base_fact("", "SRC-001·P004")])

# 6 quote 正确但 source_ref 指到别的段落 → 应被纠正到真实段落并记录修复
project = make_project()
ex = {"id": "EX01", "facts": [base_fact("把一支笔斜插进装水的透明杯子里，从侧面看，水面上下的笔仿佛断成了两截。", "SRC-001·P001")], "issues": []}
S.verify(project, ex)
f = ex["facts"][0]
results.append((f["source_ref"].startswith("SRC-001·P005"), "错误段落号应被纠正",
                "最终 ref=%s verified=%s" % (f["source_ref"], f["verified"])))

# ---- 自测内容测试的对抗 ----
project = make_project()
project["exhibits"] = [
    {"id": e["id"], "title": e["title"],
     "facts": [{"id": "F-001", "verified": True, "text": "x", "source_ref": "SRC-001·P001"},
               {"id": "F-002", "verified": True, "text": "y", "source_ref": "SRC-001·P002"}],
     "main": {"text": "主" * 160},
     "followups": [{"q": "问", "a": "答"}], "fallback": [{"q": "问", "a": "答"}],
     "simplified": {"text": "简"},
     "verified": True}
    for e in S.SEED
]
tests = S.content_tests(project)
allpass = all(t["status"] == "passed" for t in tests)
results.append((allpass, "合法内容应全部通过自测", json.dumps([t["name"] for t in tests], ensure_ascii=False)))

# 缺一个展项 → 覆盖门应失败
broken = copy.deepcopy(project)
broken["exhibits"] = broken["exhibits"][:2]
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

print()
fails = 0
for ok, name, detail in results:
    print(("PASS " if ok else "FAIL ") + name + " | " + detail)
    if not ok:
        fails += 1
print("\n%d/%d 通过" % (len(results) - fails, len(results)))
sys.exit(1 if fails else 0)
