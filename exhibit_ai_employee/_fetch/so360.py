import urllib.request, ssl, urllib.parse, re, collections

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

qs={'refraction':'光的折射 科普 原理 实例',
    'sound':'声音的传播 需要介质 声速',
    'color':'光的色散 白光 三棱镜 三原色'}
out=[]
for t,q in qs.items():
    h,f=get('https://www.so.com/s?q='+urllib.parse.quote(q))
    plain=re.sub(r'\s+',' ',h)
    ks=set(re.findall(r'https?://(?:www\.)?(?:kepu\.net\.cn|cdstm\.cn)[^\s"\'<>\\]{0,150}',plain))
    out.append('### %s  (%d chars)'%(t,len(h)))
    for k in sorted(ks): out.append('  '+k)
    # also print title-ish anchors
    for m in re.finditer(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.{0,90}?)</a>',h):
        pass
open('so_results.txt','w',encoding='utf-8').write('\n'.join(out))
print('\n'.join(out)[:3000])
