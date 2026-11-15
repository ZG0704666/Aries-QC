import importlib.util
spec=importlib.util.spec_from_file_location('a', r'D:\怀客松\exhibit_ai_employee\_fetch\article.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
for u in ['https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2020/art_735034437e8b46919e2754a0bdb5dfe5.html',
          'https://www.cdstm.cn/gallery/media/qkdr/ydy/art/2013/art_6f2ca50813e140649450ede03c8268f3.html',
          'https://www.cdstm.cn/museum/zphc/tsyfxA/art/2019/art_3992d698992947fd86fea17b9191952b.html',
          'https://www.cdstm.cn/gallery/media/mkjx/snkxhb/art/2015/art_cca0c7ace8db4e959febfe927a79dd53.html']:
    try:
        t,f,h,b=a.extract_article(u)
        print('cjk=%d | %s'%(a.cjk(b),t[:50]))
        print('  ',b[:200].replace('\n',' / '))
    except Exception as e: print('FAIL',u[-40:],type(e).__name__,str(e)[:50])
    print()
