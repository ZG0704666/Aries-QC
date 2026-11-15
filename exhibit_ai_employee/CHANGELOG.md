## 内容气质：展签式正文 · 图录式引用 · 阶段条仪式感 — 2026-11-15

方向：记忆点不靠装饰，靠给「内容」一套区别于「界面」的排版语言。界面保持 sans-serif，展品文字用宋体族——这是展览图录的做法。

### 落地（只在 studio.css 末尾追加，不改 JS）
- **内容字体分家**：`.script-body` / `.quote p` / `.fact-item p` 用宋体族（Songti SC / STSong / SimSun / Noto Serif CJK SC / serif），UI 其余保持 sans。界面是界面，展品文字是另一套字体。
- **展签式正文**：首行缩进 2em、行高 2.05、左对齐（中文不 justify——窄栏两端对齐会拉散字距）；标题下一道细展签线。
- **图录式引用**：左侧 2px 绿色竖线、大号衬线引号、斜体引用文、「原文引用」小字大写感；来源编号保持等宽与斜体形成材质对比。
- **阶段条仪式感**：当前段（`.pipeline li.current`）下缘一道短刻度线。

### 判据修正
- 正文原设 `text-align:justify + inter-ideograph`，窄栏字距被拉散 → 改回左对齐，保留首行缩进即可表达展签气质。
- 阶段条类名是 `.current`/`.done`（非 `.is-current`/`[aria-current]`），选择器先查实际类名再写。

### 回归
`_audit_full` 77/77（F49 A12 D16）、`_ui_layout` 25/25、`_ui_checks` 51/51、`_check_skill_applied` 14/14。

## 单展项独立执行单元 — 2026-11-15（CODE_REV studio-2026-11-15-o）

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

# CHANGELOG

## 密度与层级 — 2026-11-15（CODE_REV studio-2026-11-15-n）

承接「前端如何」的自评：工程扎实但视觉只是干净——信息密度低、层级平。
这一轮不加装饰，只收紧容器、把版面还给内容。

### 先量后改

新增 `_probe_density.py`：对 live / content / project / release 四屏量
panel / panel-pad / panel-header / exhibit-tray / pipeline / paper 的
padding、margin、宽高，并列出垂直方向 padding+margin ≥40px 的元素。

读数：`panel-pad` 24px、`panel-header` 24px、paper 上下 52px、
exhibit-tray 上下 40px、pipeline 上下 48px，嵌套卡片还要叠两层。
问题不是元素太小，是**统一的大 padding 把内容稀释了**。

### 改动（全部只追加到 assets/studio.css 末尾，可回退）

1. 面板内边距 24 → 16，标题区 24/10 → 16/8。
2. 讲解正文：paper 上下 52 → 32，正文限宽 36em → 44em，行高 1.9。
   字号不动，触控目标仍 ≥44px。
3. 展项托盘上下 40 → 24。
4. 阶段条上下 48 → 32，等分不变。
5. 层级只加强「当前」与「阻断」：当前展项绿描边 + 左侧 3px 色条 + 标题深色；
   阻断通知左侧 3px 红条、通过通知左侧 3px 绿条。普通卡片不加装饰。
6. 门禁/明细/成本行上下 12 → 8。
7. 面板圆角 16/12 → 10。

### 过程中发现并解决的一个布局问题

展项托盘原来是 `minmax(180px,1fr)`，806px 宽只够 4 列，
5 个展项排成 4+1，第二行只有 EX05 一个，右侧四分之三空着。
降到 `minmax(150px,1fr)` 后 5 张一行：

- 托盘高度 251 → 148px，面板 301 → 198px，**省出 103px**。
- 代价是瓦片标题折成三行（「EX01 她是/谁：乔孔多的/妻子丽莎」）。
  信息完整、选中态明确，比孤行浪费半屏好，**保留这个取舍**。

### 一个指标教训

`_visual_audit.py` 的「留白率」在改动前后几乎没变（88~90%）。
原因是它把顶栏、侧栏、卡片底色全算进留白，padding 收 8px 在整屏像素里看不出。
**有意义的指标是内容高度与一屏能否读完正文**，不是全屏留白百分比。
以后评估密度改动，量目标容器的高度变化，不看全屏留白率。

### 验证

- `_audit_full.py` 77/77（功能 49、对齐 12、设计 16）
- `_check_skill_applied.py` 14/14
- `_ui_layout.py` 25/25（五宽度无横向溢出、字号仍在 6 档阶梯）
- `_ui_checks.py` 51/51 零 JS 错误、`_probe_empty.py` 34/34
- 真实项目「蒙娜丽莎」截图复核：live 正文一屏读完、content 五张瓦片一行、
  project 表单与报价一屏放下。

## 真正使用 ui-ux-pro-max skill — 2026-11-15（CODE_REV studio-2026-11-15-n）

上一轮只用了它的规则表当尺子，没跑数据库，被问「设计 skill 用了吗」时答不上来。
这一轮先查清楚为什么跑不了，再真跑、真落地、真验证。

### 缺文件的原因

`~/.agents/skills/ui-ux-pro-max/` 下的 `data`（31 字节）和 `scripts`（34 字节）
**不是目录，是两个纯文本文件**，内容分别写着 `../../../src/ui-ux-pro-max/data` 和
`../../../src/ui-ux-pro-max/scripts`——Git 符号链接在 Windows 未启用 `core.symlinks=true`
时被 checkout 成了文本指针。之前用 `Get-ChildItem -Recurse` 看到「空」就当成空目录，是误判；
要看 `Mode` 列（`-a----` 是文件，`d-----` 才是目录）。

### 恢复方式

上游是 `nextlevelbuilder/ui-ux-pro-max-skill`（MIT）。本机只有 api.github.com 通，
用 tarball 端点拉源码，把真正的 `scripts/`（search.py / core.py / design_system.py）
和 `data/`（16 个 CSV：styles / colors / typography / products / ux-guidelines …）
复制进技能目录，替换掉两个占位文本文件。`search.py --help` 与 `--design-system` 均跑通。

### 真实输出与取舍

- `--design-system` 给出 **Data-Dense Dashboard**：行 hover 高亮、数据加载 spinner、
  hover 150–300ms、cursor-pointer、对比度 4.5:1、reduced-motion。
- `--domain ux`：可点元素要有 hover 反馈、长内容截断+展开、input 必须配 label、
  表格用 overflow-x-auto 包裹、大数字加千分位、正文行高 1.5–1.75。
- `--domain color` 首推 **navy `#1E3A5F` + green `#16A34A`**，与现有
  `--ds-navy #132541` / `--ds-accent #16815f` 同族，**配色方向确认，不换**。
- 不照抄的部分：返回的 Pattern 是「Enterprise Gateway」营销官网结构，与工作台形态不符；
  推荐字体 Fira Code / Fira Sans 不适合中文正文。只取可量化的交互与排版规则。

### 落地（assets/studio.css 末尾，全部走 token）

1. 行 hover 高亮：表格行、反馈项、展项瓦片、门禁行、成本行、运行事件，
   150ms 过渡，包在 `@media (hover:hover)` 里，触屏不依赖 hover。
2. 等宽数字：金额、指标、时长、编号统一 `font-variant-numeric: tabular-nums`。
3. 折叠指示：summary 统一 CSS 三角，随开合旋转。
4. 生成中反馈：`pendingRun` 时主按钮显示 spinner，pending 气泡头像慢转，
   `prefers-reduced-motion` 下全部静止。

### 过程中修掉的一个真缺陷

折叠箭头第一次上线后出现**双箭头 + 换行**：`styles.css` 给
`.file-tree summary::before` 写过字符 `'›'`、展开时是 `'⌄'`，
`workspace-tools.css` 给 `.event-history > summary::before` 也写过 `'›'`。
这些选择器比 `details > summary::before` 更具体，**后加载也压不住**，
新画的 CSS 三角和旧字符叠在一起。修法是对这两处用同等级或更具体的选择器把
`content` 一并收回；`.file-tree summary` 的 grid 三列布局单独保留，不能被改成 flex。
同时删掉 `app.js` 里文件树 summary 手写的 `▤` 装饰字符。

教训：改组件级样式前先把**命中同一伪元素的全部规则**列出来
（遍历 `document.styleSheets` 的 `cssRules`），别只看自己新增的那份文件。

### 验证

新增 `_check_skill_applied.py`（14 条）：真的 hover 量背景色变化、量过渡时长、
量等宽数字、量箭头边框宽度与旋转矩阵、量 summary 单行高度、量文件树 display 仍是 grid、
量 spinner 的 animationName，七视图无横向溢出、零 JS 错误。
全量回归：`_audit_full.py` 77/77、`_ui_layout.py` 25/25、`_ui_checks.py` 51/51。

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


## 3.3.0 — 2026-11-15（接入真实 TTS，交付包含真实音频）

此前 `04_音频` 只有一句「本包不完整：不含任何音频文件」，岗位名为「语音体验交付员」却从不产出音频，
是整个交付里最大的缺口。本次接入真实合成，并已在真实项目上跑出三个展项的 MP3。

### 引擎

- 新增 `tts.py`，双引擎按序降级：**edge-tts**（微软神经网络音色，默认 `zh-CN-XiaoxiaoNeural`，联网、无需密钥）
  → **Windows SAPI**（`Microsoft Huihui Desktop`，离线兜底，音质明显较差）。
- 显式指定 `engine` 时**不降级**，避免把低音质产物当成高质量交付；只有 `auto` 才回落。
- 指定引擎失败、网络不可达、返回字节不是合法 MP3 帧，一律抛 `TTSError`，不写占位文件、不静默成功。
- 无 ffmpeg 时 SAPI 交付 WAV，并在元数据里如实写 `format=wav`，不谎称 MP3。

> 实测：`edge-tts` 7.2.8 合成时报 `WSServerHandshakeError 403`，升级到 7.3.1 后正常。
> 旧的 `edge-tts` 版本会因微软接口变更而静默不可用，部署时应锁 7.3.1 以上。

### 接口

- `POST /api/studio/projects/{id}/voice`：从「只记一条试听事件」改为**真正合成并落盘**。
  - 只允许合成当前草稿里真实存在的主讲解；文本与草稿不一致返回 409，防止任意文本走 TTS 通道。
  - 展项不存在返回 404。合成失败返回 502，事件表记 `ok:false`。
  - 返回 `filename / bytes / sha256 / engine / voice / chars / elapsed_ms`。
- `GET /api/studio/projects/{id}/audio/{filename}`：下发音频。只放行该项目已登记的 `filename`，
  未登记或路径穿越一律 404。
- `GET /api/studio/health` 增加 `tts` 字段（引擎可用性、默认音色、是否就绪），前端据此展示真实能力。
- 文件名含内容哈希前缀（`EX01-24a7afaeb965.mp3`），文本一改必然换名，浏览器不会缓存到旧音频。

### 前端

- 「朗读」按钮改为播放服务端合成的真实音频，状态如实显示「播放中 · MP3 259 KB」；
  自动播放被拦时显示「已合成，需手动播放」，不谎称已试听。
- 面板原本固定写「本机未接入馆方 TTS，朗读使用浏览器语音合成」，已改为读 `health.tts` 的实际结果。
- 修复切换展项不刷新文本的缺陷：切换后仍提交上一个展项的文本，被服务端一致性门 409 拦下。
  现在 `change` 时重绘，并按 `project.audio` 显示「已有音频 / 未合成」。

### 交付稿

- 导出 Markdown 增加音频段：已合成则写出 `文件名｜引擎｜格式｜字节数｜sha256` 前 16 位；
  未合成则明写「未生成（不可视为已交付音频）」。首部总述「全部展项均已合成 / 不完整——缺 X、Y」。

### 实测结果（真实项目 `7e1c974ff8` v0.2，edge-tts）

| 展项 | 文件 | 字节 | 时长 | 耗时 |
| --- | --- | --- | --- | --- |
| EX01 光的折射 | `EX01-24a7afaeb965.mp3` | 265,680 | 44.28 s | 2,453 ms |
| EX02 声音的传播 | `EX02-2f24ed7b3c13.mp3` | 321,552 | 53.59 s | 2,671 ms |
| EX03 颜色的奥秘 | `EX03-d6d14d19a728.mp3` | 274,176 | 45.70 s | 2,828 ms |

- `ffprobe` 校验三个文件均可解码；下载接口 200 / `audio/mpeg`。
- 安全分支实测：篡改文本 409、不存在展项 404、未登记文件名 404、`../studio.sqlite3` 404。
- 回归：`gates.py` 11/11、`_audit_checks.py` 10/10。

### 仍未解决

- **SAPI 兜底未做主观音质验收**：只在无网时用，未与 edge-tts 做过听感对比。
- **未接入馆方/商用 TTS**：edge-tts 是免费接口，无 SLA、无商用授权确认，正式交付前须替换为馆方
  指定引擎或购买授权的商用服务。这一点不得在路演中模糊。
- **未做音频与文字的时长一致性校验**：45 秒是文本字数推算，实测 EX02 为 53.6 秒，与 `content_tests`
  的字数门（80~400 字）不联动。
- 音频目录已加入 `.gitignore`，不随代码提交；交付时需单独打包。
- 眼镜实机仍未接入，设备端播放未验证。

## 3.2.0 — 2026-11-15（Studio 审批门与审计隔离修复）

以下每条均已在 `STUDIO_PORT=4183` 的数据库副本实例上实测，未改动 `studio.sqlite3` 中的真实项目。

### 审批署名校验在服务端缺失（可绕过）

- 复现：`POST /api/studio/projects/{id}/review`，`reviewer` 传空串或纯空白，`decision=approved`，
  返回 200 并写入 `reviewer="未署名"`。前端 `review()` 只在浏览器里拦空值，直接调接口即可绕过。
- 影响：审批结论会进入导出交付稿与验收凭证，"谁批准的"这一栏可以是空的。
- 修复：`reviewer` 去空白后在服务端校验，为空即 400；批准与退回都要求署名。
- 复测：空白署名批准 400、空署名退回 400、正常署名批准 200、旧版本（0.1）批准 409、
  测试未全通过批准 409（`_audit_checks.py` 与 `gates.py` 同步回归，11/11 与 10/10 全过）。

### 审计脚本污染生产库

- 复现：`_audit_checks.py` 调用 `S.seed(project_id="auditfix")`，而 `studio_server` 用的是真实
  `studio.sqlite3`。每跑一次就写入一个 `exhibits=0` 的空项目，`updated_at` 最新，于是前端
  `boot()` 取 `projects[0]` 时加载这个空项目——页面表现为「定位原文」按钮 0 个、知识卡 0 张、
  自测 5/7 不过，看起来像页面逻辑坏了，实际是数据被审计脚本污染。
- 修复：脚本在 `import studio_server` 之前把 `STUDIO_DB` 指向系统临时库，并调用
  `S.initialize()` 建表。实测跑完后真实库项目与事件数不变。

### 已完成的端到端走查（真实项目 `7e1c974ff8`，v0.2）

- 来源定位：定位到 `SRC-001·P003`，引用在段落中高亮 1 处，`locateMatch` 显示「逐字原文，一字不差」。
- 知识卡：5 张事实卡，全部「已核验 / 逐字可定位」。
- 自测：7/7 通过，审批按钮在自测前禁用。
- 试听：3 个展项可选，主讲解 205 字，点击后状态回写「试听中」（浏览器朗读，不产出音频文件）。
- 导出：`GET .../export` 返回 200 / 5109 字节，含三个展项正文、简化版与逐条事实出处。

### 仍未解决

- 真实项目库里残留 `auditfix` 空项目（本次未删除，删除需你确认）。它会因更新时间最新而被
  前端当作默认项目加载，演示前应在页面上选中真实项目，或经你确认后删除该行。
- 无 TTS 接入，试听只有浏览器朗读，交付包不含音频文件。
- 未接入眼镜实机，设备相关结论仍为模拟。

## 3.1.0 — 2026-11-14（按商业审计修复）

审计报告：`设计文档\审计_商业化.md`。以下每条均已实际运行验证。

### 致命问题 ①：付费逻辑只活在文档里 → 已有可查询的数据落点

- 新增 `customers`、`quotes`、`acceptances` 三张表，`runs` 增加 `customer_id` 列。
- 新增 `POST/GET /api/customers`、`/api/quotes`、`/api/acceptances`。签收必须有人签署，
  且任务须已通过审核，否则 409——未签收不能计入成交。
- 新增 `GET /api/ledger`：客户数、报价数（按 假设/已访谈/已签约 分组）、签收笔数与金额、
  复购客户数全部来自数据库，**"0 访谈 0 成交"这个事实从接口即可看见**，不靠口头解释。
- 前端新增「07b 成交台账」区块，可直接登记与查看。

### 致命问题 ②：会输出一个骗人的毛利率

- `margin_percent` 改名为 `contribution_ratio`，并注明它不是毛利率。
- **报价未签约（basis != signed）时一律返回 null** 并给出阻断原因，不再用假设价算利润率。
- 新增双保本价：`cash_breakeven`（只算现金支出）与 `full_breakeven`（含团队人时）。
  实测同一输入下两者为 150 与 750，差 5 倍——只给一个必然答错"最低多少钱能接单"。
- 效率对照增加 `baseline_scope` / `employee_scope` / `sample_n`；两端口径不一致时返回
  `scope_mismatch` 并**拒绝计算节省**，不再拿不同范围的数字相减。
- `api_calls` 表新增 `prompt_tokens` / `completion_tokens`，模型成本可由账单推算而非手填。

### 致命问题 ③：客户付钱拿到的关键文件是空的

- `05_场景测试记录.md` 改为读取 `test_records` 生成真实表格（用例/状态/版本/模式/时间），
  并明确列出未运行用例；无记录时如实写"本次运行没有任何测试记录"，不假装通过。
- `06_修改差异与待解决问题.md` 改为读取 `versions.diff` 输出真实差异内容
  （兼容 unified diff 字符串与结构化 dict 两种格式），并列出五项待解决问题。
- `07_客户审核与验收单.md` 改为结构化验收单：五条验收项逐条状态 + 验收金额栏 +
  付款节点 + 签收人/日期栏 + 硬件上线免责声明。**这是可签收、可触发收款的凭证。**
- `04_音频/README.md` 首行改为「本包不完整：不含任何音频文件」，并写明降级交付
  须客户书面注明 `accept_degraded=true`。不再用固定串掩盖"卖语音却不产出音频"。

### 验收脚本修复

- `load_sources()` 返回 list（服务端要求 `exhibit_id` 形式），修复此前所有用例
  拿到 400「必须提交 A、B、C 三个独立展项资料」的问题。
- 新增 `clean_sources()`：T7/P3 探针改用无缺料无冲突的资料，确保请求能走到
  模型调用与审批路径，而不是在生成前被 409 拦下。
- T4/T5/P1/P2 判据改为匹配服务端真实的 409 + 顶层字段契约。
- `/api/runs/{id}/tests` 每条记录补 `run_id`，使回读校验可逐条核对。

### 前端

- 新增成交台账区块与 `approved_demo` 状态标签（此前显示原始英文状态）。
- 经济模型面板改为展示现金成本 / 全成本 / 双保本价 / 贡献率阻断原因 /
  客户现状成本对照 / 口径不一致告警。

### 仍未解决（不掩盖）

- 无真实模型凭据，live 模式生成质量完全未验证；demo 是摘句模板，不是 AI 产出。
- 未接入眼镜实机，所有设备相关结论均为模拟。
- 时长仍靠手工填写，未从事件日志自动汇总。
- 改进候选仍是模板串，不是 AI 自我改进，路演不得如此表述。

## 3.0.0 — 2026-11-14（按技术审计修复）

审计报告：`设计文档\审计_技术缺陷.md`。以下每条均已实际运行复现并验证修复。

### P0 修复

- **伪造事实可通过质量门**：新增中文数字门、中文专名门、反向覆盖门（讲解每句须命中某条事实或引用，或标注待确认）。复现用例"一九五零年 / 郑州机床厂"现被 3 道门同时拦下。
- **冲突门漏检**：`CONFLICT_MARKERS` 补入"相互冲突""存在冲突""有出入"等；新增中文数字年份识别（一八五零 → 1850）。
- **缺料门在生成前才检出**：资料缺料或冲突时返回 409，`generated=false`、`approval_allowed=false`，不产出任何草稿。
- **并发 revise 触发 500 并丢更新**：版本号改为 `BEGIN IMMEDIATE` + `UPDATE ... RETURNING version` 原子自增；SQLite 启用 WAL 与 15s busy_timeout。8 并发实测 0 个 500，版本号连续无重复。
- **demo 模式闭环断开**：demo 现在可走完 生成→批准→导出，状态记为 `approved_demo`，导出包自动加 DEMO 水印，`is_demo=true`，不进入交付台账。

### P1 修复

- live 模式缺凭据时不再静默降级成演示模板：返回 502、`draft=null`、`status=failed`、不可批准。
- 失败分支 `mode` 字段不再硬编码为 live，如实返回实际模式。
- 验收脚本 T4/T5 判据改为匹配服务端真实的 409 + 顶层字段契约。
- 缺料误检：改为实义总字数下限（40 字），不再按"句数/条数"卡，规范展签体不再被误判。
- blocked 任务禁止 revise 洗成 draft，必须补资料后重新生成。
- blocked 任务的 `/api/review`（approved 和 needs_revision）同样返回 409，堵住"退回 → 修订 → draft"的绕行路径。
- 验收脚本 `clean_sources()` 资料 A 补到 120 字以上，避免 demo 草稿被长度门判 blocked 导致 P3 误报失败。
- `gates.py` 从死代码改造为针对 `app.validate_draft` 的固定回归集（11 条用例，含 3 条反误伤用例），不再是第二套门。

### P2 修复

- `Content-Length: -1` 不再挂起连接，返回 400。
- 新增 `ACCESS_TOKEN` 鉴权：设置后所有 `/api/*` 需带 `X-Access-Token` 头或 `?token=`，静态页放行。默认空值仅供本机演示。
- 500 错误不再回传底层异常原文，改为返回 trace_id，详细信息只写服务端日志与事件表。

### 新增

- `/api/business` 单位经济模型：报价 − 实测直接成本 = 项目贡献，含贡献率、保本价、效率对照；缺项明确列出，不预填数字。
- 交付包导出为真实 7 个文件内容（取自已批准版本），前端打包为 zip。
- 前端按参考站设计语言重做（`#f7f8fc` 底色、白卡片细边框、等宽小标签、单强调色），八段式工作流。

### 已知限制

- T2/T3 仍只能在前端模拟器验证，服务端 T3 通过记录要求结构化事件顺序，前端已对齐。
- 未接入真实模型凭据，live 模式的生成质量未验证。
- 眼镜实机未接入，所有设备相关结论均为模拟。

## 文档口径补充 — 2026-11-14

- 按当前前后端实现补充电脑端模拟、demo/live、部署配置及眼镜实机限制的区分；状态机模拟不计为 AI 或硬件能力。
- 更正 T2/T3 验收边界：脚本 T2/T3 为 BLOCKED；页面结果属于本地模拟，T3 当前上报结构不满足服务端 passed 契约，不能当作持久化通过证据。
- 记录现有 GET/POST `/api/runs/{id}/tests` 契约及服务端 T3 结构化事件顺序要求；本次仅更新文档，未改代码、执行验收或部署。

## 0.1.0 — 2026-11-14

- 新增岗位原则、3 个岗位技能和单条交付 SOP。
- 新增明确标为模拟的 A/B/C 展项资料，覆盖故意缺项及故意冲突。
- 新增基于已核实 HTTP API 的 T1–T9 与两个施压探针验收脚本。
- 新增七项交付包模板、访谈提纲和待验证成本计时表。
- 本次不改 `app.py` 或 `index.html`；没有测试、访谈、客户或商业结果被预填为已完成。

