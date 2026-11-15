import urllib.request, ssl, urllib.parse, json, re, time

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None,timeout=30):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=timeout,context=ctx) as r:
        return r.read().decode('utf-8','ignore')

def search(q, page=1):
    qq=urllib.parse.quote(q)
    ref='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q='+qq
    u=('https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/interface/search/info_new'
       '?serviceId=sT7I9StjJmJrznxcoft9c&websiteid=&q='+qq+'&pg=10&p=%d&cateid=KGA7sHXaaux0bs9wfhEBs'%page)
    t=get(u,ref=ref)
    j=json.loads(t)
    sr=j.get('data',{}).get('searchResult',{})
    out=[]
    for r in sr.get('result') or []:
        d=r.get('data',{})
        out.append((d.get('title',''),d.get('url',''),d.get('createdatestr','')))
    return sr.get('total'), out

queries=['光的折射','光的折射 原理','光的折射现象','声音的传播','声波 介质 传播','声音 传播 速度','光的色散','白光 色散','三原色','物体的颜色']
res={}
for q in queries:
    try:
        tot,items=search(q)
        res[q]=(tot,items)
        print('== %s total=%s'%(q,tot))
        for t,u,d in items: print('   ',d,'|',t[:50],'|',u[:110])
    except Exception as e:
        print('FAIL',q,type(e).__name__,str(e)[:70])
    time.sleep(0.5)

json.dump({k:{'total':v[0],'items':v[1]} for k,v in res.items()}, open('search_results.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
