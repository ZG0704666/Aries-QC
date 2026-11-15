import re
h=open('kepu_search_https.html',encoding='utf-8').read()
print('len',len(h))
i=h.find('searchWord')
print(h[max(0,i-500):i+3000])
print('\n\n=== ALL HREFS ===')
for l in re.findall(r'href="([^"]+)"',h)[:80]:
    print(' ',l)
