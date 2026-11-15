import urllib.request, ssl, urllib.parse

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
base='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/'
for ep in ['interface/structure/list-category?serviceId=sT7I9StjJmJrznxcoft9c',
           'interface/structure/list-category?serviceId=sT7I9StjJmJrznxcoft9c&websiteid=',
           'interface/search/group_count?serviceId=sT7I9StjJmJrznxcoft9c&q='+q+'&p=1&pg=10&dimensionName=x&total=10&groupFields=cateid',
           ]:
    try:
        t=get(base+ep,ref=ref)
        print('OK',ep[:70],len(t))
        print(t[:900])
    except Exception as e:
        print('FAIL',ep[:70],type(e).__name__,str(e)[:80])
    print('---')
