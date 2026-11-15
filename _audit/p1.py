import json,io,sys,re
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
sys.path.insert(0,'.')
import app_frozen as app

print("### 【1】冲突门漏检：真实 C 资料（故意冲突）")
srcC=open("materials/C_模拟资料_织物.md",encoding='utf-8').read()
print("  资料含'相互冲突':", "相互冲突" in srcC, "| CONFLICT_MARKERS含:", "相互冲突" in app.CONFLICT_MARKERS)
print("  实际 detect conflicts =", app.detect_source_issues({"C":{"source_name":"s","source_text":srcC}})[1])

print("\n### 【2】缺料门误检：4 句正常资料")
ok={"A":{"source_name":"s","source_text":"展项A展示青铜礼器甲，出土于本地遗址。器物保存状况良好。观众可观察器身的三处装饰。展签提供编号模拟A-17。"}}
print("  detect missing =", json.dumps(app.detect_source_issues(ok)[0],ensure_ascii=False))

print("\n### 【3】中文数字年份识别")
print("  all_years('一八五零年') =", app.all_years("一八五零年"))
print("  all_years('一九五八年') =", app.all_years("一九五八年"))
print("  cn_years('一九零零年') =", app.cn_years("一九零零年"), "(应为1900)")
print("  数字门正则对'一八五零年'命中 =", re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)?%?","一八五零年"))

print("\n### 【4】实体门正则")
pat=r"(?<![A-Za-z])[A-Z][A-Za-z0-9-]*(?:\s+[A-Z][A-Za-z0-9-]*)*"
print("  对'郑州机床厂'命中 =", re.findall(pat,"郑州机床厂捐赠的机床"))
print("  对'一九五零年'命中 =", re.findall(pat,"一九五零年"))
print("  书名号分支对'《清明上河图》'命中 =", re.findall(r"[《“\"]([^》”\"]{2,30})[》”\"]","《清明上河图》"))

print("\n### 【5】CN_YEAR 只认4位中文数字，'一九五零' 4位OK，'二零零八' OK；但'一九五O'(拉丁O) / '一九五〇'混合?")
for t in ("一九五〇年","一九零零年","二零零八年"):
    print("   ",t,"->",app.cn_years(t))
