import json,io,sys,urllib.request,urllib.error,socket
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
B="http://127.0.0.1:4211"
print("### 【E5】负数/超大 Content-Length 直连")
for label,cl in (("负数 -1",b"-1"),("非数字",b"abc"),("超 1MB",b"2000000")):
    try:
        sk=socket.create_connection(("127.0.0.1",4211),timeout=6)
        sk.sendall(b"POST /api/generate HTTP/1.1\r\nHost: x\r\nContent-Length: "+cl+b"\r\nContent-Type: application/json\r\n\r\n{\"title\":\"x\"}")
        sk.settimeout(4)
        data=sk.recv(500)
        print(" ",label,"=>",data.split(b"\r\n")[0],data[-120:])
        sk.close()
    except Exception as e: print(" ",label,"=> EXC",type(e).__name__,e)

print("\n### 【E6】SSRF：AI_BASE_URL 环境变量控制出站目标（管理员级，但无校验）")
import re
src=open("app_frozen.py",encoding='utf-8').read()
print("  API_BASE 来源:", re.search(r'API_BASE\s*=\s*.+', src).group(0))
print("  有无 scheme/host 白名单校验:", "allowlist" in src or "ALLOWED_HOST" in src)

print("\n### 【E7】URL 路径用 urlparse().path —— 未做 query 解析/归一，是否可绕 export 状态门？")
for p in ("/api/runs/1/export","/api/runs/1/export/","//api/runs/1/export","/api/runs/1/export?x=1","/api/./runs/1/export"):
    body=json.dumps({"x":1}).encode()
    r=urllib.request.Request(B+p,data=body,method="GET",headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r) as resp: print("  ",p,"=>",resp.status)
    except urllib.error.HTTPError as e: print("  ",p,"=>",e.code)
