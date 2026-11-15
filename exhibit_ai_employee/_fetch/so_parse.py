import urllib.request, ssl, urllib.parse, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

h,f=get('https://www.so.com/s?q='+urllib.parse.quote('光的折射 科普 原理 实例'))
open('so_refraction.html','w',encoding='utf-8').write(h)
for m in re.finditer(r'<h3[^>]*>(.*?)</h3>',h,re.S):
    block=m.group(1)
    a=re.search(r'href="([^"]+)"',block)
    t=re.sub(r'<[^>]+>','',block).strip()
    if a: print(t[:80],'||',a.group(1)[:130])
