import urllib.request, ssl, re, importlib.util
spec=importlib.util.spec_from_file_location('a', r'D:\怀客松\exhibit_ai_employee\_fetch\article.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def getb(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=20,context=ctx) as r:
        return r.read()
def dec(b):
    for e in ('utf-8','gb18030'):
        try: return b.decode(e)
        except Exception: pass
    return b.decode('utf-8','ignore')

for p in ['gb/earth/weather/light/lgt003.html','gb/earth/weather/light/lgt007.html',
          'gb/earth/weather/light/lgt008_1.html','gb/earth/weather/light/lgt009.html',
          'gb/earth/weather/light/lgt001.html','gb/earth/weather/light/lgt002.html']:
    u='https://www.kepu.net.cn/'+p
    try:
        h=dec(getb(u)); t=a.html_to_text(h)
        print('%-42s cjk=%d  %s'%(p, a.cjk(t), t[:70].replace('\n',' ')))
    except Exception as e:
        print('FAIL',p,type(e).__name__)
