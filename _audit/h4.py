import json,io,sys,urllib.request,urllib.error,sqlite3,socket
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

print("### 【E1】approved+passed 导出（build_package 是否可用）")
draft={"cards":[{"exhibit_id":"A","location":"展项A","card_title":"机床","narration":"讲解"*70,
 "no_target_prompt":"x","multi_target_prompt":"y","question":"q","answer":"a",
 "citations":[{"source_name":"a","source_text":"x","source_quote":"quote"}],"facts":[]}]}
c=sqlite3.connect(DB)
c.execute("INSERT INTO runs(created_at,title,source_name,source_text,draft,status,validation,mode,version,sources,error) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
 ("2025-01-01T00:00:00+00:00","审计导出","A/B/C","{}",json.dumps(draft,ensure_ascii=False),"approved",
  json.dumps({"passed":True,"checks":9,"total_checks":9,"issues":[]}),"live",1,
  json.dumps({"A":{"source_name":"a","source_text":"x"}}),""))
c.commit(); rid=c.execute("select max(id) from runs").fetchone()[0]; c.close()
s,d=req("/api/runs/%d/export"%rid)
print("  export =>",s)
print("  files:",list((d.get("package") or {}).get("files",{}).keys()))
print("  base_name:",(d.get("package") or {}).get("base_name"))

print("\n### 【E2】路径穿越：title 用于 package_name")
c=sqlite3.connect(DB); c.execute("update runs set title=? where id=?",("../../etc/passwd",rid)); c.commit(); c.close()
s,d=req("/api/runs/%d/export"%rid)
print("  base_name =>",repr((d.get("package") or {}).get("base_name")))

print("\n### 【E3】错误信息泄露：schema 细节")
print("  已知 500 暴露:", "UNIQUE constraint failed: versions.run_id, versions.version")

print("\n### 【E4】负数 Content-Length")
try:
    sk=socket.create_connection(("127.0.0.1",4211),timeout=5)
    sk.sendall(b"POST /api/generate HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\nContent-Type: application/json\r\n\r\n")
    sk.settimeout(3)
    data=sk.recv(400)
    print("  =>",data[:250])
    sk.close()
except Exception as e: print("  =>",e)
