import urllib.request, urllib.error, ssl, json, urllib.parse

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9','X-Requested-With':'XMLHttpRequest'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore')

q=urllib.parse.quote('光的折射')
base='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/'
ref='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q='+q
cands=[
 base+'interface/search/info_new?serviceId=sT7I9StjJmJrznxcoft9c&q='+q+'&p=1',
 base+'interface/search/info?serviceId=sT7I9StjJmJrznxcoft9c&q='+q+'&p=1',
 base+'search/interface/search/info_new?serviceId=sT7I9StjJmJrznxcoft9c&q='+q+'&p=1',
]
for u in cands:
    try:
        t=get(u,ref=ref)
        print('OK len',len(t))
        print(t[:400])
    except Exception as e:
        print('FAIL',u[60:140],type(e).__name__,str(e)[:90])
    print('--')
