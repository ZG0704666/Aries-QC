import urllib.request, ssl, urllib.parse, json, time

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore')
def search(q,page=1):
    qq=urllib.parse.quote(q)
    ref='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q='+qq
    u=('https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/interface/search/info_new'
       '?serviceId=sT7I9StjJmJrznxcoft9c&websiteid=&q='+qq+'&pg=10&p=%d&cateid=KGA7sHXaaux0bs9wfhEBs'%page)
    j=json.loads(get(u,ref=ref))
    sr=j.get('data',{}).get('searchResult',{}) or {}
    return [(r.get('data',{}).get('title',''),r.get('data',{}).get('url',''),r.get('data',{}).get('createdatestr','')) for r in (sr.get('result') or [])]

seen=set()
for q in ['筷子 折断 折射','水中的筷子','光 折射 空气 水','光的传播 折射 反射','透镜','彩虹 形成','七色光','光谱 白光','颜色 波长 反射','吸收 反射 颜色']:
    try:
        for t,u,d in search(q):
            key=u
            if key in seen: continue
            seen.add(key)
            print('%s | %s | %s'%(d,t[:44],u[:105]))
    except Exception as e:
        print('FAIL',q,str(e)[:50])
    time.sleep(0.4)
