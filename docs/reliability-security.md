# 可靠性与安全执行设计

## 1. 本地事务与Outbox

业务状态变更、领域事件outbox写入同一MySQL事务。dispatcher用SKIP LOCKED领取短租约，发送成功后标SENT；数据库提交后发送前崩溃会延迟，发送后标记前崩溃会重复。不能把broker ACK解释成业务已完成。

消费者事务：插入inbox唯一键 -> 校验载荷hash和状态 -> 插入/更新本地operation及outbox -> commit -> ACK。外部provider调用不得放在此数据库事务中；由本地operation worker执行。失败回滚不ACK；已存在inbox且hash一致则ACK。

HTTP Outbox用于Java到Python、PG callback_outbox用于反向回调，同样是至少一次。两端以独立幂等ID应答，ACK只在本地事务提交后发送。重试耗尽进入持久异常队列，UI显示待人工，保留显式重驱入口。

## 2. 执行授权的精确语义

1. Agent方案绑定case_id/input_revision、evidence refs、policy refs、建议动作。
2. case权威复核：证据版本/归属、结构化政策、用户已选动作、金额/数量。获取最新权益和物流快照，保存checked_at及source_version。
3. case数据库事务CAS确认input_revision未变、policy safety_epoch未变，生成不可变authorization。人工批准与自动批准都写actor及规则版本。
4. 授权默认15分钟到期。消费授权时，在同一case事务校验当前revision/状态/epoch/expiry，把APPROVED->CONSUMED，创建唯一operation及编排outbox。消费与撤销竞争由同库CAS决定。
5. 一旦CONSUMED，后续政策变更不能假装撤销已承诺操作；进入执行/对账。若尚未目标启动可尝试cancel-before-start，否则记录事后人工处理。

本设计用数据库授权记录代替把一次性执行token发给模型。批准载荷hash绑定动作、行、金额、数量、原地址hash；换载荷必须新方案新授权。

跨服务快照不具有全局原子性。金额、补救互斥由commerce事务强制；政策撤销与授权消费同在case事务排序；物流外部事实可能在检查后改变，这是已知业务窗口。自动授权只接受已确认丢件/已核验仓库差异，疑义转人工，不能宣称分布式快照绝对最新。

## 3. 退款过程

- case创建operation，commerce reserve以同一operation占用行权益与行金额。
- commerce消费RefundRequested持久操作；operation worker调用start权益，使RESERVED->IN_USE，CAS防止并发释放。
- provider退款请求使用稳定operation_id作为幂等键，payload包含原支付单与精确金额。
- provider确认成功：本地事务记录成功、金额转已退款、权益CONSUMED、outbox成功事件。
- provider明确拒绝且保证无副作用：本地事务记录失败、释放金额/权益、发布失败。
- 超时/断线/5xx结果不明：UNKNOWN，保持所有占用，先GET provider status。同一幂等键重试仅在provider协议支持且查询确认可重试时使用。

模拟provider必须将operation_id、payload_hash、结果保存在独立持久库中；支持“提交成功后丢响应”、延迟可见、确定拒绝、重复键换载荷。进程内字典不满足故障实验。

## 4. 补发Saga

1. commerce reserve行权益（action=RESHIP，无金额预留）。
2. fulfillment消费命令、持久operation；库存预留使用条件UPDATE并在本地事务写stock_reservation。
3. 目标worker start权益，得到IN_USE后调用承运商stub（稳定operation_id）。
4. 确定接受运单 -> fulfillment成功并消费库存 -> case幂等commit commerce权益 -> 工单成功。
5. 库存不足或承运商确定失败 -> fulfillment关闭启动权限/释放库存 -> case调用权益release -> 回人工。
6. 承运商UNKNOWN -> 不释放库存和权益；持续查询，超过10分钟仍未知进入人工对账队列但不解锁权益。

reserve后尚未收到目标响应：先目标cancel-before-start建立墓碑，确认目标已禁止启动，再release权益。迟到命令遇墓碑直接终结；start与取消竞争时目标worker须以同一operation行锁/lease串行化状态，不在持锁期间调用网络。目标进入STARTING后取消返回409，若start响应丢失，通过权益查询推进，不能假定取消成功。

release由commerce验证target的终局失败/取消记录（带内部认证或结果签名），IN_USE不能由超时定时器直接释放。目标成功后commit失败只正向重试；不存在“把已寄出的包裹回滚”。

## 5. 对账与重试边界

- dispatcher退避：1/2/5/10/30/60秒加抖动，超过20次进入FAILED_DELIVERY，人工可显式重驱原ID。
- operation query对账：前2分钟每5秒，此后每30秒，10分钟后标人工关注但保留低频查询；时间由可注入Clock测试。
- 只有读/幂等写可以重试；未知结果不能换新的operation_id。
- RECONCILING/UNKNOWN本身不是失败，UI和指标区分未完成、确定失败和成功。
- case投影丢事件或版本矛盾时主动GET目标状态；无法查询则保留旧投影并标过期。
- DLQ重驱保留原event_id，已处理inbox不会重复执行；若修正业务载荷须新事件ID与审计关系，不能悄悄改旧消息。

RocketMQ的重试/死信行为见[官方文档](https://rocketmq.apache.org/docs/featureBehavior/10consumerretrypolicy/)。项目的资金约束仍必须由数据库和provider幂等共同保证。

## 6. 缓存与性能

订单不可变摘要缓存key包含merchant/customer/order-line，读取前仍校验身份。Cache Aside TTL60秒+抖动，空值TTL5秒；single-flight/短锁防止同实例/多实例重建风暴。Redis失效时限量回源，不能无限并发压库。

授权相关的可退金额、权益、政策撤销状态必须查权威库/接口，不从展示缓存放行。可变展示缓存提交后outbox失效+短TTL；承认并测量短暂陈旧窗口，不声称强一致。v1不默认延迟双删、布隆过滤器、分库分表。

关键SQL：工单队列按merchant/status/updated_at/id游标，outbox按status/next_attempt_at，operation按state/next_check_at。用EXPLAIN ANALYZE与固定数据规模比较，优化前后同环境同负载。

## 7. 权限与注入

- Spring Security在资源服务验证JWT及scope，网关不是唯一权限点。
- 演示用户JWT RS256，固定issuer/aud、15分钟TTL；内部service JWT独立aud/scope，运行时密钥挂载不入库/日志。
- 工具token绑定run与订单行，每次续签检查当前revision；Agent不可自签。stdio适配器从受控context取得身份，绝不信任模型参数。
- 客户材料和政策文本带source标签，工具allowlist、Pydantic校验、只允许固定Java base URL，无任意HTTP/SQL/shell工具。
- 审批必须是商家内REVIEWER；审批payload改变、新材料、过期、政策撤销均使未消费授权失效。
- 证据伪造hash/引用无效先拒绝或人工；模型生成的“仓库确认”不是仓库事实。

stdio工具模式不开放公共MCP授权服务器；若未来改远程MCP必须另做OAuth/受众验证，禁止直接转发用户token。参照[MCP安全说明](https://modelcontextprotocol.io/docs/2025-11-25/tutorials/security/security_best_practices)。

## 8. 观测

HTTP透传traceparent；消息信封携带traceparent，消费者新span关联生产span；Agent run span关联case请求，工具和模型子span记录类型/耗时/结果。可在重投时使用span link保留多个投递来源。

业务指标：outbox_age、inbox_duplicate_total、operation_unknown、reconciliation_age、entitlement_conflict、unsafe_execution_rejected、run_queue_age、llm_tokens、tool_error、policy_index_lag。case_id/run_id放trace/log，禁止放Prometheus高基数标签。日志不存完整材料、密钥、审批凭证。

审计日志追加且普通角色无改删权限；数据库管理员仍可能修改，不能宣称“不可篡改”。数据库审计与OTel trace不同：前者业务依据，后者诊断，采样丢trace不允许丢审计。

v1.1 Harness增加context_overflow、budget_stop、no_progress_stop、model_usage_unknown、manifest_mismatch与replay_miss计数；只用有限枚举标签，manifest_id/context_id等放关联日志或专用表，不作为指标标签。SessionStore专门保存合成材料/模型请求快照，区别于普通应用日志；默认禁止包含凭证。回放不持有业务JWT，严格模式禁网络，反事实live仅允许受控模型出口，具体见docs/trajectory-replay.md。
