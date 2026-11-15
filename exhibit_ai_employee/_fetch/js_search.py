import urllib.request, ssl, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore')

js=get('https://www.cdstm.cn/jsearch_files/publish/sT7I9StjJmJrznxcoft9c//js/search/search1.js')
open('search1.js','w',encoding='utf-8').write(js)
print('len',len(js))
for m in re.finditer(r'(url\s*:\s*[^,\n]{0,120}|\$\.(?:ajax|get|post)\([^)]{0,200})',js):
    print('  ',m.group(0).replace('\n',' ')[:200])
