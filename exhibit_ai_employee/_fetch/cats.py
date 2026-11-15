import urllib.request, ssl, json
UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA,'X-Requested-With':'XMLHttpRequest',
        'Referer':'https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q=x'})
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore')
j=json.loads(get('https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/interface/structure/list-category?serviceId=sT7I9StjJmJrznxcoft9c'))
for c in j['data']['categories']:
    print(c.get('iid'), c.get('categoryName'), 'level',c.get('cateLevel'),'children',c.get('hasChildren'))
    for d in c.get('dimensionResultBeans') or []:
        print('   dim:',d.get('dimensionName'), [ (e.get('name'),e.get('dictionaryCode')) for e in (d.get('dimensionInfoEntities') or [])][:12])
