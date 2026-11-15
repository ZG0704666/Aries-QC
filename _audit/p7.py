import json,io,sys
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
sys.path.insert(0,'.')
import app_frozen as app
print("### 【N2】阿拉伯数字子串包含：原文'1958' → 讲解'195'或'1'可通过")
srcA="展项A的展品是一台1958年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理。本展项陈列在展厅东侧，便于观众近距离观看。"
print("  '195' in src:", "195" in srcA, "| '1' in src:", "1" in srcA)
print("  数字门只判 number not in allowed_text -> '195' 会通过")

print("\n### 【N3】20厘米 -> 讲解写'2厘米'也通过（'2'是'20'子串）")
srcB="展项B展示灰陶罐乙，器高20厘米，口沿直径12厘米。表面呈灰褐色。本展项保存状况良好。"
print("  '2厘米' 的 '2' in src:", "2" in srcB, "-> 伪造尺寸可过数字门")

print("\n### 【N4】实体门：'B' 'A' 等单字母展项编号被当作实体，但要 in allowed_text")
print("  实体白名单只减 DEMO/AI/TTS/JSON；'B'若不在原文会被判实体 -> 误报")
sources={"A":{"source_name":"资料A","source_text":"展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理。本展项陈列在展厅东侧。"},
"B":{"source_name":"资料B","source_text":"展项B展示灰陶罐乙。器高二十厘米。表面灰褐色。轮制陶器，出土于本地遗址。"},
"C":{"source_name":"资料C","source_text":"展项C展示织物残片丙。麻纤维。出土本地遗址。平纹织造，纹理清晰。"}}
pad="这段补充文字用于把讲解长度控制在规定区间内，并在结尾说明本展项的陈列位置与观众参观路线安排，便于团队现场核对。请观众按指引顺序参观，保持安静。"
def card(e,n,q,c):
    return {"exhibit_id":e,"location":"L"+e,"card_title":"T"+e,"narration":n,"no_target_prompt":"x","multi_target_prompt":"y",
            "question":"q","answer":"a","facts":[{"claim":c,"source_name":"资料"+e,"source_quote":q}],
            "citations":[{"source_name":"资料"+e,"source_quote":q}]}
# A 卡讲解提到 "B 展项" —— 原文没有 B
nA="本展项A的展品是一台一九五八年的机床。请注意与 B 展项的对比。"+pad
d={"missing_materials":[],"conflicts":[],"cards":[
 card("A",nA,"它用于演示车削加工的基本原理","它用于演示车削加工的基本原理"),
 card("B","展项B展示灰陶罐乙。器高二十厘米。"+pad+"本展项保存状况良好。","器高二十厘米","器高二十厘米"),
 card("C","展项C展示织物残片丙。麻纤维。"+pad+"本展项采用平纹织造。","麻纤维","麻纤维")]}
r=app.validate_draft(sources,d)
print("  passed:",r["passed"])
for i in r["issues"]: print("   -",i)
