import json,io,sys
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
sys.path.insert(0,'.')
import app_frozen as app
src={
"A":"展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理，观众可以观察刀具与工件之间的相对运动。本展项陈列在展厅东侧，便于观众近距离观看。",
"B":"展项B展示灰陶罐乙，器高二十厘米，口沿直径十二厘米。表面呈灰褐色，为轮制陶器，出土于本地遗址。本展项保存状况良好，可长期陈列，适合常设展出。",
"C":"展项C展示织物残片丙，纤维鉴定记录为麻纤维。出土于本地遗址，保存状况良好。本展项采用平纹织造，经线与纬线粗细均匀，纹理清晰可辨。"}
sources={k:{"source_name":"资料"+k,"source_text":v} for k,v in src.items()}
print("### 【V1】demo 模式默认路径：generate_demo 产出能否通过质量门？")
draft=app.generate_demo("城市记忆展",sources)
r=app.validate_draft(sources,draft)
print("  detect:",json.dumps(app.detect_source_issues(sources),ensure_ascii=False))
print("  passed:",r["passed"],"checks",r["checks"],"/",r["total_checks"])
for i in r["issues"]: print("   -",i)
print("\n  => demo 模式生成的 run 状态必为 blocked；review 又因 mode=demo 拒绝批准")
print("  => demo 下永远无法走到 approved/export，评委面前演示“审核->导出”闭环会断")
for c in draft["cards"]:
    print("  卡片",c["exhibit_id"],"narration长度",len(c["narration"]))
