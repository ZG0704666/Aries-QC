import urllib.request, ssl, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=25,context=ctx) as r:
        return r.read(), r.geturl()
def dec(b):
    for e in ('utf-8','gb18030'):
        try: return b.decode(e)
        except Exception: pass
    return b.decode('utf-8','ignore')

for js in ['https://www.kepu.net.cn/vmuseum/images/kepu_virtualmuseum_menu2.js',
           'https://www.kepu.net.cn/vmuseum/images/kepu_virtualmuseum_menu3.js']:
    try:
        b,f=get(js); s=dec(b)
        print('==',js,len(s))
        for m in re.finditer(r'(physics|wul[i]?li|万物之理)', s):
            print('   hit at',m.start(), s[max(0,m.start()-200):m.start()+200].replace('\n',' '))
    except Exception as e:
        print('FAIL',js,type(e).__name__,str(e)[:60])
