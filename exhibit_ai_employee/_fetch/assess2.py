import importlib.util
spec=importlib.util.spec_from_file_location('a', r'D:\怀客松\exhibit_ai_employee\_fetch\article.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)

cands=[
 'https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2017/art_671d767dd79448218b017a0383a61740.html',
 'https://www.cdstm.cn/subjects/llk/art/2024/art_7ec6975467cd492d8867b6c0d42d2e77.html',
 'https://www.cdstm.cn/museum/zphc/tsyfxA/art/2019/art_6e76197447194b37ae1ca32969e6f0e3.html',
 'https://www.cdstm.cn/gallery/media/mkjx/kxhb/art/2013/art_5ea11085cd5f4c0bae751db546a1befd.html',
 'https://www.cdstm.cn/museum/zphc/dgkxg/art/2025/art_2ec384a74aa34b3abedc5352d76b4ed3.html',
]
for u in cands:
    try:
        t,f,h,b=a.extract_article(u)
        print('cjk=%d len=%d | %s'%(a.cjk(b),len(b),t[:80]))
        print('  ',b[:150].replace('\n',' / '))
    except Exception as e:
        print('FAIL',u[-45:],type(e).__name__,str(e)[:50])
    print()
