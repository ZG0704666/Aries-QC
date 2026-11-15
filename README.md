# Aries QC · AI 数据采集与标注质检专员

> slogan：**每一帧都有依据**

「Aries QC」是一个面向数据服务商的 **AI 数据采集与标注质检专员**：把一批原始图像 + 一份采集/标注规范交给它，
它会自主产出 **任务拆解 → 标签体系 → 质检报告（漏标/错标/类别 ID 冲突/误检热点）→ 补采清单**，
并输出可派工、可验收、可审计的交付包。

- 单机运行：本地 Web UI + CLI，数据不出本机。
- 数字全部由脚本计算；模型只做规范编译与文字归纳，绝不冒充真值。
- 每条结论都带可复核证据：图、行号、数值；候选问题必须人工裁定。

---

## 快速开始

```powershell
# 1) 安装依赖（Python 3.10）
pip install -r requirements.txt

# 2) 配置（可选，不配也能跑，只是没有规范编译/摘要）
copy .env.example .env
#   ARIES_QC_BASE_URL / ARIES_QC_MODEL / ARIES_QC_API_KEY  OpenAI 兼容服务
#   ARIES_QC_DATA_ROOT   演示批次根目录（例如 F:\Aries AI\Aries Glass\archive）
#   ARIES_QC_MODEL_PATH  交叉复核权重（ultralytics .pt）

# 3) Web UI（数据质检 / 模型回归门禁）
python server.py --open        # 默认 http://127.0.0.1:8765/

# 4) CLI（跑一批数据并产出交付包）
python run.py --batch "F:\path\to\dataset(hr1)" --spec fixtures\specs\robot_ops.yaml
# 输出目录：runs/<run_id>/
#   report.html / report.md  交付报告
#   findings.json            全部证据明细
#   coverage.json            覆盖度核算
#   classes.json             类别体系与 ID 映射
#   task_plan.json           任务拆解
#   recollect.csv / .json    补采清单
#   fix_diff.json / fixed/   修复预览（不覆盖原文件）
#   evidence/*.jpg           证据缩略图
#   trace.jsonl              审计轨迹
#   delivery.zip             打包后的交付包
```

### 测试

```powershell
python -m pytest tests -q
```

## 模型回归门禁

Web 页面顶部可切换「数据质检」和「模型回归门禁」。回归模式使用仓库内的旧展项 YOLO 验证集，比较基线与候选模型的逐类指标，并展示漏检、错检证据、发布判定、处理建议和可下载的交付包。

在「模型回归门禁」接单台选择数据集、基线和候选档案后，点击「快速演示」即可启动回归。内置 `candidate_v2` 和 `candidate_v3` 均包含退化类别，预期判定为 `BLOCK`；可通过复制并调整候选档案的类别健康度，演示 `WARNING` 或 `RELEASE` 情形。运行产物写入 `runs/reg_<run_id>/`。

此演示使用零 ML 依赖的模拟推理后端，因此无需安装 PyTorch 或 Ultralytics；数据集加载、检测框 IoU 匹配和汇总指标由项目代码计算。模拟得出的 AP50 以 F1 近似，适用于验证门禁交互和流程，不代表真实模型评估结果。真实模型接入不属于当前模拟演示范围。

回归数据集来源于 `qc_engineer` 项目的旧展项样例，已复制到 `fixtures/regression/datasets/`；该大体积目录由 `.gitignore` 排除。回归档案保留在 `fixtures/regression/profiles/`，用于可重复演示。

## 演示数据

仓库不携带大体积图像。演示时把真实批次（约 145MB）放在 `ARIES_QC_DATA_ROOT` 指向的目录，
仓库内只有规范文件 `fixtures/specs/`：

- `robot_ops.yaml` / `robot_ops.md`：怀柔机器人产线一期规范（检测/分割，类别 agv / robotic arm / rail door）。
- `all_batches.yaml`：跨批次合并场景，用于演示类别 ID 冲突（hr1 的 0=agv vs hr2 的 0=sliding door）。
- `missing_spec.md` / `vague.md`：规范缺失/含糊场景，用于演示「停机提问」质量门。

## 工程结构

```
employee/                  核心库
  config.py                .env、批次/规范发现
  dataset.py               YOLO 扫描、CJK 安全读图、批次指纹
  merge_guard.py           跨批次类别表对齐与 ID 冲突检测
  findings.py              Finding 模型 + 几何工具（IoU、鲁棒 z、感知哈希）
  rules.py                 确定性质检规则（格式/坐标/重复/越界/密度/序列/失衡）
  probe.py                 模型交叉复核（候选，不是真值）
  spec.py                  规范编译器（PDF/MD/YAML/JSON，回引原文校验）
  coverage.py              覆盖度核算
  plan.py                  任务拆解（工时/人员/里程碑）
  recollect.py             补采清单（JSON/CSV）
  fix.py                   修复预览与导出（绝不覆盖原文件）
  runner.py                有界 Agent 执行器（trace、质量门、人工介入）
  report.py                HTML/MD/JSON/CSV/证据/ZIP
  provider.py              OpenAI 兼容客户端
server.py                  本地 Web 服务（stdlib HTTP，无框架）
static/                    无构建前端（原生 HTML/CSS/JS）
tests/                     pytest 单元与端到端
fixtures/specs/            演示规范
scripts/                   UI 冒烟测试
```

## 设计原则

1. **确定性优先**：数量、坐标、几何、配额全部脚本计算；模型只能改写文字。
2. **证据链完整**：每条 finding 携带 `check` / `severity` / `confidence` / `subject` / `evidence`，
   报告中出现的每个数字都能在 `findings.json` 里找到对应 id。
3. **候选 ≠ 错误**：模型类结果一律 `confidence=candidate` + `requires_human=true`，不修改数据。
4. **不覆盖原文件**：修复结果写到 `runs/<id>/fixed/`，导出前必须人工确认。
5. **规范缺失就停机提问**：类别表为空或证据回引校验失败时，运行进入 `needs_input`，不自行补造。

## 竞赛材料

- [docs/岗位说明书.md](docs/岗位说明书.md) — AI 员工岗位说明书（1 页）
- [docs/商业模式画布.md](docs/商业模式画布.md) — 八要素商业模式画布
- [docs/演示脚本.md](docs/演示脚本.md) — 5 分钟路演脚本
- [docs/验证报告.md](docs/验证报告.md) — 真实批次实测结果与边界

## 赛前基础声明

本项目使用了赛前已有的资产，特此披露：

- **Label Once**（F:\Aries AI\Label Once）：.NET 10 WPF + Python studio，YOLO 标注/合并/ID 修复，
  提供真实客户痛点来源；本次**未复用其代码**。模型回归门禁实现来自独立的 `qc_engineer` 工程。
- **Aries Glass 数据与权重**（F:\Aries AI\Aries Glass）：hr1/hr2/Underwater 数据集与
  `best.pt`（10 类）权重，作为演示批次的只读数据源与交叉复核权重。
- **旧黑客松工程范式**（F:\Aries AI\hks\exhibit_employee）：stdlib HTTP + 无构建前端 + 证据脚本的
  组织方式；本次**未复用其代码**。

48h 内的新工作：

- 全部 `employee/` 业务库（dataset/merge_guard/rules/probe/spec/coverage/plan/recollect/fix/runner/report）。
- `server.py` + `static/` 本地 Web 接单台、实时轨迹、证据查看、人工裁定、交付下载。
- `run.py` CLI 与 `tests/` 单元/端到端测试。
- 规范编译器、任务拆解、补采清单、修复预览、类别 ID 冲突处理。
- 全部交付材料：岗位说明书、商业模式画布、演示脚本、验证报告。
- 模型服务集成（OpenAI 兼容 + `chat_template_kwargs.enable_thinking=false`）。
"""

