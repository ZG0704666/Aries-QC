import re
h=open('kepu_search_https.html',encoding='utf-8').read()
for pat in [r'url\s*[:=]\s*[\'"]([^\'"]{5,200})[\'"]',
            r'ajax\(\{.{0,400}',
            r'/irs-c-[a-z\-/]+[a-zA-Z0-9_./?=&-]*']:
    print('=== pat',pat)
    for m in re.finditer(pat,h,re.S):
        print(' ',m.group(0)[:160].replace('\n',' '))
