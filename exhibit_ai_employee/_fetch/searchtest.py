import urllib.request, urllib.error, ssl, re, urllib.parse

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get(u):
    req = urllib.request.Request(u, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.read().decode('utf-8', 'ignore'), r.geturl()

q = urllib.parse.quote('光的折射')
tests = [
 'https://www.cdstm.cn/search-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q=' + q,
 'https://www.cdstm.cn/search-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q=%s&page=1' % q,
]
for t in tests:
    try:
        h, f = get(t)
        print('OK', t[:100], len(h))
        print(h[:1500])
        print('-----')
    except Exception as e:
        print('FAIL', t[:100], type(e).__name__, e)

# kepu search page - find js referencing search
try:
    html, _ = get('https://www.kepu.net.cn/')
    for m in re.finditer(r'<script[^>]*src="([^"]+)"', html):
        print('js:', m.group(1))
except Exception as e:
    print('er', e)
