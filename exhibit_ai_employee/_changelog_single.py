# -*- coding: utf-8 -*-
"""CHANGELOG 顶部追加「单展项独立执行单元」一节。幂等。"""
from pathlib import Path

p = Path(__file__).resolve().parent / "CHANGELOG.md"
text = p.read_text(encoding="utf-8")
marker = "## 单展项独立执行单元"
if marker in text:
    print("already present")
    raise SystemExit(0)

block = """## 单展项独立执行单元 — 2026-11-15（CODE_REV studio-2026-11-15-o）

起因：所有指令都走左侧聊天框，「重做某一个展项」只能在对话里喊。改成 Codex 式的独立执行单元：每个展项有自己的操作、进度、产物，不靠对话驱动。

### 后端
- 抽出 `generate_exhibit(project, unit, index, research_mode)`（`studio_server.py:410`）：整批与单个共用同一条生成路径，模型失败置 failed 返回 None。
- 新增 `run_single_exhibit(project_id, exhibit_id)`（`studio_server.py:467`）：只替换目标展项，其余原样保留；版本 +0.1、`review=None`（内容变了旧签名不能沿用）、自测重跑；发 `run.finished` 事件带 exhibit_id。
- `run` 路由支持 `exhibit_id` 参数：传了走单展项，展项不存在 404，返回 202。

### 前端
- `exhibitTray()` 瓦片从一整颗 button 改成 div（button 不能嵌套 button）：`.exhibit-pick`（标题区切换展项）+ `.exhibit-ops`（`run-one` 重做、`synth` 合成/重合成两个独立按钮）。
- `doRunOne(exhibitId)`：`S.pendingRun = exhibitId`（字符串，整批仍是 true），POST run 带 exhibit_id；生成中的瓦片 `is-running` 黄底呼吸标识。
- 图标一律 `::before` 伪元素，按钮里只写文字——不用 `font-size:0` 藏字（审计不允许 0px 字号）。

### 实测（真模型，非断言代码存在）
- `_check_single_exhibit.py` 11/11：只重做 EX02，其余 EX01/EX03/EX04/EX05 讲解文本一字未动，版本 0.2→0.3，review 清空，展项总数不变，零 JS 错误。
- content 屏 5 张瓦片一行、高度 205→133px；live 屏窄栏 3+2 排列合理。

### 回归
`_audit_full` 77/77（F49 A12 D16）、`_ui_checks` 51/51 零 JS 错误、`_ui_layout` 25/25、`_check_skill_applied` 14/14、`_api_checks` 25/25、`_probe_empty` 34/34。

"""
p.write_text(block + text, encoding="utf-8", newline="\n")
print("changelog updated")
