import urllib.request, urllib.error, ssl, re
import urllib.parse

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get(u):
    req = urllib.request.Request(u, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.read().decode('utf-8', 'ignore'), r.geturl()

# inspect homepage for search form / urls
for home in ['https://www.cdstm.cn/', 'https://www.kepu.net.cn/']:
    html, f = get(home)
    print('==', home)
    for m in re.finditer(r'(?i)(search|sousuo|so\.|query)[^"\'<> ]{0,120}', html):
        s = m.group(0)
        print('  ', s[:140])
