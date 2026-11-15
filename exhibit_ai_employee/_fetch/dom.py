import sys, importlib.util, re
spec=importlib.util.spec_from_file_location('ex', r'D:\怀客松\exhibit_ai_employee\_fetch\extract.py')
ex=importlib.util.module_from_spec(spec); spec.loader.exec_module(ex)

u='https://www.cdstm.cn/gallery/kxfdj/art/2020/art_1e1409c7767b4a62bef207828bdfb93b.html'
h,f=ex.get(u)
open('art1.html','w',encoding='utf-8').write(h)
# find candidate containers
for pat in [r'<div[^>]*class="[^"]*(?:article|content|detail|txt|zw|art)[^"]*"',]:
    for m in re.finditer(pat,h,re.I):
        print(m.group(0)[:160])
