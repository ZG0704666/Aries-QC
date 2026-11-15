import urllib.request, ssl, urllib.parse, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=25,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

tests=['http://www.kepu.net.cn/gb/',
       'http://www.kepu.net.cn/gb/earth/weather/light/lgt008_2.html',
       'http://www.kepu.net.cn/gb/earth/weather/light/',
       'http://www.kepu.net.cn/gb/beyond/',
       'http://www.kepu.net.cn/gb/special/',
      ]
for u in tests:
    try:
        h,f=get(u)
        print('OK',u,'->',f,'len',len(h))
        if len(h)<20000:
            t=re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',h))
            print('   TXT:',t[:400])
    except Exception as e:
        print('FAIL',u,type(e).__name__,str(e)[:70])
