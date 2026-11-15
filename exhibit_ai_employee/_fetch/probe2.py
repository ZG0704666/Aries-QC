import urllib.request, urllib.error, ssl, urllib.parse, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE

def get(u,ref=None):
    h={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: h['Referer']=ref
    req=urllib.request.Request(u,headers=h)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

# 163 search
h,f=get('https://www.163.com/search?keyword='+urllib.parse.quote('光的折射'))
open('163_search.html','w',encoding='utf-8').write(h)
print('163 len',len(h))
for l in sorted(set(re.findall(r'href="(https?://[^"]*(?:163|blog|zhihu)[^"]*)"',h)))[:40]:
    print('  ',l[:140])

# cdstm sitemap
try:
    s,fs=get('https://www.cdstm.cn/wbwh/sitemap/index.html')
    open('cdstm_sitemap.html','w',encoding='utf-8').write(s)
    print('SITEMAP len',len(s))
    for l in re.findall(r'href="([^"]+)"',s)[:80]:
        print('  S',l)
except Exception as e:
    print('sitemap fail',type(e).__name__,e)
