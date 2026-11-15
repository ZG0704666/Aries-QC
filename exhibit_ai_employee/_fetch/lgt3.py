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

for u in ['http://www.kepu.net.cn/gb/earth/weather/light/lgt003.html',
          'http://www.kepu.net.cn/gb/science/',
          'http://www.kepu.net.cn/gb/science/index.html']:
    try:
        b,f=get(u); h=dec(b)
        plain=re.sub(r'<script.*?</script>','',h,flags=re.S)
        plain=re.sub(r'<style.*?</style>','',plain,flags=re.S)
        t=re.sub(r'<[^>]+>','\n',plain)
        lines=[x.strip() for x in t.split('\n') if x.strip()]
        body=''.join(lines)
        print('==',f,'len',len(h),'textlen',len(body))
        print(body[:700])
        print()
    except Exception as e:
        print('FAIL',u,type(e).__name__,str(e)[:70])
