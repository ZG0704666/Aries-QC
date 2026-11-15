# 展览语音体验交付员：能力、部署与验收

本目录包含展览语音体验交付员原型、岗位材料与验收脚本。A/B/C 展项资料是模拟输入，不是客户资料或真实展品事实。当前页面面向电脑浏览器演示；没有眼镜实机连接、传感器输入或实机播放验证。

## 能力与证据边界

- **当前后端能力**：任务生成与历史、来源/证据引用、缺项和冲突校验、版本修订及 diff、人工审核门、测试记录存取、反馈候选记录与受审核限制的导出。具体结果以本次 API 响应及持久化记录为准；接口成功本身不等于内容正确或客户验收。
- **电脑端模拟器**：页面用浏览器内状态模拟空闲静默、多目标待手动选择、播放中，以及手动切换时的停止/开始顺序。单目标不会自动播放，多目标提示选择而不猜意图；播放中切换作为事件处理。这个确定性状态机是前端演示逻辑，不是 AI 能力，也不证明硬件事件或真实音频设备行为。
- **设备分层**：当前已有的是浏览器界面与模拟状态；本次能力不包括眼镜实机、定位/识别传感器、设备端音频控制或现场冷却/防重播验证。硬件适配、传感器接入及现场验收属于未来工作，完成前不得描述为已上线眼镜。
- **demo/live**：以 `GET /api/health` 的 `mode` 为准。`demo` 使用模板结果，不是模型交付证据；`live` 代表后端按当前配置走真实模型调用路径，仍须逐项核验模型输出、来源和审核。健康状态中的 `demo_is_delivery_evidence` 为 false。
- **两套链路，音频能力不同**：本目录存在两套后端，不得混谈。
  - **Studio 工作台**（`studio_server.py` + `studio_web.html` + `tts.py`）：**已接入真实 TTS，可产出 MP3**。
    `GET /api/studio/health` 的 `tts` 字段给出引擎是否就绪。默认引擎 edge-tts（`zh-CN-XiaoxiaoNeural`），
    离线兜底 Windows SAPI。**edge-tts 是免费接口，无 SLA、无商用授权确认**，正式交付前须替换为馆方指定
    引擎或购买授权的商用服务。
  - **旧链路**（`app.py`）：`build_package()` 生成的交付包**仍不含任何音频文件**，首行固定声明不完整。
- **有音频不等于已验收**：合成成功只证明文件产出，不证明音色、语速、断句符合馆方要求，也不证明设备端
  播放正常。音频的 `sha256` 与字节数可核对，但不能替代听感验收。

## 部署与运行

服务单元模板 `exhibit-ai.service` 将监听地址设为 `127.0.0.1:4181`、`DEMO_MODE=true`，工作目录设为 `/opt/guikesong/exhibit-ai`，数据库设为 `/var/lib/exhibit-ai/employee.sqlite3`。这些是配置模板，不证明服务已安装、启动或对外可访问。该模板默认是 demo；启用 live 需由运维按实际环境配置模型地址、模型名和密钥，并执行本地安全与连通性检查。本次文档更新没有部署或验证任何运行中的环境。

### 访问口令

**部署到非本机环境时必须设置 `ACCESS_TOKEN`**，否则 `/api/*` 全部无鉴权，任何人都能调用生成、审批和导出，消耗模型额度。

```bash
# 服务端
export ACCESS_TOKEN='<强随机串>'
python3 app.py
```

- 所有 `/api/*` 请求需带 `X-Access-Token` 头或 `?token=` 参数，否则返回 401。
- 静态页 `/` 不需要口令（页面本身不含数据）。
- 前端页面在收到 401 时会显示口令输入框，也可直接用 `/?token=<口令>` 打开。
- 口令通过 systemd `EnvironmentFile=-/etc/exhibit-ai.env` 注入，不写进单元文件，避免随代码提交。

本机启动后可用浏览器访问部署的页面；运行验收脚本前先确认目标地址及模式：

```powershell
$env:EXHIBIT_BASE_URL = 'http://127.0.0.1:4181'
python scripts/acceptance.py
```

脚本将报告追加到 `acceptance-results.jsonl`；参数见 `python scripts/acceptance.py --help`。验收会产生运行记录，live 检查会调用模型。不要对生产服务运行验收或对抗探针。

## API 契约与验收口径

按当前 `app.py` 核对的接口：

- `GET /api/health` 返回模式、模型/凭据配置状态及 `demo_is_delivery_evidence`。
- `POST /api/generate` 接收 `title` 和 `exhibits`（列表，每项含 `exhibit_id`（须为 A/B/C）、`source_name`、`source_text`，每项来源至少 10 字），返回 `id`、`mode`、`status`、`draft`、`validation`。**资料缺料或存在来源冲突时在生成前返回 409**，`generated=false`、`approval_allowed=false`，不产出任何草稿。
- `GET /api/runs`、`GET /api/runs/{id}/versions`、`GET /api/runs/{id}/events` 分别读取任务、版本/diff、事件；`POST /api/revise` 提交完整 `draft` 与 `run_id`，返回新版本和 diff。blocked/failed 任务不允许 revise。
- `POST /api/review` 接收 `run_id` 与 `decision`（`approved` 或 `needs_revision`）；**审批请求不得携带 `draft`**（改稿须走 `/api/revise`），质量门未通过时不能批准。demo 任务可走完流程，但状态记为 `approved_demo`，导出包会强制加 DEMO 水印。`GET /api/runs/{id}/export` 只在审核与质量门通过时返回 7 个文件的真实内容。
- `GET /api/runs/{id}/tests` 返回 `{run_id, tests:[...]}`（每条记录含 `run_id`）。`POST /api/runs/{id}/tests` 接收 `{number,status,input,expected,actual,version?}`；`status` 为 `passed`、`failed` 或 `not_run`。服务端 T3 若记为 `passed`，要求 `actual.events` 是结构化事件数组，按序包含 `{event:"selected",exhibit_id:"B"}`、`{event:"stopped",exhibit_id:"A"}`、`{event:"started",exhibit_id:"B"}`，并且 `actual.no_overlap` 为 `true`。
- `GET/POST /api/feedback` 管理人工待审的改进候选；它不是自动学习。
- 商业闭环：`GET/POST /api/customers`、`/api/quotes`、`/api/acceptances`，以及 `GET /api/ledger`（客户数、报价按 假设/已访谈/已签约 分组、签收笔数与金额、复购客户数）。签收须有人签署且任务已过审，否则 409。

## 程序化质量门（已实现，非规划）

质量门全部为确定性代码，不依赖模型自评。判定入口是 `app.validate_draft`，回归集是 `gates.py`（11 条用例，含 3 条反误伤用例）。

| 门 | 作用 |
|---|---|
| 覆盖门 | 必须且只能有 A/B/C 各一份内容 |
| 引文门 | 出处必须在本展项资料中逐字定位 |
| 串台门 | 展项 A 的出处不得来自展项 B 的资料 |
| 出处映射门 | 每条 fact 的 claim 必须包含在 source_quote 中且可回溯 |
| **反向覆盖门** | 讲解每个实义句都要命中某条 claim/引用，或标注待确认——防止"一条真出处 + 补写编造" |
| **中文数字门** | 「一九五零年」「三十厘米」等中文数字必须在原文出现 |
| **中文专名门** | 机构名（厂/馆/院/所…）与朝代名必须在原文出现 |
| 阿拉伯数字门 | 数字必须能在原文找到 |
| 缺料门 | 显式缺项标记，或实义内容少于 40 字 |
| 冲突门 | 显式冲突用语，或同一展项出现两个不同年份（含中文数字） |
| 长度门 | 讲解 120–240 字（约 30–60 秒） |

运行回归集：

```powershell
python gates.py          # 11/11 通过表示无回归
```

页面选择任务时会从服务端恢复测试记录；T2/T3 的浏览器模拟结果会尝试保存，保存成功或失败都会显示状态。T3 上报结构化的 `selected(B) → stopped(A) → started(B)` 事件和 `no_overlap` 判定，服务端仍会独立校验保存条件。浏览器状态机只证明电脑端模拟行为。`scripts/acceptance.py` 的 T2/T3 仍标为 `BLOCKED`，因为 HTTP 验收脚本不采集浏览器模拟器事件；脚本中的 BLOCKED 与浏览器本地模拟结果是不同层次的记录。

脚本中 T1/T4/T5/T6/T8、P1/P2 的 live 项需真实 live 后端；demo 下记为 `NOT_RUN`，不以模板输出通过。T7 在隔离子进程中验证拒绝连接和缺少凭据。T9 需有关联的 live T1 run，并检查导出接口和模板文件；demo 导出不构成证据。以上 HTTP 验收不验证眼镜实机、现场传感器、真实设备切换或客户签收。每轮报告必须根据实际响应记录，不预填通过结论；建议至少运行三轮，并保留 JSONL 记录。

## 交付材料边界

`deliverables/` 是七项可打开的交付模板，不代表已生成真实项目交付包。`interviews/` 是访谈提纲，目前不包含访谈记录。`business/` 中金额与工时待填，假设价只用于验证表格设计，不是商业结果。尚待确认的能力和项目事实以材料中的标注为准。
