# 领域模型、状态与数据库约束

所有金额为long整数分；UTC时间存库，API ISO-8601带Z；ID为UUID字符串。version为数据库乐观锁版本；input_revision在工单决策输入变化或主动刷新决策快照时递增（包含授权过期后的重新调查），二者不得混用。ID含商家范围的查询必须同时约束merchant_id，不能仅依赖ID随机性。

## 1. 必须永久成立的不变量

| ID | 不变量 | 最终负责位置 |
| --- | --- | --- |
| INV-01 | refunded_amount + reserved_refund_amount <= paid_amount，且所有值非负 | commerce支付账事务+条件UPDATE |
| INV-02 | 同一订单行最多一个RESERVED、IN_USE或CONSUMED补救权益；退款和补发互斥 | commerce line_entitlement行锁/唯一键 |
| INV-03 | 同一operation_id与相同载荷只执行一次业务效果；换载荷必须409 | 目标服务operation表+payload_hash |
| INV-04 | 相同事件重复消费不再改变业务状态 | inbox唯一键+本地事务 |
| INV-05 | 旧input_revision方案不能授权；授权载荷不可变 | case授权事务 |
| INV-06 | Agent不能批准自己、篡改执行金额或跨主体查询 | Java资源级认证与授权 |
| INV-07 | provider UNKNOWN期间不释放金额/权益/库存 | operation状态与对账worker |
| INV-08 | 已退款/已发货的外部效果不能以本地回滚“撤销” | 正向补齐与人工处理 |
| INV-09 | 工单CLOSED_SUCCESS仅在目标操作和权益提交均确认后产生 | case编排状态 |
| INV-10 | 成功恢复运行不改变已确认业务授权 | run/input_revision/grant/operation边界 |

## 2. case_db

| 表 | 关键字段 | 约束/索引 |
| --- | --- | --- |
| demo_user | id, merchant_id, role, password_hash | login唯一；禁止明文密码 |
| aftersale_case | id, merchant_id, customer_id, order_id, line_id, status, requested_actions, input_revision, version, expires_at | (merchant_id,customer_id,created_at,id)；(merchant_id,status,updated_at,id) |
| active_case_slot | merchant_id, line_id, case_id | (merchant_id,line_id)主键；创建工单同事务抢占，终态可释放 |
| case_evidence | id, case_id, revision, source_type, source_ref, source_version, content_json, content_hash, observed_at | (case_id,revision,id)；追加保存、不覆盖 |
| agent_binding | case_id, input_revision, run_id, status | (case_id,input_revision)唯一 |
| proposal | id, case_id, run_id, input_revision, payload_json, payload_hash, status, created_at | run_id唯一有效最终方案；不可原地改载荷 |
| authorization | id, planned_operation_id, case_id, proposal_id, input_revision, action, computed_payload, payload_hash, policy_version, safety_epoch, evidence_digest, status, expires_at, version | proposal_id+payload_hash唯一；planned_operation_id唯一；一次消费 |
| approval | id, authorization_id, reviewer_id, decision, reason, authorization_version, created_at | authorization_id的终局决定唯一 |
| case_operation | id, case_id, authorization_id, action, payload_hash, state, entitlement_id, target_id, retry_at, version | authorization_id唯一；(state,retry_at) |
| case_timeline | case_id, sequence, event_type, public_payload, created_at | (case_id,sequence)唯一；SSE重放依据 |
| policy_bundle | id, merchant_id, version, category, effective_from, effective_to, published_at, status, safety_epoch, rules_json, source_hash | (merchant_id,category,effective_from)；发布事务检查区间不重叠 |
| audit_event | id, actor, case_id, operation_id, kind, reason_codes, hashes, created_at | 追加；普通业务角色无改删权限 |
| outbox | event_id, channel, destination, aggregate_id, aggregate_version, payload, status, lease_until, attempts, next_attempt_at | event_id唯一；(status,next_attempt_at) |
| inbox | consumer_group, event_id, payload_hash, processed_at | (consumer_group,event_id)主键 |
| request_idempotency | principal_id, route, idempotency_key, request_hash, resource_id, response_code | 三字段唯一；并发安全 |

policy发布同一merchant/category使用稳定的policy_scope行锁串行化，检查[from,to)区间；不能只靠内存扫描。请求幂等保留至少7天，operation与inbox去重不按缓存TTL提前删除，项目阶段保留全部实验记录。

## 3. commerce_db

- orders(id, merchant_id, customer_id, paid_at, status, version)。
- order_line(id, order_id, sku, category, quantity, line_paid_amount, currency)。金额为下单快照，禁止Agent计算优惠。
- payment_ledger(order_id PK, paid_amount, refunded_amount, reserved_refund_amount, version)。退款预留使用条件更新，余额不足为业务拒绝。
- line_entitlement(line_id PK, merchant_id, state FREE/RESERVED/IN_USE/CONSUMED, operation_id, action, version)。在同事务预留退款金额（仅REFUND），RESERVED和IN_USE不因TTL自动释放。
- refund_operation(id PK即operation_id, payload_hash, entitlement_id, amount, state, provider_key UNIQUE, provider_ref, next_check_at, version)。
- outbox/inbox与case相同语义。

权益reserve(line,operation,action)：相同operation重试返回原结果；其他占用返回409。start将RESERVED->IN_USE，commit将IN_USE->CONSUMED；release仅在可证明目标已禁止执行或确定失败时将RESERVED/IN_USE->FREE。commit/release重复调用幂等，跨operation禁止。为保存已释放operation的幂等结果，增加entitlement_operation(operation_id PK,line_id,action,payload_hash,state,result_ref,version)历史表；line_entitlement可指向下一次操作，旧operation重试不得重新占用。

退款成功本地事务：operation->SUCCEEDED，reserved_refund_amount-=amount，refunded_amount+=amount，entitlement->CONSUMED，写RefundSucceeded。确定失败则释放金额与权益并写RefundFailed。UNKNOWN维持预留。

## 4. fulfillment_db

- shipment(id, order_id, line_id, status, carrier_conclusion, version, updated_at)。
- shipment_event(id, shipment_id, source_version, occurred_at, code, payload_hash)：版本/事件ID去重，保留轨迹。
- packing_manifest(line_id, sku, shipped_quantity, verified_status, version)：有权威仓库记录时才能据此自动判断错漏发。
- inventory(sku PK, available, reserved, version)：条件更新，available>=0。
- stock_reservation(operation_id PK, sku, quantity, state RESERVED/CONSUMED/RELEASED)。
- reship_operation(id PK, payload_hash, entitlement_id, provider_key UNIQUE, state, next_check_at, version)。
- outbox/inbox。

创建补发在本地事务插入operation并预留库存；承运商确定接受生成运单后成功并消费库存。此后应将commerce权益提交（case编排负责），提交失败持续正向重试，不能释放已使用库存。确定失败可释放库存；UNKNOWN维持预留。补发成功定义为承运商持久接受补发单，非用户最终签收。

## 5. agent_db

- agent_run(run_id PK, case_id, input_revision, parent_run_id, status, reason_code, lease_owner, lease_until, fence, attempt, last_heartbeat, deadline_at, active_deadline_at, manifest_id, last_event_sequence)：(case_id,input_revision)唯一；manifest_id引用不可变配置。QUEUED准备阶段manifest_id/active_deadline_at可空；开始调查前原子绑定，之后不能更新配置或延长期限。
- LangGraph checkpointer表：使用已锁定官方PG实现迁移，不自己猜其内部Schema。
- tool_observation(id, run_id, tool_call_id, tool_name, args_hash, source_version, content_hash, result_json, observed_at)：(run_id,tool_call_id)唯一。
- model_call(id, run_id, step_id, attempt, context_id, status, model_id, request_hash, result_json, usage, latency, provider_request_id)：记录UNKNOWN调用以统计潜在重复成本；每次网络attempt独立ID，恢复复用已落库结果不新增请求。
- harness_manifest(manifest_id PK, schema_version, content_json, created_at)：内容hash寻址、不可原地更新，不保存凭证；code/prompt/context/tool/verifier/model/预算/政策索引均固定。
- context_snapshot(context_id PK, run_id, step_id, manifest_id, context_hash, protected_fact_hash, packet_json, created_at)：保存实际模型输入、裁剪记录和token计数方式；一个决策步可因修复产生多个调用，每个调用明确绑定快照。
- session_event(event_id PK, run_id, sequence, step_id, manifest_id, fence, event_type, schema_version, payload_ref, payload_hash, occurred_at)：(run_id,sequence)唯一；顺序由run行锁内分配；事件与对应结果同事务保存，不依赖日志到达时间排序。
- evidence_fact(id, run_id, fact_key, source_type, source_ref, source_version, observation_id, content_hash, observed_at, validity, value_json)：EvidenceLedger投影；保留冲突的多来源值，不用模型推断覆盖AUTHORITY。
- budget_reservation(call_id PK, run_id, input_reserved, output_reserved, status, actual_usage, count_mode)：请求前预占；完成结算，UNKNOWN不直接释放；更新计数和预占同事务并受fence保护。
- callback_outbox(callback_id PK, run_id, kind, payload_hash, payload_json, attempts, next_attempt_at, status)。
- policy_generation(id, manifest_hash, embedding_model, dimension, bm25_tokenizer_version, status BUILDING/READY/RETIRED)。
- policy_chunk(id, generation_id, bundle_id, version, merchant_id, category, text, content_hash, embedding)；BM25只在硬过滤候选范围内评分。

模型文本、trace、输入材料均不是数据库授权事实。敏感字段不可进入embedding、Prometheus标签或普通应用日志。

SessionStore是以上会话记录的仓储接口，不另建第二个状态系统。ReplayPack由已有记录导出；回放使用独立evaluation_run_id与临时评测库，不写原agent_run或callback_outbox。详细事件、快照字段和隔离规则见[回放规格](trajectory-replay.md)。默认项目只用合成数据，完整轨迹也不得含服务JWT、API key或原始授权头。

## 6. 工单状态机

| 当前状态 | 事件/条件 | 下一状态 |
| --- | --- | --- |
| 新建 | 身份及行校验通过 | QUEUED |
| QUEUED | run已领取回调 | ANALYZING |
| QUEUED/ANALYZING | 当前revision问题回调 | WAITING_CUSTOMER |
| WAITING_CUSTOMER | 材料追加，input_revision+1 | QUEUED |
| QUEUED/ANALYZING | 当前方案有效且可自动授权 | AUTHORIZED |
| QUEUED/ANALYZING | 当前方案需人工/异常接管 | PENDING_REVIEW |
| PENDING_REVIEW | 批准当前有效方案 | AUTHORIZED |
| PENDING_REVIEW | 审核拒绝且无执行 | CLOSED_REJECTED |
| AUTHORIZED | 原子消费授权并建立operation | EXECUTING |
| AUTHORIZED | 授权过期/撤销/输入改变，未消费；input_revision+1，旧授权失效 | QUEUED或PENDING_REVIEW |
| EXECUTING | 目标成功+权益提交 | CLOSED_SUCCESS |
| EXECUTING | 结果未知或补偿未收敛 | RECONCILING |
| RECONCILING | 所有成功条件满足 | CLOSED_SUCCESS |
| EXECUTING/RECONCILING | 确定失败且释放完成 | PENDING_REVIEW |
| QUEUED/ANALYZING/WAITING_CUSTOMER/PENDING_REVIEW | 用户撤销且没有活跃operation | CANCELLED |

执行后不能直接取消；人工修改方案先生成新proposal/authorization。成功、拒绝、取消终态不重开；另建工单也仍受commerce权益限制。WAITING_CUSTOMER默认72小时超时进入PENDING_REVIEW，不自动拒绝。过期定时器以数据库当前状态CAS处理，不能覆盖已收到的材料。

执行确定失败并释放后回PENDING_REVIEW，原authorization保持CONSUMED、原operation保持FAILED，不能重新批准它；再试须创建新revision及新人工/Agent方案。退款UNKNOWN不可走此路径，必须先确认终局。

authorization状态固定PENDING_REVIEW/APPROVED/REJECTED/EXPIRED/REVOKED/CONSUMED；自动授权直接APPROVED，人工批准PENDING_REVIEW->APPROVED。proposal状态固定PROPOSED/VALIDATED/STALE/REJECTED；proposal与authorization一经消费不得原地改载荷。

## 7. 执行编排状态机

case_operation：CREATED -> RESERVING -> RESERVED -> DISPATCHED -> TARGET_SUCCEEDED -> COMMITTING -> SUCCEEDED。

- reserve拒绝：FAILED（无占用）；进入人工。
- 发送/查询超时：RECONCILING，沿同一operation继续。
- 目标确定失败：RELEASING -> FAILED，必须确认库存/权益均释放。
- RESERVED但目标未确认接收：先查询目标operation；不能仅凭时间直接释放。确定不存在且case编排通过取消dispatch CAS停止后才能释放，消息迟到时目标必须校验权益仍有效，拒绝启动。
- target成功后仅允许正向提交，禁止进入释放路径。

“先查权益再执行”的HTTP读无法保证和release原子。因此目标operation落库后、provider调用前必须向commerce调用 start-entitlement(operation_id)：将RESERVED->IN_USE，与release互斥CAS；只有IN_USE才可调用provider。release要求目标已确认终局失败并由其关闭启动权限。见可靠性文件。

## 8. 乐观锁与乱序

目标refund_operation/reship_operation状态统一RECEIVED/STARTING/IN_PROGRESS/UNKNOWN/SUCCEEDED/FAILED/CANCELLED。RECEIVED可取消；STARTING表示已锁定启动意图，取消返回409，worker通过commerce权益确认再进入IN_PROGRESS。外部请求超时进入UNKNOWN，通过查询返回IN_PROGRESS或终局；SUCCEEDED/FAILED/CANCELLED不能原地重开。provider stub查询状态为NOT_FOUND/PENDING/SUCCEEDED/FAILED；NOT_FOUND在配置的延迟可见窗口内也不能直接认定无副作用。

所有状态更新使用id+version+允许前置状态；受影响行数0则重读，不覆盖。消息携带aggregate_version但不假定版本连续（订阅者可能只订阅部分事件）。旧版本忽略但保留inbox；跳跃或矛盾终态触发权威GET对账，再更新投影。工单timeline sequence在case事务内分配，不能用到达时间推断顺序。
