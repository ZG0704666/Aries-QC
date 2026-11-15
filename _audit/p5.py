import json,io,sys
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
sys.path.insert(0,'.')
import app_frozen as app

print("### 【G4】误检缺料：客户给的资料是规范、完整、但句子短的展签体")
real={"A":{"source_name":"展签","source_text":"青铜礼器甲，商代。出土于本地遗址。现藏市博物馆。器身饰三组饕餮纹。"}}
print("  4 句完整展签 detect missing =",json.dumps(app.detect_source_issues(real)[0],ensure_ascii=False))
print("  每句长度:",[len(s) for s in app.sentence_split(real["A"]["source_text"])])

print("\n### 【G5】误检缺料：资料含'未说明'等词但其实是完整的对比说明")
real2={"A":{"source_name":"展签","source_text":"青铜礼器甲为商代遗物，出土于本地遗址，现藏市博物馆，器身饰三组饕餮纹，保存状况良好，可长期陈列，信息完整。"}}
print("  detect missing =",json.dumps(app.detect_source_issues(real2)[0],ensure_ascii=False))
real3={"A":{"source_name":"展签","source_text":"展签未说明该器物的具体用途。其余信息完整：商代遗物，出土于本地遗址，现藏市博物馆，保存状况良好。"}}
print("  含'未说明'的真实完整资料 detect =",json.dumps(app.detect_source_issues(real3)[0],ensure_ascii=False))
