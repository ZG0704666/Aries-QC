import re
h=open('cdstm_search.html',encoding='utf-8').read()
print('--- scripts')
for m in re.finditer(r'<script[^>]*src="([^"]+)"',h):
    print(m.group(1))
print('--- inline mentions of "search" + "?"')
for m in re.finditer(r'[\'"][^\'"]{4,120}(?:search|Search)[^\'"]{0,120}[\'"]',h):
    s=m.group(0)
    if '?' in s or '=' in s: print('  ',s[:180])
