import urllib.request, ssl, urllib.parse, json, time
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA,'Referer':'https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q=x'})
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore')
def search(q,page=1):
    qq=urllib.parse.quote(q)
    u=('https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/interface/search/info_new'
       '?serviceId=sT7I9StjJmJrznxcoft9c&websiteid=&q='+qq+'&pg=10&p=%d&cateid=KGA7sHXaaux0bs9wfhEBs'%page)
    j=json.loads(get(u)); sr=j.get('data',{}).get('searchResult',{}) or {}
    return [(r.get('data',{}).get('title',''),r.get('data',{}).get('url',''),r.get('data',{}).get('createdatestr','')) for r in (sr.get('result') or [])]

seen=set()
for q in ['白光 七种颜色','光谱 分解','棱镜','七色光 分解','牛顿 光学','光的颜色','色彩 原理','加色法','色光 混合','眼睛 看见颜色','波长 颜色 物体']:
    for t,u,d in search(q):
        if u in seen: continue
        seen.add(u); print('%s | %s | %s'%(d,t[:40],u[:100]))
    print('--',q)
    time.sleep(0.35)
