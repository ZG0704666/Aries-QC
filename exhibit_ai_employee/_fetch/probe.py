import urllib.request, urllib.error, ssl, sys

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

urls = [
    'https://www.cdstm.cn/',
    'https://www.kepu.net.cn/',
    'https://www.cdstm.cn/search/',
]

for u in urls:
    try:
        req = urllib.request.Request(u, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            data = r.read()
            print('OK', r.status, u, 'len', len(data), 'final', r.geturl())
            txt = data.decode('utf-8', 'ignore')
            print(txt[:600].replace('\n', ' '))
            print('---')
    except Exception as e:
        print('FAIL', u, type(e).__name__, e)
