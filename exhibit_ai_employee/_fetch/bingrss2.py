import urllib.request, ssl, urllib.parse, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore')

for q in ['光的折射 site:kepu.net.cn','声音的传播 site:kepu.net.cn','光的色散 site:kepu.net.cn','三原色 site:kepu.net.cn']:
    u='https://www.bing.com/search?format=rss&q='+urllib.parse.quote(q)
    try:
        s=get(u)
        print('==',q,'len',len(s))
        for m in re.finditer(r'<item>(.*?)</item>',s,re.S):
            blk=m.group(1)
            t=re.search(r'<title>(.*?)</title>',blk,re.S)
            l=re.search(r'<link>(.*?)</link>',blk,re.S)
            if t and l: print('   ',t.group(1)[:60],'|',l.group(1)[:110])
    except Exception as e:
        print('FAIL',q,type(e).__name__,str(e)[:60])
