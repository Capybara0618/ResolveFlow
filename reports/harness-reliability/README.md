# Harness 可靠性修复结果（2026-10-05）

## 第一步：具体字段纠错

按[规格](../../docs/harness-reliability.md)实现未发货退款拒绝的字段反馈：列出当前绑定来源的占用、付款、履约版本及整数分余额条件；不会把失败条件直接转换成拒绝，也不将客户文本插入纠错指令。一次修正及资金门禁保留。verifier v6；后续源码变更需新独立回放。

先失败测试7项均失败（fields-before.txt）；修复后82项通过（fields.xml/txt），覆盖具体字段、占用后人工交接、已有退款来源/引用和有限文字事实检查，Ruff通过。最初测试误接不存在的 runner.gate，已修正为直接验证真实 ActionGate；其后保留正式7项失败结果。

实际命令：

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_harness_reliability.py -q --tb=short
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_harness_reliability.py agent/tests/unit/test_investigation_sources.py agent/tests/unit/test_proposal_verifier.py agent/tests/unit/test_correction_loop.py agent/tests/unit/test_harness_manifest.py -q --tb=short --junitxml=reports/harness-reliability/fields.xml
agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml agent/src/resolveflow/harness/verifier.py agent/src/resolveflow/harness/correction.py agent/src/resolveflow/harness/manifest.py agent/tests/unit/test_harness_reliability.py
```

## 第二步：交替循环与检索进展

动作追踪保留本run已请求的动作，交替重复动作也进入原两次无进展反馈门禁；已知重复在第三次无进展执行前阻止。搜索结果以bundle/version/rule/chunk/hash集合判新，不把query/排序/分数变化算新依据；空或旧结果的不同query仍可执行以发现新规则，第三次无新依据后停止。普通结果以工具/来源/版本/hash判新，避免相同payload跨来源或新版本误去重。context v12，verifier v6；受原manifest和代码身份保护。

先失败6项中5失败1通过（loops-before.txt）；初轮缺少常量import及测试模拟的来源区分导致12失败/90通过（loops-initial.txt），修正后102项通过，0 skipped（loops.xml/txt），包含SDK实际交替动作和隔离PG第四次工具落库后崩溃恢复：4次真实stub读取、5次脚本模型调用、2条无进展反馈，恢复不重发保存结果、不重置计数。Ruff首次长度错误修正后通过；排序测试加强后6项仍通过。

```powershell
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_loop_reliability.py agent/tests/unit/test_harness_loop.py agent/tests/unit/test_loop_semantics.py agent/tests/unit/test_sdk_adapter.py agent/tests/unit/test_correction_loop.py agent/tests/integration/test_loop_reliability_recovery.py agent/tests/integration/test_correction_recovery.py -q --tb=short --junitxml=reports/harness-reliability/loops.xml
```

## 第三步A：429分类与等待信息

429单独作为ModelUnavailableError子类，返回有界Retry-After（秒数或HTTP-date，非法值默认5秒，最少1秒，最大一天；运行期限在持久层另行约束）。400/401/402/403不自动重试，transport每调用仍只发送一次。headers不写入模型请求日志，429只使用固定错误文案，不把供应商正文变成模型纠错指令。

先失败9项/原4项通过（rate-before.txt）；修复后模型客户端/SDK32项通过（rate.xml/txt），改动Ruff通过。实际命令为 `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_model_rate_limit.py agent/tests/unit/test_live_model_client.py agent/tests/unit/test_sdk_adapter.py -q --tb=short --junitxml=reports/harness-reliability/rate.xml`。

## 第三步B：持久冷却与有界恢复

追加011迁移保存run冷却时间及attempt失败码/等待时间。DurableRun在429后先以当前fence记录冷却，再交由原worker恢复；领取及reserve_retry都检查冷却，不能提前发送或再次计数。释放冷却run的旧lease并保留调度时间，其他工单可继续；等待不超过原active deadline，原请求hash/预算/manifest不变。第二次429记录失败后立即进入既有重试耗尽终止，不会发送第三次请求。响应到冷却记录之间崩溃仍有未知窗口，不承诺零重复调用/计费。

首次测试引用错fixture引发收集错误（cooldown-collection.txt），修正后4失败/1通过（cooldown-before.txt）。实现初轮6失败/40通过（cooldown-initial.txt）：冷却run仍持有旧lease，以及历史worker模拟结果使用object替代RunSpend；已修正冷却lease释放，并将三个fixture换成真实RunSpend，不删除断言或放宽生产校验。新增直接预留防绕过后67项/0 skipped通过（cooldown.xml/txt），包括等待期、新worker原请求复用、两次429终止、过期停止、其他工单进展、旧fence拒绝与原持久恢复。改动Ruff通过。配置式全项目mypy仍16既有错误/9文件/73源码（mypy.txt），无新增诊断，类型门禁仍未通过。

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_model_rate_limit_recovery.py agent/tests/integration/test_recoverable_worker.py agent/tests/integration/test_sdk_durable_recovery.py agent/tests/integration/test_recovery_model_attempt.py agent/tests/integration/test_recovery_model_result.py agent/tests/integration/test_run_worker.py -q --tb=short --junitxml=reports/harness-reliability/cooldown.xml
agent/.venv/Scripts/python.exe -m mypy agent/src --config-file agent/pyproject.toml
```

第一步0c86215、第二步9e060b3、第三步A56678e2已核实正常push到origin/main。本批集中PG/MCP/strict新配置待收口。未真实模型复测、Java整链、网页或收费调用/常驻服务重启，不宣称建议质量提升。
