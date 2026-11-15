import urllib.request, ssl, urllib.parse, re, json

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

# bing rss without site: restriction but with kepu/china terms
for q in ['光的折射 原理 现象 科普 中国科普博览','声音的传播 介质 声速 科普 中国科普博览','光的色散 三棱镜 白光 科普 中国科普博览']:
    try:
        u='https://www.bing.com/search?format=rss&q='+urllib.parse.quote(q)
        s,_=get(u)
        print('==',q)
        for m in re.finditer(r'<item>(.*?)</item>',s,re.S):
            blk=m.group(1)
            t=re.search(r'<title>(.*?)</title>',blk,re.S); l=re.search(r'<link>(.*?)</link>',blk,re.S)
            if t and l: print('   ',t.group(1)[:56],'|',l.group(1)[:100])
    except Exception as e:
        print('FAIL',q,str(e)[:60])
