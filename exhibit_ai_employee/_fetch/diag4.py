import re
h=open('cdstm_search.html',encoding='utf-8').read()
for pat in [r'["\'](/[a-z0-9\-/]*api[a-z0-9\-/._]*)["\']',
            r'jpaas[a-z0-9\-/._]*',
            r'ajax\(',
            r'\$\.get\([^)]{0,200}',
            r'\$\.post\([^)]{0,300}']:
    print('=== ',pat)
    seen=set()
    for m in re.finditer(pat,h,re.S):
        s=m.group(0)[:200].replace('\n',' ')
        if s in seen: continue
        seen.add(s); print('  ',s)
