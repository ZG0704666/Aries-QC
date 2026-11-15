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

for q in ['折射','折射定律','海市蜃楼','透镜 折射','声波','声音 介质','声音传播 固体 液体 气体','色散 棱镜','彩虹 七色','颜色 三原色','光的三原色']:
    try:
        items=search(q)
        print('== %s (%d)'%(q,len(items)))
        for t,u,d in items: print('   ',d,'|',t[:46],'|',u[:105])
    except Exception as e:
        print('FAIL',q,str(e)[:60])
    time.sleep(0.4)
