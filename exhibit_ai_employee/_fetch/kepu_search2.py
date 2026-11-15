import urllib.request, urllib.error, ssl, re, urllib.parse

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE

def get(u,ref=None):
    h={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: h['Referer']=ref
    req=urllib.request.Request(u,headers=h)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

q=urllib.parse.quote('光的折射')
for u in ['https://www.kepu.net.cn/irs-c-web/search.shtml?code=182109db521&searchWord='+q,
          'http://www.kepu.net.cn/irs-c-web/search.shtml?code=182109db521&searchWord='+q]:
    try:
        h,f=get(u,ref='https://www.kepu.net.cn/')
        print('OK',f,len(h))
        open('kepu_search_%s.html'%('https' if u.startswith('https') else 'http'),'w',encoding='utf-8').write(h)
        # show hrefs containing 202
        links=set(re.findall(r'href="([^"]*?/20\d{2}[^"]*?)"',h))
        for l in sorted(links)[:40]: print('  L',l)
        print('  total links',len(links))
    except Exception as e:
        print('FAIL',u[:80],type(e).__name__,e)
