import urllib.request, urllib.error, ssl, urllib.parse, re, json

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE

def get(u,ref=None,hdrs=None):
    h={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: h['Referer']=ref
    if hdrs: h.update(hdrs)
    req=urllib.request.Request(u,headers=h)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl(), dict(r.headers)

q=urllib.parse.quote('光的折射')
cands=[
 'https://www.kepu.net.cn/irs-c-mobile/search-result?code=182109db521&searchWord='+q,
 'https://www.kepu.net.cn/irs-c-web/search-result.json?code=182109db521&searchWord='+q+'&page=1',
 'https://www.kepu.net.cn/irs-c-web/search!searchResult.action?code=182109db521&searchWord='+q,
]
for u in cands:
    try:
        t,f,hh=get(u,ref='https://www.kepu.net.cn/irs-c-web/search.shtml?code=182109db521&searchWord='+q)
        print('OK',f,'len',len(t),'ctype',hh.get('Content-Type'))
        print(t[:800].replace('\n',' '))
    except Exception as e:
        print('FAIL',u[:90],type(e).__name__,e)
    print('---')
