import urllib.request, ssl, urllib.parse, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

# A kepu list page
for u in ['https://www.kepu.net.cn/kpzg_kpjd/',
          'https://www.kepu.net.cn/kpqykj/',
          'https://www.kepu.net.cn/zt/']:
    try:
        h,f=get(u)
        print('== OK',f,len(h))
        ls=re.findall(r'href="([^"]*20\d{6}[^"]*)"',h)
        print('  art links',len(ls), ls[:6])
    except Exception as e:
        print('FAIL',u,type(e).__name__,str(e)[:80])
