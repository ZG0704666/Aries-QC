import urllib.request, urllib.error, ssl, re, urllib.parse

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx = ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE

def get(u, ref=None):
    h={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: h['Referer']=ref
    req=urllib.request.Request(u,headers=h)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

for u in ['https://www.kepu.net.cn/js/keputop_2024_9.js',
          'https://www.kepu.net.cn/images/keputop_2024_9.js']:
    try:
        js,_=get(u); print('OK',u,len(js))
        for m in re.finditer(r'.{80}search.{120}', js, re.S):
            print(m.group(0))
    except Exception as e:
        print('FAIL',u,type(e).__name__,e)

try:
    html,_=get('https://www.kepu.net.cn/')
    for m in re.finditer(r'<form[^>]*>', html):
        print('FORM:', m.group(0))
    idx=html.find('searchword')
    print('CTX:', html[max(0,idx-500):idx+500])
except Exception as e:
    print('e',e)
