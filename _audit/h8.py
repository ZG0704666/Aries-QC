import json,io,sys,urllib.request,urllib.error
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
B="http://127.0.0.1:4211"
def req(p,m="GET",d=None):
    body=None if d is None else json.dumps(d,ensure_ascii=False).encode()
    r=urllib.request.Request(B+p,data=body,method=m,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r) as u:
            t=u.read().decode();return u.status,json.loads(t)
    except urllib.error.HTTPError as e:
        t=e.read().decode();return e.code,json.loads(t)
src={
"A":"展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理，观众可以观察刀具与工件之间的相对运动。本展项陈列在展厅东侧，便于观众近距离观看。",
"B":"展项B展示灰陶罐乙，器高二十厘米，口沿直径十二厘米。表面呈灰褐色，为轮制陶器，出土于本地遗址。本展项保存状况良好，可长期陈列，适合常设展出。",
"C":"展项C展示织物残片丙，纤维鉴定记录为麻纤维。出土于本地遗址，保存状况良好。本展项采用平纹织造，经线与纬线粗细均匀，纹理清晰可辨。"}
ex=[{"exhibit_id":k,"source_name":"资料"+k,"source_text":v} for k,v in src.items()]
s,d=req("/api/generate","POST",{"title":"评委演示","exhibits":ex})
rid=d["id"]
print("1) generate =>",s,"status:",d.get("status"),"approval_allowed:",d.get("approval_allowed"))
print("   issues:",d.get("validation",{}).get("issues"))
print("\n2) 前端 select(%d) 走 /versions => "%rid, end="")
print(req("/api/runs/%d/versions"%rid)[0])
print("\n3) review approved =>",req("/api/review","POST",{"run_id":rid,"decision":"approved"}))
print("\n4) 导出 =>",req("/api/runs/%d/export"%rid)[0],"(demo 永远走不到导出)")
