import urllib.request, ssl, urllib.parse, re, collections

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

queries = {
 'refraction': ['光的折射 原理 科普', '光的折射 site:kepu.net.cn', '光的折射 site:cdstm.cn'],
 'sound': ['声音的传播 介质 声波 科普', '声音的传播 site:kepu.net.cn', '声速 介质 site:cdstm.cn'],
 'color': ['光的色散 白光的分解 科普', '光的色散 site:kepu.net.cn', '三原色 物体的颜色 site:cdstm.cn'],
}
res=collections.defaultdict(list)
for topic, qs in queries.items():
    for q in qs:
        try:
            h,f=get('https://www.sogou.com/web?query='+urllib.parse.quote(q))
            ks=set(re.findall(r'https?://(?:www|self|v)?\.?kepu\.net\.cn[^\s"\'<>\\]*',h))
            ks|=set(re.findall(r'https?://www\.cdstm\.cn[^\s"\'<>\\]*',h))
            for k in ks:
                if k not in res[topic]: res[topic].append(k)
            print('OK',q,len(h),len(ks))
        except Exception as e:
            print('FAIL',q,type(e).__name__,str(e)[:60])

with open('cands.txt','w',encoding='utf-8') as f:
    for t,ls in res.items():
        f.write('### %s\n'%t)
        for l in ls: f.write(l+'\n')
print('done')
