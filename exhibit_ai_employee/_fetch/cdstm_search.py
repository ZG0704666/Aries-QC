import urllib.request, ssl, urllib.parse, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u,ref=None):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

q=urllib.parse.quote('光的折射')
u='https://www.cdstm.cn/api-gateway/jpaas-jsearch-web-server/search?serviceId=sT7I9StjJmJrznxcoft9c&q='+q
try:
    h,f=get(u,ref='https://www.cdstm.cn/')
    open('cdstm_search.html','w',encoding='utf-8').write(h)
    print('OK',f,len(h))
    plain=re.sub(r'<script.*?</script>','',h,flags=re.S)
    plain=re.sub(r'<style.*?</style>','',plain,flags=re.S)
    plain=re.sub(r'<[^>]+>','\n',plain)
    lines=[l.strip() for l in plain.split('\n') if l.strip()]
    print('lines',len(lines))
    for l in lines[:120]: print('|',l[:120])
    print('=== HREFS with art/')
    for l in sorted(set(re.findall(r'href="([^"]*art/\d{4}[^"]*)"',h)))[:40]: print('  ',l)
except Exception as e:
    print('FAIL',type(e).__name__,e)
