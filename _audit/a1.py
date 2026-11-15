import json,io,sys
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
sys.path.insert(0,'.')
import app_frozen as app

# 复现 acceptance.py 的 T4/T5 判据
srcA="展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理。本展项陈列在展厅东侧。"
print("### acceptance T4 判据 vs 服务端返回")
print("  T4 期望: code==200 且 draft.missing_materials 含 A 且 无 A 卡片")
print("  服务端实际: 缺料时 code=409, 顶层 missing_materials, 且 draft=None(无 draft 键)")
print("  => acceptance:T4 ok = code==200 (False) -> 恒 FAIL")

print("\n### acceptance T5 判据 vs 服务端返回")
print("  T5 期望: code==200 且 draft.conflicts 含 C 且含'麻纤维''棉纤维'")
print("  服务端实际: 冲突时 code=409, 顶层 conflicts, 无 draft")
print("  => 恒 FAIL")

print("\n### T8 判据: 期望 blocked 且 review>=400")
print("  服务端 blocked 时确实 409 且 approval_allowed False -> 可 PASS")
