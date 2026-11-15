import json,io,sys,re
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
sys.path.insert(0,'.')
import app_frozen as app
print("### 【N1】阿拉伯数字门是子串判断 -> 可被更长数字'包含'")
srcA="展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理。本展项陈列在展厅东侧，便于观众近距离观看。"
sources={"A":{"source_name":"资料A","source_text":srcA},"B":{"source_name":"资料B","source_text":"展项B展示灰陶罐乙。器高二十厘米。表面灰褐色。轮制陶器，出土于本地遗址。"},"C":{"source_name":"资料C","source_text":"展项C展示织物残片丙。麻纤维。出土本地遗址。平纹织造，纹理清晰。"}}
pad="这段补充文字用于把讲解长度控制在规定区间内，并在结尾说明本展项的陈列位置与观众参观路线安排，便于团队现场核对。请观众按指引顺序参观，保持安静。"
def card(e,n,q,c):
    return {"exhibit_id":e,"location":"L"+e,"card_title":"T"+e,"narration":n,"no_target_prompt":"x","multi_target_prompt":"y",
            "question":"q","answer":"a","facts":[{"claim":c,"source_name":"资料"+e,"source_quote":q}],
            "citations":[{"source_name":"资料"+e,"source_quote":q}]}
# 伪造数字 195（原文只有 1958）—— 195 是 "1958" 的子串?
print("  '195' in 原文:", "195" in srcA, "| '19' in 原文:", "19" in srcA)
nA="这台机床的编号为19号，制造于一九五八年。"+pad
d={"missing_materials":[],"conflicts":[],"cards":[
 card("A",nA,"它用于演示车削加工的基本原理","它用于演示车削加工的基本原理"),
 card("B","展项B展示灰陶罐乙。器高二十厘米。"+pad+"本展项保存状况良好。","器高二十厘米","器高二十厘米"),
 card("C","展项C展示织物残片丙。麻纤维。"+pad+"本展项采用平纹织造。","麻纤维","麻纤维")]}
r=app.validate_draft(sources,d)
print("  len:",[len(x) for x in (nA,)])
print("  passed:",r["passed"])
for i in r["issues"]: print("   -",i)
print("  数字门是否拦下伪造'19号':", any("19" in i for i in r["issues"]))
