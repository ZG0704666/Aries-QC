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
            except: return resp.status,{"raw":t[:200]}
    except urllib.error.HTTPError as e:
        t=e.read().decode('utf-8','replace')
        try: return e.code,json.loads(t)
        except: return e.code,{"raw":t[:300]}

def mkrun(status,mode,draft,validation):
    c=sqlite3.connect(DB)
    c.execute("INSERT INTO runs(created_at,title,source_name,source_text,draft,status,validation,mode,version,sources,error) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
      ("2025-01-01T00:00:00+00:00","t","A/B/C","{}",json.dumps(draft,ensure_ascii=False),status,
       json.dumps(validation,ensure_ascii=False),mode,1,json.dumps({"A":{"source_name":"a","source_text":"x"}}),""))
    c.commit(); i=c.execute("select max(id) from runs").fetchone()[0]; c.close(); return i

print("### 【M1】blocked 状态下能否 approve？")
rid=mkrun("blocked","live",{"cards":[]},{"passed":False,"checks":0,"total_checks":1,"issues":["缺料"]})
print("  review on blocked =>",req("/api/review","POST",{"run_id":rid,"decision":"approved"}))

print("\n### 【M2】blocked 状态下能否 revise 洗白成 draft？")
s,d=req("/api/revise","POST",{"run_id":rid,"draft":{"cards":[]}})
print("  revise on blocked =>",s,"status->",d.get("status"))
c=sqlite3.connect(DB); print("  DB status now:",c.execute("select status,version from runs where id=?",(rid,)).fetchone()); c.close()

print("\n### 【M3】demo run 能否通过直接改 draft 绕过 mode 门？")
rid2=mkrun("draft","demo",{"cards":[]},{"passed":True,"checks":1,"total_checks":1,"issues":[]})
print("  review approved on demo =>",req("/api/review","POST",{"run_id":rid2,"decision":"approved"}))

print("\n### 【M4】failed 状态下 revise 是否被拦？")
rid3=mkrun("failed","live",{} ,{"passed":False})
c=sqlite3.connect(DB); c.execute("update runs set draft='{}' where id=?",(rid3,)); c.commit(); c.close()
print("  revise on failed =>",req("/api/revise","POST",{"run_id":rid3,"draft":{"cards":[]}}))

print("\n### 【M5】已 approved 的任务再次 revise —— 是否自动降级？")
rid4=mkrun("approved","live",{"cards":[{"exhibit_id":"A"}]},{"passed":True,"checks":1,"total_checks":1,"issues":[]})
s,d=req("/api/revise","POST",{"run_id":rid4,"draft":{"cards":[{"exhibit_id":"A","narration":"篡改"}]}})
print("  revise on approved =>",s,"status->",d.get("status"))
print("  版本:",d.get("version"))
