# 领域与状态 · v1.2核心版

金额为整数分，CNY；UTC存储；ID用UUID。version是乐观锁，input_revision是决策输入版本，两者不得混用。当前契约目标见[核心契约](core-contracts.md)。

## 1. 核心不变量

| ID | 不变量 | 最终负责位置 |
| --- | --- | --- |
| CI-01 | refunded+reserved<=paid，三者非负 | Commerce行锁/条件UPDATE及事务 |
| CI-02 | 同一订单行至多一次成功退款；同一时刻至多一个活跃退款 | Commerce行退款状态+操作历史 |
| CI-03 | 同operation_id同载荷返回原结果，换载荷409；provider key稳定 | operation唯一键/payload_hash |
| CI-04 | 重复消息不重复业务效果，结果乱序不覆盖权威终态 | inbox+本地事务+查询对账 |
| CI-05 | 旧revision/过期/已撤销方案不能新授权；授权消费与操作/outbox原子 | Case事务 |
| CI-06 | Agent无审批/退款/跨主体读取权限 | Java资源服务验证 |
| CI-07 | UNKNOWN不释放金额/行占用，不换ID重试；成功退款不可本地回滚 | Commerce对账 |
| CI-08 | Case仅在Commerce确认成功后CLOSED_SUCCESS | Case结果处理 |
| CI-09 | 旧worker不能推进checkpoint或有效回调；恢复不清预算 | PG fence/锁及持久记录 |
| CI-10 | strict回放无业务写入，不伪造缺失记录 | 隔离adapter/执行环境 |

旧INV-02跨动作权益及补发不再适用；历史证据不改名冒充新测试。

## 2. case_db

- demo_user：商家、用户/审核角色、密码hash；不用完整IAM。
- aftersale_case：merchant/customer/order/line、status、requested_actions=[REFUND]、input_revision、version、expires_at。
- active_case_slot：(merchant_id,line_id)唯一活跃case；终态释放，Commerce仍阻止重复退款。
- case_evidence：来源、ref、version、hash、revision、observed_at、内容；追加而非覆盖，人工核验另加记录。
- agent_binding：(case_id,input_revision)唯一run。
- proposal：run/case/revision、payload_hash、状态、证据/政策ref；不可原地改载荷。
- authorization：planned_operation_id、proposal_id、action=REFUND、金额/数量/line、payload_hash、policy_version、evidence_digest、expires_at、status、version。
- approval：授权终局决定唯一；申请人/审核人、理由、授权版本。
- case_operation：authorization_id唯一、固定operation_id、目标Commerce、投影状态/版本、查询时间。
- policy_bundle：不可变正文+结构化规则、商家/品类、有效区间、published_at、hash、状态。
- case_timeline、audit_event、outbox、inbox、request_idempotency：独立持久记录，按幂等/查询条件建索引。

批准、撤销、材料更新、授权消费都锁case行并校验input_revision。消费一次性创建case_operation与退款命令outbox；一旦消费，材料更新/取消/改方案返回409。授权过期发生在消费前；消费成功后属于执行，不靠过期撤销已发命令。

## 3. commerce_db

- orders/order_line：归属、支付时间、原始行金额/数量/品类；核心不接入已有部分退款的订单。
- payment_ledger(order_id PK,paid_amount,refunded_amount,reserved_refund_amount,version)。
- line_refund(line_id PK,state FREE/RESERVED/CONSUMED,operation_id,version)。
- refund_operation(operation_id PK,authorization_id UNIQUE,merchant_id,line_id,payload_hash,amount_minor,state,provider_key UNIQUE,provider_ref,retry_at,version)。
- shipment_snapshot及shipment_event：合成物流来源、结论、source_version、时间；只读业务适配，无履约写操作。
- inbox/outbox：消费事件与操作/账本更新同事务。

处理命令：验签/校验schema与主体 → 事务inbox去重 → 按固定顺序锁支付账与行退款状态 → 校验金额/归属/同ID载荷 → 创建operation并预留金额、line=RESERVED。相同operation重复直接返回记录；确定失败后的旧ID也不可重新占用。另一操作的活跃占用/成功状态拒绝。

成功事务：operation=SUCCEEDED，reserved减少，refunded增加，line=CONSUMED，写结果outbox。确定失败事务：operation=FAILED，reserved减少，line=FREE，写失败outbox；操作历史保留。所有终局更新检查前置状态/版本，重入不能重复结算。

provider请求固定key=operation_id，金额取持久快照；网络超时=UNKNOWN而非失败。再次发请求只可沿原key且provider保证幂等；查询NOT_FOUND在延迟可见窗口内仍保持UNKNOWN。单行允许重新申请仅限前一次确定失败并释放且产生新授权；不支持成功后再次退款。

## 4. 状态

Case：QUEUED→ANALYZING→WAITING_CUSTOMER/PENDING_REVIEW/AUTHORIZED/CLOSED_REJECTED；补证从WAITING_CUSTOMER增revision→QUEUED。AUTHORIZED消费→EXECUTING；UNKNOWN→RECONCILING；目标成功→CLOSED_SUCCESS；确定失败且金额释放→PENDING_REVIEW。再次执行须新revision、新方案、新授权，旧授权仍CONSUMED。消费前允许CANCELLED；消费后没有取消边。

Authorization沿用PENDING_REVIEW/APPROVED/REJECTED/EXPIRED/REVOKED/CONSUMED；Proposal沿用PROPOSED/VALIDATED/STALE/REJECTED。核心退款operation用RECEIVED/IN_PROGRESS/UNKNOWN/SUCCEEDED/FAILED；不启用旧STARTING/CANCELLED目标协议。

旧wire enum可作为兼容超集保留，核心profile必须有显式允许状态与转换测试；支持反序列化不代表允许执行。

## 5. agent_db

- agent_run：run/case/revision、parent_run_id、status、manifest_id、deadline_at/active_deadline_at、lease_owner/lease_until/fence、usage账。
- 官方LangGraph checkpoint表；写入必须与run fence校验在同一PG事务。
- model_call：稳定call_id、step/attempt、context_id、请求/响应、provider_request_id、usage、UNKNOWN。
- tool_observation：稳定call_id、工具/参数hash、scope、来源/版本/hash、原文、错误和时间。
- context_snapshot：实际请求及hash、保留/省略引用、关键事实hash、估算方式。
- harness_manifest：代码/Prompt/工具/模型/预算/政策索引固定配置，不存密钥。
- callback_outbox：幂等callback_id、run/revision、kind、载荷hash、重试状态。
- policy_generation/policy_chunk：绑定bundle/hash、embedding revision、原文和向量。

事实视图、预算预占可放run JSON/现有记录中，不强制独立EvidenceLedger表或完整session_event平台。更新仍需事务/唯一键；禁止内存成为唯一事实。模型未落库窗口可能重复计费。上下文/原文只使用合成数据且不含凭证。
