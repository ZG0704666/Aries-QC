import urllib.request, ssl, re

UA='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'
ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE

def get(u,ref=None,timeout=30):
    hh={'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'}
    if ref: hh['Referer']=ref
    req=urllib.request.Request(u,headers=hh)
    with urllib.request.urlopen(req,timeout=timeout,context=ctx) as r:
        return r.read().decode('utf-8','ignore'), r.geturl()

def _block(h, cls):
    """Return inner HTML of the first <tag class="...cls..."> ... matching close."""
    m=re.search(r'<(div|article|section)[^>]*class="[^"]*\b%s\b[^"]*"[^>]*>'%re.escape(cls),h,re.I)
    if not m: return None
    start=m.end(); i=start; depth=1; tag=m.group(1).lower()
    for mm in re.finditer(r'</?%s\b[^>]*>'%tag, h[start:], re.I):
        if mm.group(0).startswith('</'): depth-=1
        else: depth+=1
        if depth==0:
            i=start+mm.start(); return h[start:i]
    return h[start:]

def html_to_text(h):
    h=re.sub(r'<!--.*?-->','',h,flags=re.S)
    h=re.sub(r'<script.*?</script>','',h,flags=re.S|re.I)
    h=re.sub(r'<style.*?</style>','',h,flags=re.S|re.I)
    h=re.sub(r'<br\s*/?>','\n',h,flags=re.I)
    h=re.sub(r'</(p|div|h[1-6]|li|tr|section|article|blockquote)>','\n',h,flags=re.I)
    t=re.sub(r'<[^>]+>','',h)
    for a,b in [('&nbsp;',' '),('&ldquo;','“'),('&rdquo;','”'),('&mdash;','—'),
                ('&hellip;','…'),('&amp;','&'),('&lt;','<'),('&gt;','>'),
                ('&quot;','"'),('&#39;',"'"),('&middot;','·'),('&lsquo;','‘'),
                ('&rsquo;','’'),('&copy;','©')]:
        t=t.replace(a,b)
    lines=[x.strip() for x in t.split('\n')]
    return '\n'.join([x for x in lines if x])

def cjk(s):
    return len(re.findall(r'[一-鿿]',s))

def extract_article(u):
    h,f=get(u)
    title=''
    m=re.search(r'<title>(.*?)</title>',h,re.S)
    if m: title=re.sub(r'\s+',' ',m.group(1)).strip()
    body=None
    for cls in ['article-content','TRS_Editor','content','article','detail','zw','text']:
        b=_block(h,cls)
        if b and cjk(html_to_text(b))>200:
            body=html_to_text(b); break
    if body is None:
        body=html_to_text(h)
    return title,f,h,body
