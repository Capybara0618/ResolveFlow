# Agent业务与执行规格 · v1.3（业务沿用v1.2）

主线见[Harness](agent-harness.md)。Python/FastAPI保留现有锁，Agent框架目标改为AgentScope 2.x SDK，先按[迁移规格](agentscope-migration.md)验证后锁定；单Agent按Observation选择下一行动，Java独立执行退款。核心不是固定workflow，也不是通用Agent产品。

2026-10-05当前调查/终止约束见[第三批规格](agent-investigation-batch3.md)：扁平模型动作/一次修复不变，ASK客户前拒绝六类已绑定编号字段；命名丢失/质量条款的退款建议必须引用对应当前来源和关联人工核验。来源检查不等于全部自然语言条件判定或Java授权。当前context v8/verifier v4，版本不兼容仍不静默迁移；实际质量限制见本批报告。

## 1. 状态与输入

输入为case/run/input_revision、认证绑定的merchant/customer/line、用户诉求、可用政策manifest、deadline。状态保留facts及来源/冲突、观察ref、已问问题、下一动作、预算/调用账、manifest_id和checkpoint；长原文单独存储。

run状态沿用QUEUED/RUNNING/CALLBACK_PENDING/WAITING_INPUT/COMPLETED/FAILED/CANCELLED/STALE。COMPLETED表示方案回调被Case接收，不表示退款成功。QUESTION接收后WAITING_INPUT；补证创建新revision/new run，旧run STALE。新run可继承用户问答，但重新取得物流/退款/政策有效事实。

## 2. 决策

固定职责顺序为load→build_context→model_decide→validate→execute/read/propose→persist→next/end，具体业务工具顺序不固定。这是执行约束，不是要求另写一个循环包住SDK；AgentScope驱动唯一主循环，适配层将原生工具/结构化结果映射到下列领域动作，再统一校验。普通文本不是方案，终止动作后不得额外调用模型。

- READ_TOOL：1–3个独立只读调用，参数由模型选。
- SEARCH_POLICY：query/top_k<=5，绑定当前政策版本。
- READ_OBSERVATION：读本run获准观察的片段。
- ASK_CUSTOMER：最多3个聚合问题，每case最多2轮。
- PROPOSE：核心方案REFUND/REQUEST_INFO/MANUAL_REVIEW/REJECT；身份由运行时填入。
- ESCALATE：生成MANUAL_REVIEW方案或失败回调，记录原因，不补造引用。

损坏/签收争议即使模型建议退款也必须Java人工路由。未知动作、身份字段、任意URL或写工具拒绝。

2026-10-05模型输入协议增加当前run的O/P短引用，见[规则与引用规格](agent-context-protocol.md)。五MCP直接可用，动作/建议字段仍常驻；短引用在严格ABI验证前确定性展开为原有完整契约对象，模型账保留原始响应，SDK/最终回调使用完整身份。事实、版本、冲突、政策条件和后台hash校验不删，不允许模型创建映射；旧完整对象兼容，旧run不静默换manifest。

## 3. MCP白名单

| 工具 | 参数 | 所有者 |
| --- | --- | --- |
| get_order_context | 空对象 | Commerce当前line订单/支付 |
| get_shipment_trace | cursor可选、limit<=20 | Commerce模拟物流适配；最多2页 |
| get_refund_status | 空对象 | Commerce行退款状态 |
| get_case_evidence | kind可选 | Case当前revision材料 |
| get_policy_manifest | 空对象 | Case绑定政策版本 |

5个工具通过真实官方MCP stdio tools/list和tools/call提供；HTTP后端再次检查主体。政策检索和READ_OBSERVATION是本地能力，不包装成额外微服务。

返回Observation带source_type/ref/version/hash/时间和错误。NOT_FOUND不是否定事实；FORBIDDEN停止，不更换ID重试。给模型的excerpt<=8KiB，原始响应<=256KiB；过大返回明确错误并分页，原文受限持久化。

## 4. 预算

默认每run最多12次模型调用（含修复/网络重试）、16次外部工具/检索attempt、8次本地读，用于终止和防循环；新run累计输入/输出token只记录、不设消费上限（2026-10-05用户授权，见[用量规则](model-usage-policy.md)）。单步输入8192/输出1024、单模型timeout30秒继续控制请求大小和时间。工具最多额外重试2次、模型1次，只有一层负责重试，所有attempt记录；旧run保留原冻结配置。

case提交控制面deadline默认10分钟；首次开始调查固化active_deadline=min(deadline,开始+120秒)。同run恢复不延期，停机/重试消耗窗口。落库方案的回调重试不受调查窗口限制，但仍查revision。

预占请求预算并持久化，成功按usage结算；UNKNOWN保守保留估计，不在重启后清零。输入包含最终system/messages/tool schema/provider包装，输出按请求上限预占，不只计算最新packet或预占0输出。SDK隐式修复/重试/总结不豁免计费，不启用绕过ContextBuilder的自动压缩。缺provider准确计数时标ESTIMATED，不承诺精确费用不超额。连续重复同动作且无新证据，两次反馈NO_PROGRESS，第三次停止；不同版本/下一页不误判。

## 5. 恢复与验证

worker领取用PG租约/fence与同run advisory lock；checkpoint（领域运行快照，包含必要SDK续接状态）写入同事务锁run行校验fence，不能先查再另事务写。连接池与session级锁的生命周期必须明确。AgentScope接入由AS01重新验证，不能套用T00的LangGraph通过结论；生产实现归C09。

已落库模型/工具结果用稳定call_id复用；外部模型返回但未落库可重复计费，明确UNKNOWN。SDK会话不是唯一结果记录，恢复补齐“结果保存而checkpoint未前进”，不能重新请求已落库步骤或重复结算预算。最终run状态/方案/callback_outbox同事务且受fence保护。详见迁移规格的恢复窗口与技术门禁。

模型输出Schema/引用可修复一次；ref必须实际可见，来源/版本/hash匹配。Java独立重算金额并核验事实、政策、授权。不得展示隐式思维链，仅存显式动作、短理由、输入快照和工具结果。

核心验收：不同证据驱动不同后续行动；缺证追问/新revision；超权拒绝；预算及无进展停止；落库前后崩溃语义；旧worker/旧回调隔离。
