import json,io,sys,urllib.request,urllib.error,sqlite3
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
B="http://127.0.0.1:4212"
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
# 用 sources 缺失触发 sources[eid] KeyError -> 500
s,d=req("/api/review","POST",{"run_id":999,"decision":"approved"})
print("  review 不存在 run =>",s,d)
# 直接看失败分支代码
