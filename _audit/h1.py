import json,io,sys,urllib.request,urllib.error
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
B="http://127.0.0.1:4211"
def req(p,m="GET",d=None,hdrs=None):
    body=None if d is None else json.dumps(d,ensure_ascii=False).encode()
    h={"Content-Type":"application/json"}; h.update(hdrs or {})
    r=urllib.request.Request(B+p,data=body,method=m,headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            t=resp.read().decode('utf-8','replace')
            try: return resp.status,json.loads(t)
            except: return resp.status,{"raw":t[:200]}
    except urllib.error.HTTPError as e:
        t=e.read().decode('utf-8','replace')
        try: return e.code,json.loads(t)
        except: return e.code,{"raw":t[:300]}

print("### 【S1】index.html 提交的字段 vs 服务端 normalize_sources 期望")
print(" 前端: {title, source_name, source_text}  <- 单展项扁平结构")
print(" 后端: 期望 {title, exhibits:[{exhibit_id,source_name,source_text}] x3}")
r=req("/api/generate","POST",{"title":"城市记忆展","source_name":"展览资料样例 v1","source_text":"本展览呈现城市从传统街巷向现代社区发展的历史过程。"})
print(" ★ 前端原样请求 =>",r[0],json.dumps(r[1],ensure_ascii=False))

print("\n### 【S2】无鉴权：任意来源可读全部任务")
s,d=req("/api/runs"); print("  /api/runs =>",s,"条数:",len(d.get("runs",[])))
