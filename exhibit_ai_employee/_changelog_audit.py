"""回写「全面审计」到 CHANGELOG 头部（幂等：已含标记则跳过）。"""
from pathlib import Path

path = Path(__file__).parent / "CHANGELOG.md"
marker = "全面审计：对齐 / 设计 / 功能"
text = path.read_text(encoding="utf-8")
if marker in text:
    print("已存在，跳过")
    raise SystemExit(0)

entry = """# CHANGELOG

## 全面审计：对齐 / 设计 / 功能 — 2026-11-15（CODE_REV studio-2026-11-15-n）

新增 `_audit_full.py`：用 `_fixture.py` 现场造一个真实形状的夹具项目（3 展项 + 3 段已合成音频 + 自测结果），
再起临时服务用 Playwright 逐视图逐交互实测，**77 条断言全部通过**（功能 49 / 对齐 12 / 设计 16）。
报告落在 `_ui_shots/audit-full.txt`，不用肉眼判断、不凭感觉下结论。

### 审计发现的真问题（已修）

- **金额框留空会拒掉整次提交**：`apply_quote` 对空字符串直接走 `float('')` 抛「必须是数字」，
  用户点「更新测算」时只要有一个金额框没填，**已填的报价一分钱都没存进去**。
  现在空字符串视为「未填」跳过；负数、非数字仍 400。
- **发布门禁前后端不一致**：前端 `gates()` 列 5 项，后端 `publish` 只挡 2 项（审核、自测），
  缺音频、有待核验引用、审核签名对不上当前版本都能直接发布，交付包里会缺 MP3。
  现在后端补齐：审核 `review.version` 必须等于当前版本、`issues` 必须为空、每个展项都得有音频登记。
- **重复签收会覆盖原结论**：`record_acceptance` 不拦第二次提交，客户点两下能把「已签收」改成「已拒收」。
  现在同一人同一结论重发算幂等成功；换结论或换人返回 403，要求先发布新版本。
- **前端 `gates().approved` 不看版本**：审核通过是 v0.2，内容改到 v0.3 后前端仍显示「已批准」、放行发布按钮。
  现在前后端用同一判据；发布屏在「签名是旧版本」时明确写「审核签名是 vX，当前 vY，需重新审核」，
  阻断原因也补上此前漏掉的「资料授权未登记」。
- `_api_checks.py` 的种子项目没有音频记录，被新门禁拦下属预期；补一条音频记录并新增「缺音频时发布被拦」断言。

### 审计脚本自身的判据修正

- live 视图的页头标题与副标题是**同行 baseline 排列**（`refinement.css` 特判），
  按「垂直间距」量会算出 −24px 的负数误判；现在识别为同行排列，其余六屏间距极差 0px。
- 走查时审计会主动提交非法输入（空白金额框等），产生预期的 400，
  不再计入「零 JS 错误」；真正的 `pageerror` 仍然算 FAIL。
- `_probe_export.py` 是一次性探针，写死了已删除项目 `7e1c974ff8`，404 与本次改动无关；
  导出能力由 `_audit_full.py` 的「导出交付稿 .md / 交付包 .zip（判 PK 头）」覆盖。
- 顺手修 `assets/app.js` 的 `S.exhibitsIndex = 0` 拼写（删除项目后重置选中展项用，应为 `S.exhibitIndex`）。

### 全量回归

`_audit_full` 77/77、`_ui_checks` 51/51、`_ui_layout` 25/25、`_probe_empty` 34 项、
`_api_checks` 25/25、`_auth_checks` 13/13、`_audit_checks` 11/11、`_duration_checks` 8/8、
`_check_real_copy` 长句 0 条 console 错误 0、`_probe_overflow` 无溢出、`_probe_live` 无 JS 错误。

"""
path.write_text(entry + text.split("\n", 1)[1], encoding="utf-8", newline="\n")
print("已写入 CHANGELOG")
