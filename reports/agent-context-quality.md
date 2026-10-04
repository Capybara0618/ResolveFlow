# Agent 上下文与结论质量：第一批

2026-10-04。按用户批准的 [方案](../docs/agent-context-quality.md) 实施；进度仅在 todo 顶部。此次是上下文精简及拒绝建议的工程校验，不是大模型正确率或当前商城 RAG 召回评测。

## 实际改动

- `ContextBuilder` 保留完整政策条件/例外及引用，同一份规则被不同查询反复召回只呈现一次；不同版本/hash/原文不合并。P3 保留排名对应的 rule/version、标题、分数及未知元数据，正文指向必保留的 P2，原始排序/原文仍能读回。
- 已抽取的精确字段在 P2 出现，P3 仅保留字段映射及未抽取内容。只有本 Observation、来源、版本/hash和值都匹配的当前事实可消除重复；不能用另一来源或旧版本的事实替代。
- 已被同源新版替代的 STALE 事实和其引用不再挤占当前 P2；原始 Observation/历史索引保留。所有当前冲突同时呈现，`protected_fact_hash` 语义不变。
- 增加简短的订单/物流/退款/材料/政策读取进展，区分未读、失败、无候选。工单/订单行/运行身份继续在系统任务和 ContextPacket 元数据中保存，不反复发送不能由模型选择的长 ID；材料修订仍在请求中。
- 中文 prompt 去除重复说明，保留原文仅为数据、四项引用、陈述/推断/冲突、未知、人工作用、针对性追问与分/元语义。明确空材料/读取失败/无候选不能支持拒绝，物流 NOT_FOUND 不能推导未发货。
- REJECT 要求实际证据及检索过的政策引用、成功且被引用的付款订单和已知物流事实、无自报关键缺证；不具备时给出稳定原因并仅允许原有一次修复，MANUAL_REVIEW 仍可使用。REFUND 原引用/缺证检查不放宽，Java 权威事实/金额/审批不变。此次门禁只能证明最低依据完整，不能证明政策解释正确。
- 新上下文版本 `p0-p4-v4-precision-progress`，verifier `python-citations-v2-rejection-evidence`；prompt/tool schema hash 和代码身份同步变化。旧 run 不换 manifest 或重置预算，已完成结果不重算。

## 固定输入前后对照

八个独立合成 ContextPacket，使用同一 fixture、最小 tool schema、真实组装函数与校验器，无模型/数据库调用。**不是完整生产任务或累计供应商计费**。来源：[`before.json`](agent-context-quality/before.json)、[`after.json`](agent-context-quality/after.json)。

| 诊断输入 | 改前估算 | 改后估算 | 拒绝/建议检查 |
| --- | ---: | ---: | --- |
| 买错规格口语（未提供明确未发货事实） | 4827 | 4387 | 无依据拒绝：通过 → 拦截 |
| 确认丢失、退款引用 | 4827 | 4390 | 原退款引用检查仍通过 |
| 签收争议、多次检索 | 5939 | 4566 | 人工复核仍可用 |
| 单方损坏、无引用拒绝 | 4837 | 4395 | 通过 → 拦截 |
| 高金额政策例外 | 4840 | 4403 | 人工复核仍可用，例外保留 |
| 同规则三次查询 | 6576 | 4616 | 原引用检查仍通过 |
| 无政策候选 | 3671 | 3591 | 无依据拒绝：通过 → 拦截 |
| 订单读取失败 | 4299 | 3869 | 缺订单依据拒绝：通过 → 拦截 |
| 合计 | 39816 | 34217 | 必保留事实 hash 八例全部一致 |

这些输入的 ESTIMATED 总长度减少 5599，约 14.1%；计数是现有 UTF-8 字节保守估算，不能写成实际 token/费用降低 14.1%。同一政策正文原为每 packet 2–5 份，改后为1份；条件与例外原文、来源版本/hash全部保留。最高相似条款是否适用不在本对照结论中。

改前基线在 commit `a933674` 保存后才改生产代码；另以 git archive 提取该版本到忽略目录 `tmp/agent-context-baseline`，重跑基线，与 before 的八份 messages/hash/校验结果逐项完全一致。没有切换工作区、覆盖用户改动或重写历史。

## 实际验证

新增 `test_context_quality.py` 16项：重复政策、改版政策、未知字段、未抽取结果、读取缺口、空材料拒绝、人工退路、已知/未知物流、自报缺证、同源更新读回、两来源冲突、坏引用元数据、SDK 一次修复与持续拒绝停止。

集中20文件 **209 passed，5 failed，0 skipped**。唯一失败为既有 `test_committed_golden_pack` 五包，`PACK_INVALID: incompatible harness manifest/state/code`；改前 `a933674` 源码隔离复测同五项全部失败。未删除断言、重录旧包或放开 manifest。新生成的五种持久轨迹 strict 回放、恢复与实际请求/预算检查在通过集合内。

核心命令（仓库根目录；DB测试随机独立 schema，结束后清理自身 schema）：

```powershell
agent/.venv/Scripts/python.exe scripts/agent_context_audit.py --output reports/agent-context-quality/before.json # 改前执行
agent/.venv/Scripts/python.exe scripts/agent_context_audit.py --output reports/agent-context-quality/after.json
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_context_quality.py agent/tests/unit/test_context_builder.py agent/tests/unit/test_context_citation_survival.py agent/tests/unit/test_context_facts.py agent/tests/unit/test_context_scenarios.py agent/tests/unit/test_context_trimming_demo.py agent/tests/unit/test_proposal_verifier.py agent/tests/unit/test_loop_semantics.py agent/tests/unit/test_sdk_adapter.py agent/tests/unit/test_harness_manifest.py agent/tests/unit/test_action_repair_notice.py agent/tests/unit/test_build_identity.py agent/tests/integration/test_context_wiring.py agent/tests/integration/test_sdk_durable_recovery.py agent/tests/integration/test_policy_search_action.py agent/tests/integration/test_reviewer_diagnostics.py agent/tests/integration/test_recovery_request.py agent/tests/integration/test_recovery_budget_store.py agent/tests/integration/test_strict_replay.py agent/tests/integration/test_replay_golden.py -q --tb=line
agent/.venv/Scripts/python.exe -m ruff check agent/src/resolveflow/harness/context.py agent/src/resolveflow/harness/verifier.py agent/src/resolveflow/harness/vocabulary.py agent/src/resolveflow/harness/manifest.py agent/src/resolveflow/harness/sdk_runner.py agent/tests/unit/test_context_quality.py scripts/agent_context_audit.py
git diff --check
```

初轮5个新增关键失败先复现；实现中新增进展导致低输入预算和长调用窗口回归失败，改为更短状态、移出无决策作用的任务 ID、去除 prompt 重复并将已替代事实移出当前 P2 后通过，没有提高预算或改掉旧断言。一次新 SDK 测试把 ModelDecision 当字典导致失败，改用实际类型属性后通过。

首次 status 检查依赖容器和政策READY，应用五进程未运行，返回1；不是就绪通过。Agent 公共库仍4 COMPLETED、15模型记录、10工具、8回调，无待执行 run。此次未发送新模型请求、未造订单/工单或退款。

代码 `ba6f0db` 正常推送并确认远端后，实际执行 `.\start.ps1 -SkipBuild -NoBrowser` 返回0：现有三店政策导入0/同hash跳过3、索引READY，三个Java进程、当前真实Agent和网页已启动，九项就绪检查全部通过。没有启动浏览器或发起新调查。启动后只读PG核对4 COMPLETED/15模型/10工具/8回调与启动前一致，[机器记录](agent-context-quality/runtime.json)。业务地址仍为 `http://127.0.0.1:5174/#/shop`，新调查使用本批代码，已完成建议不重算。

## 未运行与后续

- 没有真实模型建议前后对照；合成动作不证明模型自主判断改善。没有重跑全仓 Java/网页，因为其代码/协议未变。
- 不宣称当前三店政策的新 RAG recall。旧40查询不是新场景质量依据；本批仅去除检索结果的重复呈现，没有换 embedding/修改排序。
- 明确履约事实仍是后续关键依赖：当前五个 MCP 工具并未接入新商城 `order_fulfillment` 状态/版本；无物流记录不是未发货事实。后续需把可信履约投影接到可复核来源，再实现场景化结论条件。第一批遇到无法证实的物流状态可转人工，不能为了让建议通过伪造来源。
- 材料问答仍按既有无损快照保护；超大必需材料继续明确超限。后续设计按需原文访问时必须保留客户主张、已答问题、人工结论和冲突，不能直接裁掉正文。
