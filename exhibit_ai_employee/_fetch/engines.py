import urllib.request, ssl, urllib.parse, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

q=urllib.parse.quote('光的折射 site:kepu.net.cn')
engines=[
 'https://cn.bing.com/search?q='+q,
 'https://www.sogou.com/web?query='+q,
 'https://search.cn.bing.com/search?q='+q,
 'https://www.so.com/s?q='+q,
]
for u in engines:
    try:
        h,f=get(u)
        kep=set(re.findall(r'https?://[a-z0-9.]*kepu\.net\.cn[^\s"\'<>]*',h))
        print('OK',u.split('?')[0],len(h),'kepulinks',len(kep))
        for k in list(kep)[:6]: print('   ',k[:120])
    except Exception as e:
        print('FAIL',u.split('?')[0],type(e).__name__,str(e)[:100])
