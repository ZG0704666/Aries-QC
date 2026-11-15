import urllib.request, ssl, urllib.parse, re, json

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl(), dict(r.headers)

q=urllib.parse.quote('光的折射')
base='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q='+q
cands=[
 base+'&page=1&pagesize=10',
 base+'&pageNum=1&pageSize=10',
 base+'&p=1&size=10',
 'https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/api/search?serviceId=sT7I9StjJmJrznxcoft9c&q='+q+'&page=1&size=10',
 'https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/ss/search?serviceId=sT7I9StjJmJrznxcoft9c&q='+q+'&page=1&size=10',
]
for u in cands:
    try:
        t,f,h=get(u,ref=base)
        links=re.findall(r'href="([^"]*art/\d{4}[^"]*)"',t)
        print('OK len',len(t),'artlinks',len(links),'|',u[len(base):][:60])
        for l in links[:5]: print('   ',l)
    except Exception as e:
        print('FAIL',u[60:120],type(e).__name__,str(e)[:80])
