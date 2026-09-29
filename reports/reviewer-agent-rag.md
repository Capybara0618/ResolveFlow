# 第四批交付：五个难例的离线诊断

2026-09-29 执行（DSH）。依据 [`tasks/dsh-reviewer/04-agent-rag.md`](../tasks/dsh-reviewer/04-agent-rag.md)。

本批**未修改生产代码**：五例的离线部分逐条核对后都满足要求，唯一的真实缺口（已答问题不进入下一轮 run）需要动协议，属于"报告证据、交用户决策"的一类，不做半成品改造。因此交付物是诊断集、定向测试与逐例记录。

- 诊断集：[`agent/tests/fixtures/reviewer_diagnostics.json`](../agent/tests/fixtures/reviewer_diagnostics.json)（数据，含每例的 `observed` 结论）
- 定向测试：[`agent/tests/integration/test_reviewer_diagnostics.py`](../agent/tests/integration/test_reviewer_diagnostics.py)（10 项）
- 真实 dense 检索实测：`scripts/policy_search_eval.py` 对第二批 demo 索引（`--dsn postgresql://agent:agent@127.0.0.1:55433/agent_db`）

诊断顺序按手册第 4 节：工具数据 → 检索 → 上下文 → 建议输出 → 仅在确有提示词问题时才动 `vocabulary.py`。本批没有改动提示词。

## 1. 逐例记录

### 例1 签收冲突

| | |
| --- | --- |
| 预期 | 两来源与版本进入上下文；可提出签收争议的具体补证或转人工；输出注明冲突 |
| 不允许 | 把客户说法写成承运商确认丢失；执行丢失退款 |
| 改前 | 未发现缺口 |
| 原因 | `get_shipment_trace` 的 `carrier_conclusion` 作为 `AUTHORITY` 事实进入 P2，随行的 `source_ref@version` 也在；客户的原始诉求经 `request.description` 进入 P1；材料引用带四项身份 |
| 修改 | 无 |
| 改后 | 同改前 |
| 证据 | `test_a_signing_conflict_reaches_the_model_with_both_sources_and_their_versions`：读入两张来源后那一轮的**真实请求**里含 `shipment_carrier_conclusion=DELIVERED [AUTHORITY …@3]` 与客户原话，且**没有任何来源在说丢失**；`packet_excludes` 检查的是"来源的丢失主张"（`shipment_carrier_conclusion=LOST`、`"carrier_conclusion": "LOST"`、承运商确认丢失），不是 token——被检索到的政策文本里合法地含有 "LOST"，这一点已写进诊断集，避免用关键词冒充证据 |
| 模式 | mock（结构/数据/进入上下文可证） |

**未证部分**：真实模型是否**主动识别**这个矛盾并转人工，mock 证不了（手册第 5 节明说）。这一半是 NOT_RUN。

### 例2 单方损坏

| | |
| --- | --- |
| 预期 | 说明缺少核验；按现有规则补证/转人工；材料改变后旧修订失效 |
| 不允许 | 虚构图片鉴定、核验人或自动确认真实性 |
| 改前 | 未发现缺口（但有一处需要写清楚的限制） |
| 原因 | `get_case_evidence` 只返回四项引用、**不含正文**（`contracts/core/openapi-case.yaml` 的 `EvidenceRef` 刻意如此），因此上下文里既没有可被过度信任的材料正文，也没有任何"已核验"事实；材料的核验状态只存在于工单视图（第三批已按"未核验不画绿勾"呈现） |
| 修改 | 无 |
| 改后 | 同改前 |
| 证据 | `test_a_unilateral_damage_claim_never_reads_as_verified`：请求里含客户诉求与材料引用，`packet_excludes` 的"已核验/CONFIRMED/真实性已验证/核验通过"一个都不出现；工具 body 里没有材料文本；针对性追问同时通过 ABI 校验（见例5） |
| 模式 | mock |

**已记录的限制**：run 也不知道某份材料**是否**已被人工核验（工具不带 `verification_result`）。今天模型既不能过度信任它，也不能依赖它；如果将来要让 Agent 用上已核验结论，需要动 `EvidenceRef`，与例5的缺口是同一类协议改动。

### 例3 无适用政策

| | |
| --- | --- |
| 预期 | 无命中与索引未就绪分开；明确缺依据/服务问题 |
| 不允许 | 换商户/换最新 bundle；随便引用最高分条款 |
| 改前 | 未发现缺口 |
| 原因 | `PolicySearchBridge` 的身份来自 **run facts**（merchant/bundle_ids/manifest_hash），模型只提供 `query`/`top_k`；索引按 bundle+manifest 过滤，未 READY 的 pin 走 `POLICY_INDEX_NOT_READY` 而不是 `TOOL_FAILED` |
| 修改 | 无 |
| 改后 | 同改前 |
| 证据 | `test_a_query_without_a_match_returns_nothing_rather_than_the_closest_other_bundle`：无命中时 `hit_count=0`、`error=None`，返回的每条 hit 都属于钉住 bundle，`policy-damage-2026.09`（同时索引在库）一条都不出现。`test_an_unindexed_pin_reports_its_own_reason_and_not_a_broken_tool`：未索引的 pin → `completed=False`、`reason_code=POLICY_INDEX_NOT_READY`。真实 dense 实测的 `filter_violations=0`（40 条查询、两个 bundle、两个版本）把"过滤是实测的不是假设的"钉住 |
| 模式 | mock + 真实 dense 检索 |

### 例4 政策例外

| | |
| --- | --- |
| 预期 | 分块、检索、上下文保留完整条件/例外；建议不能忽略例外 |
| 不允许 | 截出"可退款"当成充分依据 |
| 改前 | 未发现缺口 |
| 原因 | 切块以"一条规则一块"为单位，块文本就是已存正文；检索同一次查询同时召回基础规则与例外规则；例外是独立条款，因此它作为**自己的**命中带五项身份进入请求 |
| 修改 | 无 |
| 改后 | 同改前 |
| 证据 | `test_the_exception_survives_chunking_retrieval_and_the_request`：`R-LOST-EXC-001` 的 chunk 文本与存储正文逐字相同（含"例外"与 500000 阈值）；同一次查询的命中里同时有 `R-LOST-001` 与 `R-LOST-EXC-001`；最后一次请求里含 `order_paid_amount_minor=600000`、`shipment_carrier_conclusion=LOST`、`R-LOST-EXC-001` 与阈值文本 |
| 真实检索 | `dev-15 [dev/high_value_exception] 高价值订单行丢失规则的例外` → dense 与 BM25 都是 **rank=1** 命中 `R-LOST-EXC-001`，第 2 名是 `R-LOST-001`；LOST 类查询的 top-5 里也都带例外条款 |
| 模式 | mock + 真实 dense 检索（真实缓存模型 `BAAI/bge-small-zh-v1.5 @ 7999e1d3…`，512 维） |

### 例5 针对性追问

| | |
| --- | --- |
| 预期 | 提问对应明确缺口，带稳定 `question_id`；已有回答不重复索取；两轮/超时有效 |
| 不允许 | 泛泛"补充更多信息"、无穷追问、改写旧答案 |
| 改前 | **部分满足**：追问形状与上限成立，"已答不重复索取"不成立 |
| 原因 | ABI 层：`ASK_CUSTOMER` 必须带 `question_id`/`field`/`prompt`，一次最多 3 问（`validate_decision`）。工单层：两轮、等待态、到期不再追问由 case-service 负责（第一批已交付）。**但**：下一轮的 run 请求只带 `request.description`、`requested_actions` 与 `evidence_refs`（`AgentRunDispatch.runRequest`），内部材料路由只返回四项引用且**不含 `question_id`**，所以新 run 无法知道上一轮问过什么、客户答了没有 |
| 修改 | 无（需协议改动，见下） |
| 改后 | 同改前 |
| 证据 | `test_a_targeted_question_must_name_its_field_and_a_decision_may_not_ask_four`：缺 `field` 与超过 3 问都被具体拒绝。`test_an_answered_question_is_not_carried_into_the_next_run_and_that_is_a_known_gap`：断言 `RunRequest` 上没有任何 question 成员，并保留 `description`/`requested_actions`/`evidence_refs` 三项——将来补上该成员时这条测试会失败，提醒更新诊断集 |
| 模式 | mock |

**缺口的后果与最小修法**：后果是**重复提问**，不是无限追问——两轮/等待/到期仍由工单服务兜住。要真正解决，需要在协议上让"上一轮的问题与客户的回答"成为 run 的可追溯输入，二选一：

1. `RunRequest.request` 增加可选成员（例如 `question_context: {question_id, field, prompt, answer}`），由 `AgentRunDispatch` 从工单材料/工单事件投影生成；需要同步 core OpenAPI、Python 模型、run 请求 hash 与 fixture；
2. 或在内部材料路由的引用上增加 `question_id`，让"这条材料是某个追问的回答"成为引用的一部分；这会改动 `EvidenceRef`（现为固定四项），影响方案引用与 Java 复核。

两条都超出"局部函数拆分"的范围，且第 2 条会触及引用身份与复核路径，因此本批只报告、不实现。

## 2. 命令与实测

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_reviewer_diagnostics.py -q
# 10 passed

agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_policy_chunking.py agent/tests/unit/test_reviewer_findings.py agent/tests/unit/test_context_builder.py agent/tests/unit/test_context_facts.py agent/tests/unit/test_context_scenarios.py -q
# 62 passed

agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_policy_index.py agent/tests/integration/test_policy_search_action.py agent/tests/integration/test_context_wiring.py -q
# 62 passed

agent/.venv/Scripts/python.exe scripts/policy_search_eval.py --dsn "postgresql://agent:agent@127.0.0.1:55433/agent_db" --report tmp/reviewer-demo/rag-eval.txt
# dense  n=40 answered=40 recall@5=1.000 top1=0.750 mrr@5=0.858 median=16ms p95=23ms errors=0 filter_violations=0
# bm25   n=40 answered=40 recall@5=1.000 top1=0.775 mrr@5=0.863 median=4ms  p95=5ms  errors=0 filter_violations=0
# dense model: BAAI/bge-small-zh-v1.5 @ 7999e1d3359715c523056ef9478215996d62a620 (512 dims)
```

未改动循环/持久请求/恢复，因此按手册未跑 `test_sdk_durable_recovery.py`、`test_recovery_budget_store.py` 与 strict 回放（它们的状态见第二批报告：5 个 committed golden pack 仍是已知的过期证据）。

## 3. 真实模型质量：NOT_RUN

未获授权调用任何收费模型，也未沿用旧 C12 预算。因此：

- 例1"模型是否主动识别冲突"、例2"模型是否会说清缺口而不是编造核验"、例5"模型是否会问得具体且不重复"，这三条**只做了结构/数据/限制层面的验证**，真实建议质量**未验证**。
- `mock` 模式只证明数据、结构、限制与保存链路（手册第 5 节原文）。诊断集里的 `observed.not_provable_offline` 就是为这三条留的位置。
- 若将来授权 live：只对五例新 run 执行，固定模型与 manifest，调用前设总金额/调用数/时间上限、失败也计费；记录请求 hash、引用、token、耗时与未知计费。无上限控制不启动；strict 回放不得联网。

## 4. 未做与边界

1. 未新增 hybrid/RRF/rerank、未换 embedding 或依赖锁、未加多 Agent、未做模型路由、未删除任何失败样本、未在冻结 test 上调参（手册第 4 节明确禁止）。
2. 未修改 `vocabulary.py`：五例里没有一例的失败能归因到提示词；提示词已在第二批按要求保留"条件例外、缺口、具体追问"的要求。
3. 诊断数据与第二批演示样本互不相干：诊断集用独立的 observation_id 与 case_id，测试只读 `reports/reviewer-demo/samples.json` 做隔离断言，不写它。
4. 真实 dense 评估用的是第二批建的 demo 索引（同环境、同 manifest 过滤口径）；语料是合成的、规模很小，不外推正确率。
