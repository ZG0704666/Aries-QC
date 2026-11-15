import importlib.util
spec=importlib.util.spec_from_file_location('a', r'D:\怀客松\exhibit_ai_employee\_fetch\article.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
out=[]
for nm,u in [('rainbow','https://www.cdstm.cn/gallery/media/mkjx/kxhb/art/2013/art_5ea11085cd5f4c0bae751db546a1befd.html'),
             ('grade8','https://www.cdstm.cn/subjects/llk/art/2024/art_7ec6975467cd492d8867b6c0d42d2e77.html')]:
    t,f,h,b=a.extract_article(u)
    out.append('##### %s | %s\nURL %s\nCJK %d\n%s\n'%(nm,t,f,a.cjk(b),b))
open('dump2.txt','w',encoding='utf-8').write('\n'.join(out))
print('ok')
