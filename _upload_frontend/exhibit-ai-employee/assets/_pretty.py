import io
import re

src = io.open('app.js', encoding='utf-8').read().splitlines()
out = []
for idx in range(31, 58):
    text = src[idx]
    depth = 0
    out.append('===== LINE %d =====' % (idx + 1))
    for part in re.split(r'(?<=>)(?=<)', text):
        if re.match(r'</', part):
            depth = max(0, depth - 1)
        out.append('  ' * depth + part.strip())
        if re.match(r'<[a-zA-Z]', part) and not part.rstrip().endswith('/>') \
                and not re.match(r'<(br|img|input|hr)\b', part):
            depth += 1
io.open('_views_pretty.txt', 'w', encoding='utf-8').write('\n'.join(out))
print('lines', len(out), 'chars', sum(len(x) for x in out))
