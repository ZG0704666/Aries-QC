import urllib.request, ssl, urllib.parse, json

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9','X-Requested-With':'XMLHttpRequest'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore')

q=urllib.parse.quote('光的折射')
ref='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q='+q
u=('https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/interface/search/info_new'
   '?serviceId=sT7I9StjJmJrznxcoft9c&websiteid=&q='+q+'&pg=10&p=1&cateid=KGA7sHXaaux0bs9wfhEBs')
t=get(u,ref=ref)
open('api_result.json','w',encoding='utf-8').write(t)
print('len',len(t))
try:
    j=json.loads(t)
    sr=j['data']['searchResult']
    print('total',sr.get('total'),'count',sr.get('countNumber'))
    for r in sr.get('result',[])[:25]:
        d=r['data']
        print(' -',d.get('createdatestr'),'|',d.get('title')[:60],'|',d.get('url')[:110])
except Exception as e:
    print('parse err',e); print(t[:600])
