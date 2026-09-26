# C08.2 出站方案与已发布契约的缺口（2026-09-26，仅核查、未改码）

范围：只读核查 + 两个只读复现脚本，未改业务代码、测试、数据库、依赖或部署配置，未提交代码改动，未联网，未跑 Java。

## 1. 起点与问题

账本与[当前交接](../tasks/handoff-current.md)记着两项"仍待接入"：`verify_proposal()` 在 runtime 无调用点、`RunWorker` 无常驻装配入口。
动手接线之前先回答一个更前置的问题：**出站给 Java 的那份方案文档，到底是什么？** 因为在错误的文档上做校验，只会把一个缺口换成另一个
（`reports/c08-2-5-callback-payload-contract-gap.md` 的原话就是"再谈 `verify_proposal()` 接入（否则校验的是错的文档）"）。

## 2. 复现（实际运行，未改任何被检对象）

在 `E:/Code/Agent+Backend/agent` 下用现有 venv 跑一个只读脚本：用 `validate_decision` + `ClaimedRun`/`RunResult` + `worker.callback_payload`
组装**真实**出站 body，再喂给仓内 `component_validator("case", "ProposalPayload", "contracts/core", CORE_SCHEMA_FILES)` 与
`ProposalVerifier.verify_proposal(...)`。两种输入只差一个 `summary`。

```text
[with summary] keys=['case_id','case_type','input_revision','proposal_id','reason_codes','recommended_action','run_id','schema_version','summary']
[with summary] contract errors=[]
[with summary] verify_proposal ok=False codes=('REFUND_CITATION_REQUIRED',)
[with summary] citations on the wire: evidence_refs=False policy_refs=False
[no summary]   keys=['case_id','case_type','input_revision','proposal_id','reason_codes','recommended_action','run_id','schema_version']
[no summary]   contract errors=["[]: 'summary' is a required property"]
[no summary]   verify_proposal ok=False codes=('PROPOSAL_SCHEMA_REFUSED',)
[no summary]   citations on the wire: evidence_refs=False policy_refs=False
```

## 3. 三个已复现的事实

1. **缺 `summary` 时出站 body 必被 Java 拒，而 run 会永远停在 `CALLBACK_PENDING`。**
   `ProposalPayload` 的 `required` 含 `summary`（`contracts/core/openapi-case.yaml`），而 `ModelDecision.summary` 是可选的；
   `worker.callback_payload` 只在 `summary` 为真时才写它。于是"模型这次没写 summary"→ body 缺必填成员 → Case 422 → run 状态无人再改。
   `tests/unit/test_callback_payloads_match_the_case_contract.py` **全绿但它证明的只是"带 summary 的那一个 body 合法"**：那条例子的
   fixture 自带 `summary`，契约校验不会覆盖到"模型省略 summary"的分支。这正是"Python 通过不等于 Java 批准"的又一具体形态。
2. **出站方案不带任何引用，gate 验过的引用在出站时被丢掉。** `callback_payload` 的 PROPOSAL 分支不写 `evidence_refs`/`policy_refs`
   （契约两者都是可选、`maxItems` 有界的成员，纯追加不需要 Java 同步）。后果有两个：`verify_proposal(composed)` 对**合法**方案也给
   `REFUND_CITATION_REQUIRED`（它的动作级规则要求退款必须引用）；而 `docs/implementation-handoff.md:27` 记的"Case 可按钉住政策版本核对引用"
   在一份**没有引用**的 body 上无从执行——引用只在 Python 的 run 记录里，过了 outbox 就没了。
3. **`verify_proposal()` 确实没有 runtime 调用点。** `grep -n "verify_proposal" agent/src` 只命中 `harness/verifier.py` 自身；
   调用方只有 `tests/unit/test_proposal_verifier.py`。出站路径（`RunWorker.finish` → `callback_payload` → `enqueue_for_run`）没有任何
   文档级复核。

## 4. 建议的下一步（小步，本次未实施）

1. 出站 PROPOSE 带上模型已给、gate 已用 `verify_citations` 验过的 `evidence_refs`/`policy_refs`（契约允许、纯追加、无消费者同步）。
2. `RunWorker.finish()` 在**写入 outbox 之前**用 `ProposalVerifier.verify_proposal(组装后的 body)` 复核：不合法就不投递这份方案，
   按 run 自己的理由码落 `FAILED`（`docs/agent-harness.md:13`：校验不了的方案不是方案）。这一条同时兜住第 3.1 条。
3. `summary` 是否在 ABI 层对 PROPOSE **强制**单独一步做：会改 `prompt_hash`/`manifest_id`，并让既有 PROPOSE fixture 变红
   （C08.2-7 已量过同类影响面：60 个用例），所以要么先补 fixture，要么明确接受"缺 summary 由第 2 条兜住"。
4. 完成后仍**不得**把"Python 侧通过"写成"Java 已接受"：Java 复核/审批→模拟退款半段仍未运行。

## 5. 未做与边界

- 未改任何代码或测试；上述三点的证据是**当前源码的实际输出**，不是对历史的复述。
- 未跑 Java、all-offline、live 模型、MCP 子进程；`parent_run_id` 仍无人写，常驻调度入口仍缺。
- 本次没有把这三条缺口记成"C08.2 已完成"，C08.1/C08.2 仍不勾完成。
