import urllib.request, urllib.error, ssl, re, urllib.parse, http.cookiejar

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ctx),
    urllib.request.HTTPCookieProcessor(cj),
    urllib.request.HTTPRedirectHandler(),
)

def get(u, ref=None):
    h = {'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9',
         'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'}
    if ref: h['Referer'] = ref
    req = urllib.request.Request(u, headers=h)
    with opener.open(req, timeout=30) as r:
        return r.read().decode('utf-8', 'ignore'), r.geturl()

# prime cookies
try:
    get('https://www.cdstm.cn/')
    print('cookies:', [c.name for c in cj])
except Exception as e:
    print('prime fail', e)

q = urllib.parse.quote('光的折射')
for t in ['https://www.cdstm.cn/search-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q=' + q,
          'https://www.cdstm.cn/search-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q=%s&size=20' % q]:
    try:
        h, f = get(t, ref='https://www.cdstm.cn/')
        print('OK', f, len(h))
        print(h[:1200])
    except Exception as e:
        print('FAIL', type(e).__name__, e)
    print('---')

# 163 search
try:
    h, f = get('https://www.163.com/search?keyword=' + urllib.parse.quote('光的折射'))
    print('163 OK', f, len(h))
    print(h[:400])
except Exception as e:
    print('163 FAIL', type(e).__name__, e)
