import urllib.request, urllib.error, ssl, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE

def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

u='https://www.cdstm.cn/frontier/xw/art/2026/art_6d6404b4406d47c6b6a21049a6b63b40.html'
h,f=get(u)
open('sample_article.html','w',encoding='utf-8').write(h)
print('len',len(h))
txt=re.sub(r'<script.*?</script>','',h,flags=re.S)
txt=re.sub(r'<style.*?</style>','',txt,flags=re.S)
plain=re.sub(r'<[^>]+>','\n',txt)
lines=[l.strip() for l in plain.split('\n')]
lines=[l for l in lines if l]
print('nlines',len(lines))
for l in lines[:120]:
    print('|',l[:110])
