import sys, importlib.util
spec=importlib.util.spec_from_file_location('ex', r'D:\怀客松\exhibit_ai_employee\_fetch\extract.py')
ex=importlib.util.module_from_spec(spec); spec.loader.exec_module(ex)

urls=[
 'https://www.cdstm.cn/gallery/kxfdj/art/2020/art_1e1409c7767b4a62bef207828bdfb93b.html',
 'https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2020/art_48b013bcec814995bd1dc75a3387bdfb.html',
 'https://www.cdstm.cn/xqq/kkxw/dyd/kxgs/art/2020/art_2384d3f53dfc455d8fb6b36cb9a97923.html',
 'https://www.cdstm.cn/gallery/hycx/hqkxltqyzxgt/art/2018/art_1aec662fcdf64bfa848f224586f059d0.html',
 'https://www.cdstm.cn/zt/xjll/pyj/art/2017/art_c0d56a506e1e4bfeb94f2c6853e1479a.html',
 'https://www.cdstm.cn/theme/khsj/khzx/khqw/art/2022/art_ac89fb7a365746f3a7410f6e7ac246e6.html',
 'https://www.cdstm.cn/gallery/media/mkjx/kxzy/art/2017/art_2a33918478f14adf9da9e1bd40f6247f.html',
 'https://www.cdstm.cn/gallery/media/qkdr/ydy/art/2013/art_6f2ca50813e140649450ede03c8268f3.html',
]
for u in urls:
    try:
        h,f=ex.get(u); t=ex.html_to_text(h)
        print('OK',ex.cjk_count(t),'|',u[-70:])
        print('   ',t[:140].replace('\n',' / '))
    except Exception as e:
        print('FAIL',u[-70:],type(e).__name__,str(e)[:60])
