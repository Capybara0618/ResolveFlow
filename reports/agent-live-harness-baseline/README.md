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
- 入口提交时尚未执行真实评测，未提前报告质量结果。原四历史脏文件未夹带。

## 只读聚合与RAG标注入口

- `python -m scripts.evaluation.live_baseline --input-report <6例报告> --input-report <26例报告> --dataset evals/calibrated-v3 --output <整体报告>`：校验代码、数据、模型、全部预算一致；案例不重叠且完整覆盖32；失败保留、未完成批次/重复/遗漏/请求计数不符拒绝，不调用模型。
- `python -m scripts.evaluation.rag_probes --dataset evals/calibrated-v3 --live-report <整体报告> --output <候选报告> --review-output <盲标模板>`：保留旧入口默认aligned-v2，显式传v3才能读新报告；FAQ版本不改，必须证明v3政策语料与FAQ原绑定语料字节hash一致才允许复用。模型query不等于已执行检索，原top_k和实际turn均保留，离线诊断统一top5。
- 标注模板只含原问法/来源/主体版本和完整政策，不含排名、最终动作或工单Gold；候选另存。`must_rules=null`为未审，`[]`只能由审查人明确判定没有适用条款，不能用来表示不知道。
- 新入口验证：先新增2项RAG兼容测试失败、聚合模块缺失失败；实现后相关79测试通过。新文件首次Ruff有1项导入排序，修复后通过。聚合测试覆盖预算/代码改变、重复、缺例、未结束、请求计数不符。
- 支持入口提交时真实质量仍未收口；最终结果见下文，失败分母未删。

## 已完成的真实结果（2026-10-05）

被测生产/入口代码冻结于 **103aabe4bf468f970b475ab92306620c2dd7a19e**；两阶段的全部 code_hashes、entry_hash、模型参数、数据与预算完全一致。后续聚合/待审辅助脚本单独提交，不改变任何被测生产文件；聚合保留两原报告hash和原逐轮记录。

| 项目 | 实际结果 |
| --- | --- |
| 首批失败/对照6例 | 5/6联合达标，30请求，退出1（A03B失败保留） |
| 剩余26例 | 26/26联合达标，128请求，退出0 |
| 全部32例 | 31/32动作及自动联合达标，31完成/1未完成，0调用错误，0被接受的禁止终局 |
| 分组 | dev 15/16，test 16/16；数据已触达，不能称未见盲测 |
| 真实用量 | 158个provider请求；input **273381**、output **18588** tokens；158份provider usage、0估算/缺失usage |
| 用量账本 | 历史316→474，差值158，limit=null；历史reserved_usd不更新、不等于本轮真实费用 |
| 调用与时间 | 每例4–7请求；本机案例p50 **13.973秒**、p95 **15.618秒**；案例累计426.651秒，含模型/工具/本机开销，不是纯模型延迟或整批墙钟时间 |
| 上下文 | 无观察到的溢出；最大发送估计3248 tokens；估计相对provider输入最小余量376，仅本次观察，不保证所有未来请求 |
| 纠错/故障反馈 | 6例出现10条REFUSED通知，5例最终自动达标；其中包含合成工具故障和事实/引用错误，不能作为生产总体纠错率 |
| 工程回归 | 相关79测试；Harness28/28，strict harness-v10 14/14，Ruff/diff通过 |
| 独立语义审查 | 0/32完成，明确PENDING |

完整[原6例](live-controls.json)、[原26例](live-remaining.json)、[整体报告](live-baseline.json)、[逐例摘要](cases.md)、[审计](audit.json)、[Agent待审表](agent-review-pending.json)、[Harness](harness.json)、[strict](strict.json)。自动31/32只是当前32个合成案例上的检查结果，不是现实退款决策准确率。

### 明确剩余失败：A03B

退款占用事实为 RESERVED，支付32900分、已退0、占用32900，余额不支持再次退款。第4轮错误建议REFUND，被具体字段反馈拒绝；第5轮补读退款状态；第6轮文字承认占用需人工核对，动作仍为REFUND，并列出未解决材料，触发 MISSING_EVIDENCE_ON_REFUND。没有通过终局校验、没有审批/退款执行。它没有耗尽12次调用预算；一次修正已使用，不能靠无限追加调用掩盖。

A01B/A02B同样曾尝试错误REFUND，本次根据字段反馈转人工；A01A/A03A/A13A三个正常对照均4次调用正确建议REFUND。A04B在订单/退款记录NOT_FOUND及坏引用反馈后补问，A08B/A12B在合成只读源临时故障后转人工。它们证明本次真实模型利用了部分反馈，不能推断所有模型错误都自愈。

失败归因：A03B首先是模型的事实适用/动作与文字不一致，Harness安全门槛生效但未恢复到有效建议；已有相关政策实际召回且引用，所以不能直接归因于RAG漏召回。下一步优先处理这一明确冲突的稳定终止/交人工表达，不放宽资金校验，不改本轮结果或重跑刷分。整体基线不是旧13例的受控提升实验：预算与代码都已变化。

## RAG独立标注包已准备，Gold尚未完成

[RAG待审模板](rag-review-pending.json)：**66条**逐query，33条FAQ商家绑定（只有11个独立公开问法来源）+33条本轮真实模型query（32种原问法）。[候选报告](rag-candidates.json)：同样66条分别dense/BM25，**132行**，0检索错误/0主体版本越界；所有准确率null、所有must_rules=null。FAQ不是客户日志，政策语料依然合成。

标注先只读模板里的原query、来源、商家/版本和完整政策，选择该查询必须召回的规则集合，并在notes说明依据及不确定性；不能把工单最终动作Gold当该轮query Gold，不能把相似候选视为授权。无足够信息时保留null，不为了填满而使用空集合。完成初稿/日期后再看另存的候选报告核验漏召回；有争议的条目保留待裁定。标注由独立审查人填写姓名/日期，Agent生成的猜测不能冒充人审。

正式选RAG优化方案前，还需独立完成这些标签，冻结新Gold，按问法来源/场景家族处理重复和开发/测试分组；这批来源及test已被检视，不包装为盲测。届时比较覆盖@2/@5、全依据召回、负例及错商家/版本，再决定是否需要query改写、hybrid或rerank。本批没有改变检索算法，也没有宣称RAG真实效果优化完成。

## 实际命令与核验

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
./eval.ps1 -Mode live -Case A01B,A02B,A03B,A01A,A03A,A13A -ModelCalls 12 -Dataset evals/calibrated-v3 -Output reports/agent-live-harness-baseline/live-controls.json -LiveUsage tmp/evaluation-live-budget.json
# 其余26例由冻结cases.json排除上述6个id，验证Count=26后传入同配置；精确id见live-remaining.json/cohort_reports。
agent/.venv/Scripts/python.exe -m scripts.evaluation.live_baseline --input-report reports/agent-live-harness-baseline/live-controls.json --input-report reports/agent-live-harness-baseline/live-remaining.json --dataset evals/calibrated-v3 --output reports/agent-live-harness-baseline/live-baseline.json
agent/.venv/Scripts/python.exe -m scripts.evaluation.quality_audit --input-report reports/agent-live-harness-baseline/live-baseline.json --dataset evals/calibrated-v3 --output reports/agent-live-harness-baseline/audit.json
./eval.ps1 -Mode review-template -InputReport reports/agent-live-harness-baseline/live-baseline.json -Output reports/agent-live-harness-baseline/agent-review-pending.json
./eval.ps1 -Mode report -InputReport reports/agent-live-harness-baseline/live-baseline.json -Output reports/agent-live-harness-baseline/cases.md
agent/.venv/Scripts/python.exe -m scripts.evaluation.rag_probes --dataset evals/calibrated-v3 --live-report reports/agent-live-harness-baseline/live-baseline.json --output reports/agent-live-harness-baseline/rag-candidates.json --review-output reports/agent-live-harness-baseline/rag-review-pending.json
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_live_baseline_merge.py agent/tests/unit/test_rag_probes.py agent/tests/unit/test_evaluation_controls.py agent/tests/unit/test_quality_audit.py agent/tests/unit/test_evaluation_review.py -q
agent/.venv/Scripts/python.exe scripts/agent_eval.py replay --dataset evals/calibrated-v3 --replay-dir evals/replay/harness-v10 --output reports/agent-live-harness-baseline/strict.json
agent/.venv/Scripts/python.exe scripts/agent_eval.py harness --dataset evals/calibrated-v3 --output reports/agent-live-harness-baseline/harness.json
```

以上为已执行命令；原报告不可覆写，重现需新输出名且真实模型会新增费用。单例质量失败的退出1已保留；聚合/审计/模板命令退出0只表示操作成功。三冻结数据版本hash/规模校验、32/66待审分母、132候选身份/未评分、报告hash绑定、密钥未包含于报告检查均通过。

未运行：新生产750全回归（生产源码未改，前批证据不冒充本批重跑）、新mock32（前批已通过，本批实际模型替代）、业务浏览器/退款端到端、真实429网络故障、独立语义/逐query人审、受控RAG算法效果对照。原四历史脏文件与草图/日志均保留，没有重启/改业务数据库或自动退款。
