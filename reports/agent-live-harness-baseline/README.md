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

## 只读聚合与RAG标注入口

- `python -m scripts.evaluation.live_baseline --input-report <6例报告> --input-report <26例报告> --dataset evals/calibrated-v3 --output <整体报告>`：校验代码、数据、模型、全部预算一致；案例不重叠且完整覆盖32；失败保留、未完成批次/重复/遗漏/请求计数不符拒绝，不调用模型。
- `python -m scripts.evaluation.rag_probes --dataset evals/calibrated-v3 --live-report <整体报告> --output <候选报告> --review-output <盲标模板>`：保留旧入口默认aligned-v2，显式传v3才能读新报告；FAQ版本不改，必须证明v3政策语料与FAQ原绑定语料字节hash一致才允许复用。模型query不等于已执行检索，原top_k和实际turn均保留，离线诊断统一top5。
- 标注模板只含原问法/来源/主体版本和完整政策，不含排名、最终动作或工单Gold；候选另存。`must_rules=null`为未审，`[]`只能由审查人明确判定没有适用条款，不能用来表示不知道。
- 新入口验证：先新增2项RAG兼容测试失败、聚合模块缺失失败；实现后相关79测试通过。新文件首次Ruff有1项导入排序，修复后通过。聚合测试覆盖预算/代码改变、重复、缺例、未结束、请求计数不符。
- 全部真实质量结果仍待整体收口，不因目前已完成病例较好就改分母或宣布成功。
