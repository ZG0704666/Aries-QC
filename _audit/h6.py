import json,io,sys,urllib.request,urllib.error,sqlite3
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
B="http://127.0.0.1:4211"; DB="D:/怀客松/_audit/live.sqlite3"
def req(p,m="GET",d=None):
    body=None if d is None else json.dumps(d,ensure_ascii=False).encode()
    r=urllib.request.Request(B+p,data=body,method=m,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r) as resp:
            t=resp.read().decode('utf-8','replace')
            try: return resp.status,json.loads(t)
            except: return resp.status,{"raw":t[:300]}
    except urllib.error.HTTPError as e:
        t=e.read().decode('utf-8','replace')
        try: return e.code,json.loads(t)
        except: return e.code,{"raw":t[:300]}

print("### 【D1】demo 模式下生成 —— mode 字段是否可被请求方影响？")
src={
"A":"展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理，观众可以观察刀具与工件之间的相对运动。本展项陈列在展厅东侧，便于观众近距离观看。",
"B":"展项B展示灰陶罐乙，器高二十厘米，口沿直径十二厘米。表面呈灰褐色，为轮制陶器，出土于本地遗址。本展项保存状况良好，可长期陈列，适合常设展出。",
"C":"展项C展示织物残片丙，纤维鉴定记录为麻纤维。出土于本地遗址，保存状况良好。本展项采用平纹织造，经线与纬线粗细均匀，纹理清晰可辨。"}
ex=[{"exhibit_id":k,"source_name":"资料"+k,"source_text":v} for k,v in src.items()]
s,d=req("/api/generate","POST",{"title":"demo测试","exhibits":ex,"mode":"live"})
print("  请求带 mode=live =>",s,"返回mode:",d.get("mode"),"status:",d.get("status"),"id:",d.get("id"))
rid=d.get("id")

print("\n### 【D2】demo 产物是否带 DEMO 标记？能否冒充 live？")
c=sqlite3.connect(DB)
row=c.execute("select draft,mode,status from runs where id=?",(rid,)).fetchone()
dr=json.loads(row[0])
for card in dr.get("cards",[]):
    print("  ",card["exhibit_id"],"narration前30字:",card["narration"][:30].replace("\n"," "))
print("  DB mode =",row[1],"status =",row[2])
print("  cards[0] 是否含'演示模板':", "演示模板" in dr["cards"][0]["narration"])
c.close()

print("\n### 【D3】demo 生成是否也走 detect_source_issues 前置阻断？（构造冲突资料）")
src2=dict(src); src2["C"]="展项C展示织物残片丙。来源一《模拟登记卡》记载纤维鉴定记录为麻纤维。来源二《模拟说明页》记载纤维鉴定记录为棉纤维。两条记录相互冲突，无第三方检测报告。"
ex2=[{"exhibit_id":k,"source_name":"资料"+k,"source_text":v} for k,v in src2.items()]
s,d=req("/api/generate","POST",{"title":"冲突探针","exhibits":ex2})
print("  真实冲突资料 =>",s,"status:",d.get("status"),"conflicts返回:",json.dumps(d.get("conflicts"),ensure_ascii=False)[:200])
