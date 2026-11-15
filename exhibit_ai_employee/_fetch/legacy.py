import urllib.request, ssl, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=20,context=ctx) as r:
        return r.read()
def dec(b):
    for e in ('utf-8','gb18030'):
        try: return b.decode(e)
        except Exception: pass
    return b.decode('utf-8','ignore')

paths=['gb/earth/index.html','gb/earth/weather/index.html','gb/earth/weather/light/index.html',
       'gb/technology/index.html','gb/lives/index.html','gb/basic/index.html',
       'gb/earth/weather/light/lgt003.html',
       'gb/earth/weather/light/lgt008_1.html','gb/earth/weather/light/lgt007.html']
for p in paths:
    u='https://www.kepu.net.cn/'+p
    try:
        h=dec(get(u))
        print('OK %-45s len=%d'%(p,len(h)))
        if len(h)<1000: print('    ',re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',h))[:120])
    except Exception as e:
        print('FAIL %-45s %s'%(p,type(e).__name__))
