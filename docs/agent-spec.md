# Agent业务与执行规格 · v1.2核心版

主线见[Harness](agent-harness.md)。Python/FastAPI/LangGraph使用现有锁；单Agent按Observation选择下一行动，Java独立执行退款。核心不是固定workflow，也不是通用Agent产品。

## 1. 状态与输入

输入为case/run/input_revision、认证绑定的merchant/customer/line、用户诉求、可用政策manifest、deadline。状态保留facts及来源/冲突、观察ref、已问问题、下一动作、预算/调用账、manifest_id和checkpoint；长原文单独存储。

run状态沿用QUEUED/RUNNING/CALLBACK_PENDING/WAITING_INPUT/COMPLETED/FAILED/CANCELLED/STALE。COMPLETED表示方案回调被Case接收，不表示退款成功。QUESTION接收后WAITING_INPUT；补证创建新revision/new run，旧run STALE。新run可继承用户问答，但重新取得物流/退款/政策有效事实。

## 2. 决策

固定外层为load→build_context→model_decide→validate→execute/read/propose→persist→next/end，具体业务工具顺序不固定。

- READ_TOOL：1–3个独立只读调用，参数由模型选。
- SEARCH_POLICY：query/top_k<=5，绑定当前政策版本。
- READ_OBSERVATION：读本run获准观察的片段。
- ASK_CUSTOMER：最多3个聚合问题，每case最多2轮。
- PROPOSE：核心方案REFUND/REQUEST_INFO/MANUAL_REVIEW/REJECT；身份由运行时填入。
- ESCALATE：生成MANUAL_REVIEW方案或失败回调，记录原因，不补造引用。

损坏/签收争议即使模型建议退款也必须Java人工路由。未知动作、身份字段、任意URL或写工具拒绝。

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

默认每run最多12次模型调用（含修复/网络重试）、16次外部工具/检索attempt、8次本地读；累计输入40000/输出4000，单步输入8192/输出1024，单模型timeout30秒。工具最多额外重试2次、模型1次，只有一层负责重试，所有attempt计预算。

case提交控制面deadline默认10分钟；首次开始调查固化active_deadline=min(deadline,开始+120秒)。同run恢复不延期，停机/重试消耗窗口。落库方案的回调重试不受调查窗口限制，但仍查revision。

预占请求预算并持久化，成功按usage结算；UNKNOWN保守保留估计，不在重启后清零。缺provider准确计数时标ESTIMATED，不承诺精确费用不超额。连续重复同动作且无新证据，两次反馈NO_PROGRESS，第三次停止；不同版本/下一页不误判。

## 5. 恢复与验证

worker领取用PG租约/fence与同run advisory lock；checkpoint写入同事务锁run行校验fence，不能先查再另事务写。复用T00已验证能力，必要适配只服务这一边界。

已落库模型/工具结果用稳定call_id复用；外部模型返回但未落库可重复计费，明确UNKNOWN。图状态不是唯一结果记录，恢复补齐“结果保存而checkpoint未前进”。

模型输出Schema/引用可修复一次；ref必须实际可见，来源/版本/hash匹配。Java独立重算金额并核验事实、政策、授权。不得展示隐式思维链，仅存显式动作、短理由、输入快照和工具结果。

核心验收：不同证据驱动不同后续行动；缺证追问/新revision；超权拒绝；预算及无进展停止；落库前后崩溃语义；旧worker/旧回调隔离。
