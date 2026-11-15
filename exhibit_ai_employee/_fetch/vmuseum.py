import urllib.request, ssl, re, urllib.parse

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

for u in ['https://www.kepu.net.cn/vmuseum/',
          'https://www.kepu.net.cn/vmuseum/technology/',
          'https://www.kepu.net.cn/vmuseum/physics/',
          'https://www.kepu.net.cn/vmuseum/overview/']:
    try:
        b,f=get(u); h=dec(b)
        print('OK',u,'len',len(h))
        for a,t in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',h,re.S)[:50]:
            tt=re.sub(r'<[^>]+>','',t).strip()
            if tt and len(tt)<40: print('    ',tt,'|',a[:80])
    except Exception as e:
        print('FAIL',u,type(e).__name__,str(e)[:60])
