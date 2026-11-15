import json,io,sys,urllib.request,urllib.error,sqlite3,threading,time
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
B="http://127.0.0.1:4211"; DB="D:/怀客松/_audit/live.sqlite3"
def req(p,m="GET",d=None):
    body=None if d is None else json.dumps(d,ensure_ascii=False).encode()
    r=urllib.request.Request(B+p,data=body,method=m,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r,timeout=20) as resp:
            t=resp.read().decode('utf-8','replace')
            try: return resp.status,json.loads(t)
            except: return resp.status,{"raw":t[:200]}
    except urllib.error.HTTPError as e:
        t=e.read().decode('utf-8','replace')
        try: return e.code,json.loads(t)
        except: return e.code,{"raw":t[:300]}
    except Exception as e: return 0,{"exc":str(e)}

print("### 【C2】高并发写入 —— SQLite 'database is locked' ?")
errs=[]
def w(i):
    for _ in range(6):
        s,d=req("/api/feedback","POST",{"category":"c%d"%i,"note":"并发写入探针"*5})
        if s!=200: errs.append((s,str(d)[:120]))
ths=[threading.Thread(target=w,args=(i,)) for i in range(12)]
t0=time.time(); [t.start() for t in ths]; [t.join() for t in ths]
print("  耗时 %.1fs 失败数 %d"%(time.time()-t0,len(errs)))
for e in errs[:5]: print("   ",e)

print("\n### 【C3】feedback version 竞态：MAX(version)+1 非原子")
c=sqlite3.connect(DB)
rows=c.execute("select version,count(*) from feedback group by version having count(*)>1").fetchall()
print("  重复 version 组:",rows)
print("  feedback 总数:",c.execute("select count(*) from feedback").fetchone()[0])
c.close()
