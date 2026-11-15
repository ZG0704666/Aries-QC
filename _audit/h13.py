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

print("### 【D4】demo 产物 + 人工把 mode 改成 live 是否能变成交付证据？")
# demo 生成 -> 拿 draft
src={
"A":"展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理，观众可以观察刀具与工件之间的相对运动。本展项陈列在展厅东侧，便于观众近距离观看。",
"B":"展项B展示灰陶罐乙，器高二十厘米，口沿直径十二厘米。表面呈灰褐色，为轮制陶器，出土于本地遗址。本展项保存状况良好，可长期陈列，适合常设展出。",
"C":"展项C展示织物残片丙，纤维鉴定记录为麻纤维。出土于本地遗址，保存状况良好。本展项采用平纹织造，经线与纬线粗细均匀，纹理清晰可辨。"}
ex=[{"exhibit_id":k,"source_name":"资料"+k,"source_text":v} for k,v in src.items()]
s,d=req("/api/generate","POST",{"title":"demo冒充","exhibits":ex})
rid=d["id"]; print("  生成 status:",d.get("status"),"mode:",d.get("mode"))
# 看 demo 文案本身是否已带标记
c=sqlite3.connect(DB); dr=json.loads(c.execute("select draft from runs where id=?",(rid,)).fetchone()[0])
print("  demo 文案带'演示模板'标记:", "演示模板" in dr["cards"][0]["narration"])
# 攻击：把 mode 改 live + 去掉标记 -> 能否批准？
for card in dr["cards"]:
    card["narration"]=card["narration"].replace("【演示模板，非模型生成，不可作为交付内容】","").replace("这份模板只用于验证流程与质量门是否生效，不得作为讲解交付。","")
c.execute("update runs set mode='live',draft=? where id=?",(json.dumps(dr,ensure_ascii=False),rid)); c.commit(); c.close()
print("\n  改 mode=live + 删标记后再 approve =>",req("/api/review","POST",{"run_id":rid,"decision":"approved"}))
print("  ★ 结论：mode 只是 DB 字段，无任何签名/来源绑定；去掉标记文案后 demo 内容可被批准")
