import sys, importlib.util
spec=importlib.util.spec_from_file_location('a', r'D:\怀客松\exhibit_ai_employee\_fetch\article.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)

urls=[('refrap','https://www.cdstm.cn/gallery/kxfdj/art/2020/art_1e1409c7767b4a62bef207828bdfb93b.html'),
      ('sound1','https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2020/art_48b013bcec814995bd1dc75a3387bdfb.html'),
      ('sound2','https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2020/art_2384d3f53dfc455d8fb6b36cb9a97923.html'),
      ('color1','https://www.cdstm.cn/zt/xjll/pyj/art/2017/art_c0d56a506e1e4bfeb94f2c6853e1479a.html')]
out=[]
for nm,u in urls:
    title,f,h,body=a.extract_article(u)
    out.append('########## %s\nTITLE: %s\nURL: %s\nCJK: %d\n---BODY---\n%s\n'%(nm,title,f,a.cjk(body),body))
open('dump.txt','w',encoding='utf-8').write('\n'.join(out))
print('ok')
