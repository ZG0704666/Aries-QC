import urllib.request, ssl, urllib.parse, json, time

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()
def search(q,page=1):
    qq=urllib.parse.quote(q)
    ref='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9k='+qq
    u=('https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/interface/search/info_new'
       '?serviceId=sT7I9StjJmJrznxcoft9c&websiteid=&q='+qq+'&pg=10&p=%d&cateid=KGA7sHXaaux0bs9wfhEBs'%page)
    j=json.loads(get(u,ref=ref)[0])
    sr=j.get('data',{}).get('searchResult',{}) or {}
    return [(r.get('data',{}).get('title',''),r.get('data',{}).get('url',''),r.get('data',{}).get('createdatestr','')) for r in (sr.get('result') or [])]

for q in ['折射角 入射角','光从空气斜射入水中','光的折射 筷子','光的折射 原理','光的直线传播 折射 反射 展品']:
    try:
        for t,u,d in search(q): print('%s | %s | %s'%(d,t[:42],u[:100]))
        print('---')
    except Exception as e: print('FAIL',q,str(e)[:50])
    time.sleep(0.4)

# zhihu test
for u in ['https://zhuanlan.zhihu.com/p/654766853']:
    try:
        h,f=get(u)
        print('ZHIHU',f,len(h))
        print(h[:300].replace('\n',' '))
    except Exception as e:
        print('ZHIHU FAIL',type(e).__name__,str(e)[:80])
