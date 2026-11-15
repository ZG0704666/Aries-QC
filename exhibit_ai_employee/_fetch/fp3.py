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
locs=[m.start() for m in re.finditer('万物之理',h)]
print('occurrences',locs)
for i in locs[1:]:
    print('-----')
    print(h[max(0,i-600):i+300])
