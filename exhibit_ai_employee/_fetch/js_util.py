import urllib.request, ssl, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE
def get(u):
    req=urllib.request.Request(u,headers={'User-Agent':UA})
    with urllib.request.urlopen(req,timeout=30,context=ctx) as r:
        return r.read().decode('utf-8','ignore')

for js in ['https://www.cdstm.cn/jsearch_files/publish/sT7I9StjJmJrznxcoft9c//js/util1.js',
           'https://www.cdstm.cn/jsearch_files/publish/sT7I9StjJmJrznxcoft9c//js/common.js',
           'https://www.cdstm.cn/jsearch_files/publish/sT7I9StjJmJrznxcoft9c//js/websitechange/webinit.js']:
    try:
        s=get(js)
        print('==',js.split('/')[-1],len(s))
        for fn in ['otherdatanew','tooldata','ajaxGet']:
            for m in re.finditer(r'function\s+'+fn+r'|'+fn+r'\s*=\s*function', s):
                seg=s[m.start():m.start()+900]
                print('   >>>',fn)
                print(seg[:900])
                print()
    except Exception as e:
        print('FAIL',js,type(e).__name__,str(e)[:60])
