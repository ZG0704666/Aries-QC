import sys, importlib.util, json
spec=importlib.util.spec_from_file_location('a', r'D:\怀客松\exhibit_ai_employee\_fetch\article.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)

urls=[
 ('refraction','https://www.cdstm.cn/gallery/kxfdj/art/2020/art_1e1409c7767b4a62bef207828bdfb93b.html'),
 ('refraction','https://www.cdstm.cn/gallery/hycx/hqkxltqyzxgt/art/2020/art_f24c9cd4c00f470290f5b8a78c4d2fd2.html'),
 ('refraction','https://www.cdstm.cn/subjects/yxkx/ydkxk/video/202106/t20210611_1049554.html'),
 ('sound','https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2020/art_48b013bcec814995bd1dc75a3387bdfb.html'),
 ('sound','https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2020/art_2384d3f53dfc455d8fb6b36cb9a97923.html'),
 ('sound','https://www.cdstm.cn/theme/khsj/khzx/khqw/art/2022/art_ac89fb7a365746f3a7410f6e7ac246e6.html'),
 ('sound','https://www.cdstm.cn/theme/khsj/khzx/khqw/art/2022/art_d6e564b9cf914b70866eede85f58c228.html'),
 ('color','https://www.cdstm.cn/zt/xjll/pyj/art/2017/art_c0d56a506e1e4bfeb94f2c6853e1479a.html'),
 ('color','https://www.cdstm.cn/gallery/hycx/hqkxltqyzxgt/art/2018/art_1aec662fcdf64bfa848f224586f059d0.html'),
 ('color','https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2020/art_2c2f0c25f6384676ae1a3f558f9cc112.html'),
 ('color','https://www.cdstm.cn/theme/khsj/khzx/khqx/art/2020/art_b591bf98101547228fa052e47c8e5919.html'),
]
for tp,u in urls:
    try:
        title,f,h,body=a.extract_article(u)
        print('%s cjk=%d len=%d | %s' % (tp, a.cjk(body), len(body), title[:70]))
        print('    URL->',f)
        print('    ', body[:120].replace('\n',' / '))
    except Exception as e:
        print('%s FAIL %s %s'%(tp,u[-50:],type(e).__name__),str(e)[:60])
    print()
