import json,io,sys,re,urllib.request,urllib.error
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
B="http://127.0.0.1:4211"
def req(p,m="GET",d=None):
    body=None if d is None else json.dumps(d,ensure_ascii=False).encode()
    r=urllib.request.Request(B+p,data=body,method=m,headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r) as u: return u.status,json.loads(u.read().decode())
    except urllib.error.HTTPError as e:
        t=e.read().decode(); return e.code,json.loads(t)

html=open("index.html",encoding='utf-8').read()
print("### 【F1】前端引用的 run/package 字段")
for f in ["base_name","package_version","total_checks","checks","detected","requires_confirmation","diff","actor"]:
    used = f in html
    print("   %-22s 前端引用:%s"%(f,used))

print("\n### 【F2】/versions 返回的字段 vs select() 期望")
s,d=req("/api/runs/1/versions")
v=(d.get("versions") or [{}])
print("   versions[0] keys:",sorted(v[0].keys()) if v else "无")
print("   select() 读取: latest.version/draft/validation/diff ->", all(k in (v[0] if v else {}) for k in ("version","draft","validation","diff")))

print("\n### 【F3】/api/runs 列表字段 vs 前端 runs.map 读取")
s,d=req("/api/runs")
r0=(d.get("runs") or [{}])[0]
print("   runs[0] keys:",sorted(r0.keys()))
for f in ["title","status","mode","created_at","source_name","version"]:
    print("   前端读 %-12s 后端有:%s"%(f,f in r0))

print("\n### 【F4】export 的 package.files 是 dict -> 前端点 .files 后遍历?")
s,d=req("/api/runs/999999/export")
print("   不存在任务 export =>",s,d)
