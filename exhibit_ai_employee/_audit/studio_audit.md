# app / Studio 安全与功能审计

记录时间：2026-11-14（Asia/Shanghai）。代理与隔离 HTTP 复现正常，未遇到401；未输出密钥。仅新增本记录，未编辑实现文件。

## 验证边界

最近完整实测 app.py SHA256：`289c550b6b31c41013d4f10ea908bf2ec3f79aa3ad9e9fc2ecb6c7a4f89a8000`。

读取单次代码快照并在内存执行，使用临时SQLite、127.0.0.1随机端口、虚拟访问口令，通过真实HTTP Handler复现。未改现有业务数据库，未调用模型或TTS。初始资料为 gates._base_sources()，草稿为 deepcopy(gates.CASES[0]['draft'])；隔离种子为draft、version=1、mode=live。该mode是夹具，不能作为真实模型运行证据。行号随并行开发变化，以下函数名和SQL更可靠。

尚无已确认P0。已确认以下两类P1；程序内部名为“P0质量门”的检查不代表漏洞风险等级。

## P1-01：审批与修订并发，批准版本与内容错配

位置：app.py `/api/review`、`/api/revise` 分支，审批末尾 `UPDATE runs SET draft=?,validation=?,status=? WHERE id=?`。已验证快照约1864、1936行。

可复现步骤：

1. 从上述合规夹具创建v1任务，并保存versions中的v1快照。
2. `POST /api/review`，提交run_id、decision=approved、expected_version=1。在审批validate_draft结束后、UPDATE之前暂停线程。
3. 另一线程将v1草稿的 `draft['cards'][0]['card_title']` 改成 `AUDIT-V2`，`POST /api/revise`，提交run_id、draft、expected_version=1。
4. 修订收到HTTP200、version=2后恢复审批；审批也收到HTTP200。
5. 查询runs与versions，并 `GET /api/runs/ID/export`。

实测：runs.version=2、status=approved，runs.draft标题却恢复为v1的“回归用例卡 A”；versions(v2)标题仍为AUDIT-V2，两个草稿不一致；导出HTTP200。导出版本字段位于 `package.version`，导出正文直接使用runs.draft并标为runs.version，不核对批准快照。

确定性复现采用内存包装validate_draft和threading.Event固定上述调度，不修改实现；暂停仅放大实际读写窗口。不要以导出“历史差异”出现AUDIT-V2推断新标题保留在正文。

同根因的顺序复现：任务已到v2后，以旧v1草稿再次revise，同时提交version=1和expected_version=1，仍HTTP200、新版本3。服务端忽略这些版本字段，旧编辑覆盖新编辑；写事务原子取号只能保证版本号不重复。

修复：review/revise强制expected_version；事务内读取并校验版本与允许状态，条件UPDATE失败返回409；批准绑定不可变版本和内容/资料哈希；审批不回写旧草稿。导出及发布从批准快照取内容并核验版本/哈希。修订原子失效批准、测试、音频及发布资格。

验收：上述交错至少一请求409；approved内容与批准版本快照始终一致；顺序提交旧expected_version也必须409。

## P1-02：无来源的讲解与问答通过验证、审核及导出

位置：app.py coverage_gaps、validate_draft、build_package，已验证快照约548、706、1009行。

每组独立从干净合规v1开始，分别仅做下列一项变更：

```python
draft = copy.deepcopy(gates.CASES[0]['draft'])
card = draft['cards'][0]
card['narration'] += '触摸可治病。'
```

或：

```python
card['narration'] = card['narration'].replace(
    '器身饰有饕餮纹。', '器身饰有饕餮纹，可治愈失眠。'
)
```

或：

```python
card['answer'] += '触摸这件展品可以治病。'
```

每组依次调用：

1. `POST /api/revise`，run_id、draft、expected_version=1。
2. `POST /api/review`，run_id、decision=approved、expected_version=2。
3. `GET /api/runs/ID/export`。

三组均实测：validation为passed=true、checks=16、total_checks=16、issues=[]；三个HTTP状态均200；导出文件含新增治疗表述。测试断言草稿确实发生变化，排除了replace未命中的假阳性。

根因：coverage_gaps跳过小于12字的句子；长句只有covered_clauses==0才失败，任一分句获得支持就能携带无依据分句；answer未做同等溯源检查，却被导出原样包含。

修复：全部实际展示、语音、问答及导出字段都需溯源；短事实句不能按长度免检；每个实质分句都需支持。绑定授权原始资料ID、原文范围及哈希，严格原文模式使用可验证摘录，改写需要明确人工事实确认；不得用生成文本作为自己的来源。发布前验证最终载荷与批准内容一致。

验收：三组均须在批准或更早阶段阻断，未获事实确认不得进入导出/发布。

## 认证：URL口令写入访问日志，等级取决于部署

位置：app.py Handler.authorized与Handler.log_message，已验证快照约1510、1481行。

隔离设置虚拟ACCESS_TOKEN后，以 `GET /api/health?token=虚拟值` 认证，返回HTTP200；内存捕获默认日志确认完整虚拟口令被记录。仅输出布尔结果，不输出口令。

若访问日志向低权限人员或外部日志服务开放，可按P1处理；当前未证明实际日志可见范围、外网暴露、真实口令泄露，不能写作“已发生账号接管”。未设置口令时的本机演示放行也不单独作为已确认P1。

修复：认证走请求头或安全会话，停用query token；日志屏蔽凭据；兼容迁移页面清理地址栏口令。

## Studio增量审计状态

studio.py、voice_live.py已落盘。最近读取studio.py为125行，仅有表结构、get/save、reserve、模型封装、normalize；app.py尚未发现Studio/studio路由接入。不能把未完成的分批实现误报成最终产品缺陷。

Studio.reserve已在BEGIN IMMEDIATE内检查expected_version和状态，是正确方向；审批、修改、异步收尾与发布是否完整复用约束仍待接口落盘验证。尚未确认Studio专属P0/P1，也未完成其端到端发布验证。

待验收：旧版本审批409；并发审批修订不覆盖；修订使审批/测试/音频失效；旧异步任务不得回写恢复过期结果；全部输出字段可回溯原始资料；发布绑定批准快照和哈希；发布条件及下载资源认证一致。app.py现有缺陷不自动归因于Studio。
