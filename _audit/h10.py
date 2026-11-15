import json,io,sys,urllib.request,urllib.error,sqlite3
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
B="http://127.0.0.1:4212"; DB="D:/怀客松/_audit/live2.sqlite3"
def req(p,m="GET",d=None):
    body=None if d is None else json.dumps(d,ensure_ascii=False).encode()
    r=urllib.request.Request(B+p,data=body,method=m,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r) as u:
            t=u.read().decode();return u.status,json.loads(t)
    except urllib.error.HTTPError as e:
        t=e.read().decode()
        try: return e.code,json.loads(t)
        except: return e.code,{"raw":t[:200]}

print("### 【M6】完整绕过链：blocked → revise(空draft) → status=draft → 再 revise 成合法draft → approve")
src={
"A":"展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理，观众可以观察刀具与工件之间的相对运动。本展项陈列在展厅东侧，便于观众近距离观看。",
"B":"展项B展示灰陶罐乙，器高二十厘米，口沿直径十二厘米。表面呈灰褐色，为轮制陶器，出土于本地遗址。本展项保存状况良好，可长期陈列，适合常设展出。",
"C":"展项C展示织物残片丙，纤维鉴定记录为麻纤维。出土于本地遗址，保存状况良好。本展项采用平纹织造，经线与纬线粗细均匀，纹理清晰可辨。"}
# 让 A 缺料：删掉后半句 -> 只有1句
src["A"]="展项A的展品是一台一九五八年的机床。"
ex=[{"exhibit_id":k,"source_name":"资料"+k,"source_text":v} for k,v in src.items()]
s,d=req("/api/generate","POST",{"title":"绕过链","exhibits":ex})
rid=d.get("id"); print("  1) generate =>",s,"status:",d.get("status"),"(缺料阻断)")
print("  2) revise 空草稿 =>",req("/api/revise","POST",{"run_id":rid,"draft":{"cards":[]}}))
c=sqlite3.connect(DB); print("     DB:",c.execute("select status,version from runs where id=?",(rid,)).fetchone()); c.close()
print("  3) 此时再 review approved =>",req("/api/review","POST",{"run_id":rid,"decision":"approved"})[0])
s2,d2=req("/api/runs/%d/versions"%rid)
print("  4) 但 versions[0].validation.passed =",(d2["versions"][0]["validation"].get("passed")))
print("\n  ⚠ 关键：revise 不校验 status 是否 blocked，blocked 任务可被洗成 draft")
print("  ⚠ 但 approve 时会重新 validate_draft，所以缺料仍被拦 -> 该链只造成状态失真，不造成越权批准")
