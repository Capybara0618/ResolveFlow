# 后端四条：实现、证据与面试展开

2026-10-27。只整理第1、4、5、7条，不改第1条原文、第4/5条冻结稿和Agent三条。本页是实现导航，不维护任务进度；性能结果分别看各批原始报告。

## 技术与业务落点

| 简历条目 | 可以展开的设计 | 直接证据 |
| --- | --- | --- |
| 1 多租户电商微服务 | 三个Java进程与一个Python Agent；Case持有身份/店铺绑定/工单/授权，Commerce持有商品/订单/评价/资金，Gateway为公共入口；买家跨店通过可信绑定查本人资源，商家查询带本店条件 | [核心范围](core-scope.md)、[买家范围](../java/case-service/src/main/java/com/resolveflow/caseservice/auth/BuyerScopes.java)、[主体解析](../java/case-service/src/main/java/com/resolveflow/caseservice/order/RequestPrincipalResolver.java) |
| 4 多商家交易与并发一致性 | 购物车revision检测旧修改；行锁与条件更新守住短事务；结算复核商品版本/价格并保存快照；同付款key复用原结果，订单/行/槽/账本同事务发布 | [冻结正文](resume-backend-trade-refund-frozen-20261026.md)、[160轮交易报告](../reports/backend-resume-v1/trade-formal.md) |
| 5 版本化授权与异步可靠退款 | 材料revision使旧授权失效；消费授权、执行状态、命令与Outbox同事务；至少一次投递+Inbox/业务幂等；整单金额预留与同行槽；UNKNOWN保留占用并查原操作 | [80行退款审计](../reports/backend-resume-v1/refund-formal-01/README.md)、[消费事务](../java/case-service/src/main/java/com/resolveflow/caseservice/casefile/AuthorizationConsumptionService.java)、[退款接收事务](../java/commerce-service/src/main/java/com/resolveflow/commerce/refund/RefundAcceptanceService.java) |
| 7 SQL查询与Redis缓存优化 | 订单页按页批量读取，保留筛选/游标/完整投影；工作台短缓存；公开评价epoch分代缓存与Redisson热点重建；Lua写限流及本机有界DB回源 | [D3实际SQL](../reports/backend-resume-v1/purchase-d3-01/README.md)、[D4真实双进程](../reports/backend-resume-v1/d4-functional-01/README.md)、[D5正常窗口协议](../reports/backend-resume-v1/d5-normal-01/README.md) |

## 第1条：边界怎样落在代码里

平台买家的buyer_id与每店customer_id通过Case内持久绑定转换；Commerce内部接口接收可信商家/客户范围，查询本身带条件。JWT声明与持久账号/identity_version对齐，不能只信前端传来的merchant_id。Gateway路由与服务间scope凭证是入口边界，业务服务仍复核资源归属。

租户主要是行级逻辑隔离；Case/Commerce独立库是按服务划分职责，不是每个租户单独建库。Python拥有run，Java拥有业务状态和金额。这解释了为什么Agent即使给出退款建议，也不能直接写资金表或代替审批。

“逐行独立退款”指资格、占用与结果按订单行区分；同订单多行仍共享支付账本，资金短事务按账本→行槽的顺序加锁。同单资金写入会短暂串行，不能把业务独立解释成完全没有锁等待。

## 第4条：为什么版本、行锁、幂等都需要

- **版本**：识别用户基于旧购物车/规格发起的修改，给出明确冲突。
- **行锁和条件更新**：防止两个已进入数据库的请求同时改变同一权威状态。
- **幂等key与不可变快照**：识别同一业务请求的重发；相同key不同内容拒绝，不能靠换key掩盖结果未知。

付款提供方的模拟收据与商城订单发布是两个提交边界。收据已成功而HTTP响应丢失时，后续查原attempt/收据，再补齐原订单发布；长网络请求不放在持有资金锁的数据库事务里。真实竞争证据是160个场景轮，不能说成160笔扣款。

入口见[CartService](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/CartService.java)、[MultiCheckoutService](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/MultiCheckoutService.java)、[CheckoutPayments](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/CheckoutPayments.java)。

## 第5条：MQ可靠性与资金正确性分层回答

Outbox解决本地业务已提交、消息未发出的窗口；Inbox/event_id识别重复投递，operation_id识别同一业务操作，payload_hash拒绝同ID换内容。MQ采用至少一次，消费端事务和业务约束共同保证效果，不宣称消息传输本身恰好一次。

Commerce先锁整单账本再锁本行槽，保证已退+预留不超过实付；同行只能有一个有效退款操作。网络调用在事务外；明确失败才能释放预留，UNKNOWN保留原operation_id与占用。对账查询原操作，不能因超时换ID再付。

授权的input_revision、资源的version、账号identity_version、消息event_id和业务operation_id各管不同问题。审批后、消费前仍可能撤销或因新材料失效；消费事务重新复核并冻结执行输入。80行模拟退款的零重复/超额是资金结果，故障是否准确触发仍按原报告分列。

## 第7条：SQL与Redis分别解决什么问题

订单列表原先取一页ID后逐单读取，SQL随页长增长。现在保留原候选筛选，将草稿头、子快照、最新付款、发布行、历史订单/行与退款账本按本页ID批量读取，查询同时约束商家和客户。D3混合夹具1/24/48条页实测4/110/238→4/8/8条SQL，完整DTO与游标一致。

Commerce单页使用只读RR事务并固定本页now；Case跨店页是多个受限分片页的归并，不是跨服务的全局数据库快照。详情继续读取权威记录。工作台保留已有复合索引/游标；D4未新增索引，D5不把相同SQL的A/B延迟波动宣传成新索引收益。

| Redis用途 | key/时效与边界 | 源码 |
| --- | --- | --- |
| 商家工作台页面 | 商家、主体/过滤/游标上下文、limit；TTL2秒；仅展示投影，审批和资金不读取它 | [RedisReviewQueueCache](../java/case-service/src/main/java/com/resolveflow/caseservice/casefile/RedisReviewQueueCache.java) |
| 公开评价首页及摘要 | product+数据库epoch，默认10条、TTL30秒；修改/回复推进epoch，旧代回填不会成为新代命中 | [ProductReviewReadCache](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/ProductReviewReadCache.java) |
| 热点评价重建锁 | 对同product/epoch的miss协调两个Commerce实例；等100ms、显式租约2秒，锁内二查；失租约跳过回填、释放时查所有权 | [ReviewRebuildLock](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/ReviewRebuildLock.java) |
| 写评价/商家回复限流 | 按账号+动作，Lua INCR/EXPIRE固定60秒窗6次，两个Case实例共享；Redis失败明确503 | [ReviewWriteLimiter](../java/case-service/src/main/java/com/resolveflow/caseservice/shopping/ReviewWriteLimiter.java) |

评价每次命中仍先查数据库epoch，换取修改后的新代可见性，所以不能称缓存命中零SQL。工作台和评价各有本机8个DB许可、等待100ms；双Commerce合计最多16个许可，不是一个全局8。Semaphore负责限制回源并发，Redisson负责减少同key重复重建，Lua负责账号写请求频率。

锁使用独立Redisson core客户端，与现有Lettuce缓存/Lua共存。显式租约避免把恢复依赖于旧进程续期；进程超租约暂停时可能出现重叠，所有权检查保护新owner，epoch保护新内容。它是展示数据重建锁，资金仍由MySQL的行锁、唯一约束和状态机保护。

## 面试讲数字时的对应关系

先说接口、数据规模、并发、对照构建和计量层次，再说结果。D3的每页SQL次数、D4的故障行为、D5的Gateway HTTP延迟各自有不同分母；不把单次EXPLAIN耗时或开发门控重建降幅当端到端p95。D5正常和故障结果完成审计后，按报告的成功延迟、错误/503、SQL/成功与SQL/总请求一起解释。

MyBatis的结果读取未被v3行计数全覆盖，rows_returned只是部分观测，不作为总返回行或扫描行。所有实验是本地合成业务/模拟资金；系统经验来自真实实现和可重复记录，不声称商用流量或生产集群。
