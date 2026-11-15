import urllib.request, urllib.error, ssl, re, collections

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

def get(u):
    req = urllib.request.Request(u, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        return r.read().decode('utf-8', 'ignore'), r.geturl()

out = []
for home in ['https://www.cdstm.cn/', 'https://www.kepu.net.cn/']:
    try:
        html, final = get(home)
        out.append('=== %s -> %s (len %d)' % (home, final, len(html)))
        links = re.findall(r'href="([^"]+)"', html)
        seen = collections.OrderedDict()
        for l in links:
            if l.startswith('#') or l.startswith('javascript'): continue
            seen.setdefault(l, 0)
            seen[l] += 1
        for l in list(seen)[:200]:
            out.append('  ' + l)
    except Exception as e:
        out.append('FAIL %s %s %s' % (home, type(e).__name__, e))

open('links.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('wrote', len(out))
