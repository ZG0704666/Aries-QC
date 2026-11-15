import json,io,sys,re
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
sys.path.insert(0,'.')
import app_frozen as app

src={
"A":"展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理，观众可以观察刀具与工件之间的相对运动。本展项陈列在展厅东侧，便于观众近距离观看。",
"B":"展项B展示灰陶罐乙，器高二十厘米，口沿直径十二厘米。表面呈灰褐色，为轮制陶器，出土于本地遗址。本展项保存状况良好，可长期陈列，适合常设展出。",
"C":"展项C展示织物残片丙，纤维鉴定记录为麻纤维。出土于本地遗址，保存状况良好。本展项采用平纹织造，经线与纬线粗细均匀，纹理清晰可辨。"}
sources={k:{"source_name":"资料"+k,"source_text":v} for k,v in src.items()}
print("detect =",json.dumps(app.detect_source_issues(sources),ensure_ascii=False))

def card(eid,narr,quote,claim):
    return {"exhibit_id":eid,"location":"展项"+eid,"card_title":"标题"+eid,"narration":narr,
      "no_target_prompt":"您可以选择一个展项，听它的介绍。","multi_target_prompt":"检测到多个候选，请在屏幕上选择要听的展项。",
      "question":"这是什么？","answer":quote[:40],
      "facts":[{"claim":claim,"source_name":"资料"+eid,"source_quote":quote}],
      "citations":[{"source_name":"资料"+eid,"source_quote":quote}]}

pad="这段补充文字用于把讲解长度控制在规定区间内，并在结尾说明本展项的陈列位置与观众参观路线安排，便于团队现场核对。"+"请观众按指引顺序参观，保持安静，不要触摸展品与展柜，谢谢配合。"
# ★ A 讲解伪造：年份 一九五八→一九五零，捐赠方 市机械厂→郑州机床厂
nA="展项A的展品是一台一九五零年的机床，由郑州机床厂捐赠。它用于演示车削加工的基本原理。本展项陈列在展厅东侧，便于观众近距离观看。"+pad
qA="它用于演示车削加工的基本原理"
nB="展项B展示灰陶罐乙，器高二十厘米，口沿直径十二厘米。表面呈灰褐色，为轮制陶器。"+pad+"本展项保存状况良好，可长期陈列。"
qB="表面呈灰褐色"
nC="展项C展示织物残片丙，纤维鉴定记录为麻纤维。出土于本地遗址，保存状况良好。"+pad+"本展项采用平纹织造。"
qC="出土于本地遗址"
for n in (nA,nB,nC): print("len",len(n))
d={"missing_materials":[],"conflicts":[],"cards":[
  card("A",nA,qA,qA), card("B",nB,qB,qB), card("C",nC,qC,qC)]}
r=app.validate_draft(sources,d)
print("\n★★★ passed =",r["passed"]," checks",r["checks"],"/",r["total_checks"])
for i in r["issues"]: print("  -",i)
print("\n伪造'一九五零年'不在原文:", "一九五零" not in src["A"], "| 伪造'郑州机床厂'不在原文:", "郑州机床厂" not in src["A"])
