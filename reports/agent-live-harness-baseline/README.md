# 当前 Harness 真实模型基线

2026-10-05，沿用 calibrated-v3 全部32例及冻结 Gold，正文 dense 检索不变。本次用户明确批准生产配置真实复测与整体基线；不改生产 Agent、旧数据或旧报告。

## 执行协议

先 A01B/A02B/A03B 三个历史失败与 A01A/A03A/A13A 三个正向对照，再剩余26例，每例只运行一次。两阶段显式 `-ModelCalls 12`，单例其它预算与生产 RunBudget 默认一致；历史入口默认6保留。整体分母为32，错误/未完成保留，不自动重跑刷分。

模型 deepseek-flash，temperature=0、thinking disabled、JSON输出、最大输出1024；context v12/verifier v6；自动动作/读取/引用评分，不等于独立语义人审或业务退款端到端验收。使用隔离PG索引与合成只读HTTP/MCP，不消费常驻工单队列。本次直接 AgentScopeRunner 的质量评测不覆盖持久 worker 的429冷却/崩溃恢复，后者沿用可靠性工程测试证据。

旧13例受6次预算且代码不同，不能将新旧分数差异归因于单项 Harness 或 RAG 改善。本批保留逐轮请求、Observation、反馈、真实 provider usage 与本机耗时。独立RAG Gold 标注包只准备来源、候选与待填标签，不把自动评分/同作者合成标签宣称人工独立答案。

## 入口验证

- 修改前：4个新测试中2失败（12次参数不支持、报告无配置），2参数拒绝测试通过。
- 修改后：`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_evaluation_controls.py -q`：43 passed。
- `agent/.venv/Scripts/python.exe -m ruff check --config agent/pyproject.toml scripts/agent_eval.py scripts/evaluation/reporting.py agent/tests/unit/test_evaluation_controls.py`：通过。首次未指定agent配置误加载根配置，19项诊断；按项目既有配置复核通过，不修改旧代码规避规则。
- 新增 `--model-calls` / PowerShell `-ModelCalls`，允许1–12，保持默认6；实际Runner和报告均使用所选预算；新报告预算不同或新旧配置缺失时拒绝直接效果比较。
- 真实评测尚待执行，不能提前报告质量结果。原四历史脏文件未夹带。
