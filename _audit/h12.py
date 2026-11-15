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

print("### 【X1】sources 为 '{}' 的 run（旧数据/人为）调 review -> KeyError 500 ?")
c=sqlite3.connect(DB)
c.execute("INSERT INTO runs(created_at,title,source_name,source_text,draft,status,validation,mode,version,sources,error) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
 ("2025-01-01T00:00:00+00:00","空sources","x","{}",json.dumps({"cards":[{"exhibit_id":"A"}]}),"draft",'{"passed":false}',"live",1,"{}",""))
c.commit(); rid=c.execute("select max(id) from runs").fetchone()[0]; c.close()
print("  review =>",req("/api/review","POST",{"run_id":rid,"decision":"approved"}))
print("  revise =>",req("/api/revise","POST",{"run_id":rid,"draft":{"cards":[]}}))
print("\n### 【X2】测试记录版本门：给不存在版本写测试")
print("  tests version=99 =>",req("/api/runs/%d/tests"%rid,"POST",{"number":"T1","status":"passed","input":{},"expected":{},"actual":{"x":1},"version":99}))
