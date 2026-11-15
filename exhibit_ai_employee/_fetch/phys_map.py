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

h_src=dec(get('https://www.kepu.net.cn/vmuseum/')[0])
i=h_src.find('Map2')
seg=h_src[i:i+3000]
for m in re.finditer(r'<area[^>]+>',seg):
    print(m.group(0)[:170])
