import urllib.request, ssl, re, json, sys, os

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE

def get(u,ref=None,timeout=30):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=timeout,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

def html_to_text(h):
    h=re.sub(r'<!--.*?-->','',h,flags=re.S)
    h=re.sub(r'<script.*?</script>','',h,flags=re.S|re.I)
    h=re.sub(r'<style.*?</style>','',h,flags=re.S|re.I)
    h=re.sub(r'<br\s*/?>','\n',h,flags=re.I)
    h=re.sub(r'</(p|div|h[1-6]|li|tr|td|section|article)>','\n',h,flags=re.I)
    t=re.sub(r'<[^>]+>','',h)
    t=t.replace('&nbsp;',' ').replace('&ldquo;','“').replace('&rdquo;','”')
    t=t.replace('&mdash;','—').replace('&hellip;','…').replace('&amp;','&')
    t=t.replace('&lt;','<').replace('&gt;','>').replace('&quot;','"').replace('&#39;',"'")
    lines=[x.strip() for x in t.split('\n')]
    lines=[x for x in lines if x]
    return '\n'.join(lines)

def cjk_count(s):
    return len(re.findall(r'[一-鿿]',s))

if __name__=='__main__':
    for u in sys.argv[1:]:
        try:
            h,f=get(u)
            t=html_to_text(h)
            print('URL:',u)
            print('  final:',f,'html',len(h),'text',len(t),'cjk',cjk_count(t))
            print('  head:',t[:160].replace('\n',' / '))
        except Exception as e:
            print('URL:',u,'FAIL',type(e).__name__,str(e)[:80])
        print()
