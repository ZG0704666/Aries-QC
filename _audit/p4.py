import json,io,sys
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
sys.path.insert(0,'.')
import app_frozen as app

print("### 【G1】误检：同一展项两件不同器物，各有一个年份 → 被判为冲突？")
s={"A":{"source_name":"s","source_text":"展项A陈列一号青铜鼎，铸造于一九五八年。展项A同时陈列二号陶罐，出土于一九八零年。两件器物均保存良好。"}}
print("  detect conflicts =",json.dumps(app.detect_source_issues(s)[1],ensure_ascii=False,indent=1))

print("\n### 【G2】误检：正常的两句含不同数字（尺寸），LCS>=6")
s2={"B":{"source_name":"s","source_text":"灰陶罐乙器高二十厘米，口沿直径十二厘米。灰陶罐乙表面呈灰褐色，为轮制陶器。"}}
print("  detect conflicts =",json.dumps(app.detect_source_issues(s2)[1],ensure_ascii=False))

print("\n### 【G3】漏检：任意一句未被 facts 覆盖的伪造句")
srcA="展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理，观众可以观察刀具与工件之间的相对运动。本展项陈列在展厅东侧，便于观众近距离观看。"
sources={"A":{"source_name":"资料A","source_text":srcA},"B":{"source_name":"资料B","source_text":"展项B展示灰陶罐乙。器高二十厘米。表面灰褐色。轮制陶器。"},"C":{"source_name":"资料C","source_text":"展项C展示织物残片丙。麻纤维。出土本地。平纹织造。"}}
pad="这段补充文字用于把讲解长度控制在规定区间内，并在结尾说明本展项的陈列位置与观众参观路线安排，便于团队现场核对。请观众按指引顺序参观，保持安静，不要触摸展品与展柜，谢谢配合。"
def card(e,n,q,c):
    return {"exhibit_id":e,"location":"展项"+e,"card_title":"T"+e,"narration":n,"no_target_prompt":"x","multi_target_prompt":"y",
            "question":"q","answer":"a","facts":[{"claim":c,"source_name":"资料"+e,"source_quote":q}],
            "citations":[{"source_name":"资料"+e,"source_quote":q}]}
nA="展项A的展品是一台一九五零年的机床，由郑州机床厂捐赠，国家级文物。"+pad
d={"missing_materials":[],"conflicts":[],"cards":[
 card("A",nA,"它用于演示车削加工的基本原理","它用于演示车削加工的基本原理"),
 card("B","展项B展示灰陶罐乙。器高二十厘米。"+pad,"器高二十厘米","器高二十厘米"),
 card("C","展项C展示织物残片丙。麻纤维。"+pad,"麻纤维","麻纤维")]}
r=app.validate_draft(sources,d)
print("  passed =",r["passed"],"| 伪造句'一九五零年''郑州机床厂''国家级文物'均未覆盖却通过:",r["passed"])
print("  issues:",r["issues"])
