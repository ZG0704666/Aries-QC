import urllib.request, ssl, re, urllib.parse

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

q='光的折射 site:kepu.net.cn'
h,f=get('https://cn.bing.com/search?q='+urllib.parse.quote(q)+'&ensearch=0')
open('bing.html','w',encoding='utf-8').write(h)
print('len',len(h))
plain=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',h))
print(plain[:1500])
