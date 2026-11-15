import re
h=open('cdstm_search.html',encoding='utf-8').read()
# find lines around 'searchList' or 'result'
for kw in ['searchList','resultList','js_list','search-result','tpl','render','pageSize','searchJson','param','$.ajax','fetch(','XMLHttp']:
    idx=[m.start() for m in re.finditer(re.escape(kw),h)]
    print(kw, len(idx))
print('---- around 查询范围 tail 120 lines')
plain=re.sub(r'<[^>]+>','\n',re.sub(r'<script.*?</script>','',h,flags=re.S))
lines=[l.strip() for l in plain.split('\n') if l.strip()]
for l in lines[120:200]: print('|',l[:120])
