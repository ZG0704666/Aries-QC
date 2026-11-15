# -*- coding: utf-8 -*-
"""把剩余几个空表单字段换成带占位示例的 hintField。幂等：替换后字符串不再匹配。"""
import io

P = "assets/app.js"
s = io.open(P, encoding="utf-8", newline="").read()

PAIRS = [
    ("field('确认人姓名', 'confirmed_by', '')", "hintField('确认人姓名', 'confirmed_by', '')"),
    ("field('审核人', 'reviewer', (p.review && p.review.reviewer) || '')",
     "hintField('审核人', 'reviewer', (p.review && p.review.reviewer) || '')"),
    ("field('签收人', 'signer', (p.acceptance && p.acceptance.signer) || '')",
     "hintField('签收人', 'signer', (p.acceptance && p.acceptance.signer) || '')"),
    ("field('备注', 'note', (p.acceptance && p.acceptance.note) || '')",
     "hintField('备注', 'note', (p.acceptance && p.acceptance.note) || '')"),
]
for a, b in PAIRS:
    n = s.count(a)
    s = s.replace(a, b)
    print("%-46s -> %d 处" % (a[:44], n))

# 页头右上角：原本每屏都挂同一个项目状态 pill，于是「反馈改进」屏也显示「已自测」，
# 跟这一屏在做什么毫无关系。改成按视图给「这一屏自己的状态」；没给就不显示，
# 别再挂一个与当前任务无关的标签。
OLD = """  function header(title, subtitle, meta) {
    const sm = statusMeta();
    return `<div class="page-header"><div><h2>${esc(title)}</h2><p>${subtitle}</p></div>` +
      `<div class="header-meta">${meta || pill(sm[0], sm[1])}</div></div>`;
  }"""
NEW = """  function header(title, subtitle, meta) {
    return `<div class="page-header"><div><h2>${esc(title)}</h2><p>${subtitle}</p></div>` +
      `<div class="header-meta">${meta || ''}</div></div>`;
  }"""
assert OLD in s, "header() 没匹配上"
s = s.replace(OLD, NEW)

# 「内容批准」下面写「未通过」读起来像被驳回，真实状态是「还没人审」。
s = s.replace("pipeline([['内容批准', g.approved ? '已通过' : '未通过']",
              "pipeline([['内容批准', g.approved ? '已通过' : '未批准']")

# 「真实台账」不是状态，是自证清明的标签，删掉。
s = s.replace("${pill('真实台账', 'green')}", "")
# 「运行事件」卡上的「真实记录」同理。
s = s.replace('<span class="micro-tag">真实记录</span>', '')

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("done")
