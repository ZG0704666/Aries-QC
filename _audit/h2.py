import json,io,sys,urllib.request,urllib.error,sqlite3,threading
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
B="http://127.0.0.1:4211"
DB="D:/怀客松/_audit/live.sqlite3"
def req(p,m="GET",d=None):
    body=None if d is None else json.dumps(d,ensure_ascii=False).encode()
    r=urllib.request.Request(B+p,data=body,method=m,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r) as resp:
            t=resp.read().decode('utf-8','replace')
            try: return resp.status,json.loads(t)
            except: return resp.status,{"raw":t[:200]}
    except urllib.error.HTTPError as e:
        t=e.read().decode('utf-8','replace')
        try: return e.code,json.loads(t)
        except: return e.code,{"raw":t[:300]}

src={
"A":"展项A的展品是一台一九五八年的机床，由市机械厂捐赠。它用于演示车削加工的基本原理，观众可以观察刀具与工件之间的相对运动。本展项陈列在展厅东侧，便于观众近距离观看。",
"B":"展项B展示灰陶罐乙，器高二十厘米，口沿直径十二厘米。表面呈灰褐色，为轮制陶器，出土于本地遗址。本展项保存状况良好，可长期陈列，适合常设展出。",
"C":"展项C展示织物残片丙，纤维鉴定记录为麻纤维。出土于本地遗址，保存状况良好。本展项采用平纹织造，经线与纬线粗细均匀，纹理清晰可辨。"}
ex=[{"exhibit_id":k,"source_name":"资料"+k,"source_text":v} for k,v in src.items()]
s,d=req("/api/generate","POST",{"title":"并发探针","exhibits":ex})
print("generate =>",s,d.get("status"),"id",d.get("id"))
rid=d["id"]

print("\n### 【C1】并发 revise —— UNIQUE(run_id,version) 冲突")
results=[]
def worker(i):
    code,body=req("/api/revise","POST",{"run_id":rid,"draft":{"cards":[],"marker":i},"actor":"w%d"%i})
    results.append((i,code,body.get("version"),body.get("error")))
ths=[threading.Thread(target=worker,args=(i,)) for i in range(8)]
[t.start() for t in ths]; [t.join() for t in ths]
for r in sorted(results):
    print("  worker",r[0],"HTTP",r[1],"version",r[2],"err",r[3])
c=sqlite3.connect(DB)
print("  runs.version =",c.execute("select version from runs where id=?",(rid,)).fetchone())
print("  versions 行:",c.execute("select version,actor from versions where run_id=? order by version",(rid,)).fetchall())
c.close()
