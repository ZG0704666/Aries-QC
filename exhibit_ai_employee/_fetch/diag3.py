import urllib.request, ssl, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

h,_=get('https://www.cdstm.cn/')
i=h.find('search-web-server')
print('CTX1:', h[max(0,i-1200):i+400])
print()
j=h.find('search-box')
print('CTX2:', h[max(0,j-800):j+900])
