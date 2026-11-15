import importlib.util
spec=importlib.util.spec_from_file_location('a', r'D:\怀客松\exhibit_ai_employee\_fetch\article.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
t,f,h,b=a.extract_article('https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2021/art_bf0e2300d2f74ce8a1f5de3cf9baa82b.html')
open('dump3.txt','w',encoding='utf-8').write(b)
print(a.cjk(b), '折射' in b)
