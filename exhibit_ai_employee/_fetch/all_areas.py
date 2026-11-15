import urllib.request, ssl, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=25,context=ctx) as r:
        return r.read()
def dec(b):
    for e in ('utf-8','gb18030'):
        try: return b.decode(e)
        except Exception: pass
    return b.decode('utf-8','ignore')

h=dec(get('https://www.kepu.net.cn/vmuseum/'))
for m in re.finditer(r'<area[^>]+>',h):
    s=m.group(0)
    a=re.search(r'href="([^"]+)"',s); alt=re.search(r'alt="([^"]*)"',s)
    print((alt.group(1) if alt else '?'), '|', a.group(1) if a else '')
