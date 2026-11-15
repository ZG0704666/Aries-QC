import urllib.request, ssl, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=25,context=ctx) as r:
        return r.read(), r.geturl()

def dec(b):
    for e in ('utf-8','gb18030'):
        try: return b.decode(e)
        except Exception: pass
    return b.decode('utf-8','ignore')

for u in ['http://www.kepu.net.cn/gb/earth/weather/light/',
          'http://www.kepu.net.cn/gb/earth/weather/']:
    b,f=get(u); h=dec(b)
    print('==',f,len(h))
    for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',h,re.S):
        t=re.sub(r'<[^>]+>','',m.group(2)).strip()
        if t and len(t)<40: print('  ',t,'|',m.group(1)[:80])
