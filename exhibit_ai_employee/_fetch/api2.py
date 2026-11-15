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
base='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/interface/search/info_new'
ref='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q='+q
variants=[
 '?serviceId=sT7I9StjJmJrznxcoft9c&websiteid=&q='+q+'&pg=10&p=1&cateid=',
 '?serviceId=sT7I9StjJmJrznxcoft9c&websiteid=&q='+q+'&pg=10&p=1&cateid=0',
 '?serviceId=sT7I9StjJmJrznxcoft9c&websiteid=&q='+q+'&pg=10&p=1&cateid=all',
 '?serviceId=sT7I9StjJmJrznxcoft9c&q='+q+'&pg=10&p=1&cateid=null',
]
for v in variants:
    try:
        t=get(base+v,ref=ref)
        print('OK',v[-40:],t[:300])
    except Exception as e:
        print('FAIL',v[-40:],type(e).__name__,str(e)[:70])
    print('--')
