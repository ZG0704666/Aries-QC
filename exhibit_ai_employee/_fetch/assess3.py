import importlib.util
spec=importlib.util.spec_from_file_location('a', r'D:\怀客松\exhibit_ai_employee\_fetch\article.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
for u in ['https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2021/art_bf0e2300d2f74ce8a1f5de3cf9baa82b.html',
          'https://www.cdstm.cn/gallery/kxfdj/art/2022/art_477cc926434443fcb3c82148d5ee0a24.html']:
    try:
        t,f,h,b=a.extract_article(u)
        print('cjk=%d | %s'%(a.cjk(b),t[:60]))
        print(b[:400].replace('\n',' / '))
    except Exception as e:
        print('FAIL',u[-40:],type(e).__name__,str(e)[:50])
    print()
