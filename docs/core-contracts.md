# 核心版协议目标 · v1.2

这是C00要落地的协议目标，不表示目标Schema/OpenAPI已实现。[contracts.md](contracts.md)及现有根目录Schema/OpenAPI继续作为T02已验证的旧基线。不要直接改其语义后沿用旧版本号。

## 1. 迁移方式

C00建立contracts/core/：openapi-case.yaml、openapi-commerce.yaml、openapi-agent.yaml、refund-command.schema.json、event-envelope.schema.json、agent-proposal.schema.json及核心正反fixture；同步Java/Pydantic类型与独立核心路由覆盖测试。

新退款命令/信封schema_version=2，使用独立URN，不与旧v1消费者混用；事件仍名RefundRequested/RefundSucceeded/RefundFailed/RefundUnknown，但topic固定rf.case.core.v2及rf.commerce.core.v2。核心Agent方案schema_version=2且不允许RESHIP，其他字段复用旧结构。控制面与公共HTTP可保留/internal/v1和/api/v1，因为尚无运行中的业务客户端；以核心OpenAPI明确标注core-v1.2部署profile，不承诺与旧目标API全集兼容。

旧四份OpenAPI/fixture/枚举/hash测试保留为兼容测试，不据此开放旧写接口。核心启动只接新topic，只用核心协议适配器；为使旧fixture通过而临时伪造entitlement_id禁止。manifest继续使用现有独立schema_version=1，不因业务命令升级强制改版本。

## 2. 公共约定

JSON用snake_case。Authorization JWT；service JWT独立aud/scope。外部写需Idempotency-Key，更新已有资源需If-Match；同key换body409。错误体仍是{code,message,retryable,trace_id,details}。主体来自认证上下文；模型不得指定tenant/customer/run等身份。

金额1..1,000,000,000分、整数，revision/version不超2^53-1，时间UTC带Z，UUID不是权限。canonical JSON和Ed25519签名复用已实测实现；新核心payload_hash只覆盖：
{operation_id,case_id,authorization_id,input_revision,line_id,merchant_id,action,quantity,currency,amount_minor,policy_version,target_service}。
不含自身hash、trace、发送时间；没有entitlement_id/address_hash。授权创建时预分配operation_id并固定载荷。事件签名覆盖除signature自身以外的规范化信封（含signing_key_id），无Bearer token。

## 3. 核心路由

用户角色来自Case持久账号。REVIEWER/MERCHANT_ADMIN/原OPERATOR读取本商家工单；人工写入必须是当前负责人并携带原业务及协作版本，管理员须显式接管。CUSTOMER分旧商家客户和平台买家两种互斥身份，后者只携带buyer_id，经可信(merchant,customer)映射汇总本人订单/申请及限定实际资源的售后操作；客户不能修改映射、扩大工作人员或Agent范围。仅MERCHANT_ADMIN可维护本商家账号，平台买家不属于商家管理员维护范围。内部订单keyset由共享v2游标保留微秒，兼容旧毫秒编码；平台外层游标绑定买家和启用归属。见[平台买家](platform-buyer.md)、[持久身份](persistent-identity.md)、[协作](case-collaboration.md)及[人员管理](staff-management.md)。

| 所属 | 方法与路由 | 行为 |
| --- | --- | --- |
| Case | GET /api/v1/shop/stores | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Case | GET /api/v1/shop/stores/{store_id} | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Case | GET /api/v1/shop/products | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Case | GET /api/v1/shop/products/{product_id} | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Case | POST /api/v1/shop/quote | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Case | POST /api/v1/shop/drafts | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Case | GET /api/v1/shop/drafts/{draft_id} | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Case | POST /api/v1/shop/drafts/{draft_id}/payment | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Case | GET /api/v1/shop/drafts/{draft_id}/payment | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Case | POST /api/v1/shop/drafts/{draft_id}/cancel | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Case | GET /api/v1/shop/purchases | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Case | GET /api/v1/shop/purchases/{purchase_id} | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Commerce | POST /internal/v1/shop/drafts/{draft_id}/payment | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Commerce | GET /internal/v1/shop/drafts/{draft_id}/payment | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Commerce | POST /internal/v1/shop/drafts/{draft_id}/cancel | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Commerce | GET /internal/v1/shop/purchases | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Commerce | GET /internal/v1/shop/purchases/{purchase_id} | docs/simulated-checkout-payment.md；本人复合归属、原尝试模拟付款及交易投影 |
| Commerce | GET /internal/v1/shop/stores | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Commerce | GET /internal/v1/shop/stores/{store_id} | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Commerce | GET /internal/v1/shop/products | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Commerce | GET /internal/v1/shop/products/{product_id} | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Commerce | POST /internal/v1/shop/quote | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Commerce | POST /internal/v1/shop/drafts | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Commerce | GET /internal/v1/shop/drafts/{draft_id} | docs/catalog-checkout.md；公开目录或受可信归属约束的独立待支付草稿 |
| Case | POST /api/v1/auth/login | 持久化本地账号登录；商家/角色/客户归属来自账号，启用状态及identity_version控制会话 |
| Case | GET /api/v1/auth/me | 当前有效会话资料；每个用户接口重新校验持久账号启用状态、归属、角色及身份版本，不返回密码hash |
| Case | GET /api/v1/admin/overview | docs/merchant-workspace.md；本商家真实协调汇总，只读 |
| Case | GET /api/v1/admin/policies | docs/merchant-workspace.md；管理员本商家政策只读列表 |
| Case | GET /api/v1/admin/policies/{bundle_id} | docs/merchant-workspace.md；原文及精确hash索引状态，历史钉住版本不变 |
| Case | GET /api/v1/admin/accounts | docs/staff-management.md；仅本商家管理员，独立账号版本/身份失效与审计，保护最后启用管理员 |
| Case | POST /api/v1/admin/accounts | docs/staff-management.md；仅本商家管理员，独立账号版本/身份失效与审计，保护最后启用管理员 |
| Case | POST /api/v1/admin/accounts/{username} | docs/staff-management.md；仅本商家管理员，独立账号版本/身份失效与审计，保护最后启用管理员 |
| Case | POST /api/v1/admin/accounts/{username}/password | docs/staff-management.md；仅本商家管理员，独立账号版本/身份失效与审计，保护最后启用管理员 |
| Case | GET /api/v1/admin/accounts/{username}/history | docs/staff-management.md；仅本商家管理员，独立账号版本/身份失效与审计，保护最后启用管理员 |
| Case | GET /api/v1/review/staff | 本商家启用工作人员的只读显示身份，供转交选择；不返回客户、口令或其他商家账号 |
| Case | GET /api/v1/cases/{case_id}/collaboration | 本商家工作人员读取独立负责人、协作版本和操作历史；历史未领取为版本0，不修改工单/Agent |
| Case | POST /api/v1/cases/{case_id}/collaboration | 带If-Collaboration-Match原子领取/释放/转交/管理员显式接管；账号锁内复核签名身份版本，消费/已批准/执行/终态冻结，详见docs/case-collaboration.md |
| Case | GET /api/v1/customer/cases | 本人分页申请列表，view/line_id筛选、微秒游标；只从有效身份取merchant/customer |
| Case | GET /api/v1/customer/cases/{case_id} | 客户专用最小详情、问题/回答、允许动作及公开结果；不返回工作人员投影 |
| Case | GET /api/v1/customer/order-lines/{line_id} | 本人订单行与当前申请/全额预检，真实金额由Commerce提供 |
| Case | POST /api/v1/customer/cases/{case_id}/answers | 当前问题文本回答，If-Match＋question_id在工单锁内校验；追加材料、新修订调查与旧授权失效复用原路径 |
| Case | GET /api/v1/orders | 当前主体订单视图；内部请求Commerce |
| Case | GET /api/v1/orders/{order_id} | 本人/商家授权订单 |
| Case | POST /api/v1/cases | line_id/description/requested_actions=[REFUND] |
| Case | GET /api/v1/cases/{case_id} | 状态、客户原始问题描述、订单 ID 与公开证据；按现有主体权限读取 |
| Case | POST /api/v1/cases/{case_id}/evidence | 追加材料并增revision、回到QUEUED且创建新run绑定；回答追问须关联当前question_id；消费后409 |
| Case | POST /api/v1/cases/{case_id}/cancel | 仅授权消费前可取消 |
| Case | GET /api/v1/cases/{case_id}/events | SSE，Last-Event-ID，鉴权不放URL |
| Case | GET /api/v1/review/cases | 本商家队列：view阶段＋scope PUBLIC/MINE/UNCLAIMED＋query；真实负责人/协作版、全量匹配计数、绑定账号与筛选的精确keyset游标；无三参数保持旧待审缓存页；客户403、非法/错筛选游标400 |
| Case | POST /api/v1/cases/{case_id}/reviews | 人工决定当前授权；`If-Match`为工单版本、body带授权自己的版本，任一过期409；批准前重新校验；客户角色403 |
| Case | POST /api/v1/cases/{case_id}/reviewed-evidence | 人工核验追加，不改原材料：新记录引用被核验记录（`reviewed_evidence_id`）并带 `verification_result`，推进revision、回到QUEUED并创建新run绑定；客户角色 403，跨工单引用 422 |
| Case | POST /api/v1/cases/{case_id}/manual-proposals | 新revision/方案，非直接付款 |
| Case | GET /api/v1/cases/{case_id}/review-context | 商户人员读取当前工单版本、实际允许动作、绑定政策原文、人工决定与当前授权的执行结果；无政策为UNAVAILABLE，跨商户/不存在同为404 |
| Case | POST /api/v1/cases/{case_id}/review-actions | 带If-Match的审核动作：MANUAL_PROPOSAL（金额仍由Java重算）/REJECT/REQUEST_INFO；不伪造授权，输入修订与状态同事务推进使旧调查失效；已消费输入冻结 |
| Case | GET /api/v1/cases/{case_id}/investigation | 商户人员只读当前修订绑定的调查原始记录；无绑定NOT_SCHEDULED，下游故障或历史缺失UNAVAILABLE；不重跑模型/工具 |
| Case | POST /api/v1/operations/{operation_id}/reconcile | OPERATOR请求查状态，不再次付款 |
| Agent | POST /internal/v1/runs | PG落库后202，同case/revision唯一；`run_id`由Case从`(case_id,input_revision)`派生（RFC 9562 v5），重试得到同一个id |
| Agent | GET /internal/v1/runs/{run_id} | 受权运行摘要 |
| Agent | GET /internal/v1/runs/{run_id}/observations/{observation_id} | 仅Case校验证据 |
| Agent | GET /internal/v1/policies/{bundle_id}/index-status | docs/merchant-workspace.md；case-service + policy:read + merchant，精确hash只读持久索引 |
| Agent | GET /internal/v1/runs/{run_id}/review-sources | case-service身份+run:review scope，与持久run的case/revision完全匹配；只读已保存工具结果，最多40条，超32768字节正文省略；不返回SDK对话、请求体或凭证 |
| Agent | POST /internal/v1/runs/{run_id}/cancel | 停后续调查，不承诺撤回已发LLM计费 |
| Agent | GET /health | 健康 |
| Case | POST /internal/v1/cases/{case_id}/agent-callbacks | callback_id幂等，ACCEPTED/DUPLICATE/STALE |
| Case | POST /internal/v1/runs/{run_id}/tool-credential | 当前revision受限工具凭证 |
| Commerce | GET /internal/v1/order-lines/{line_id}/context | 权威订单/支付/行金额；core追加order_paid_amount与line_refund_state，原金额成员仍是整单合计；本行FREE按整单余款复核，见cart-multiline-checkout.md |
| Commerce | GET /internal/v1/order-lines | 按主体列出订单行，供Case构建公共订单视图 |
| Commerce | GET /internal/v1/order-lines/{line_id}/shipment | 明确标synthetic的版本化物流数据 |
| Commerce | GET /internal/v1/order-lines/{line_id}/refund-status | 已退/预留/当前退款状态 |
| Commerce | GET /internal/v1/operations/{operation_id} | 权威退款状态，供Case对账 |
| Case | GET /internal/v1/cases/{case_id}/evidence | 当前case材料及来源 |
| Case | GET /internal/v1/cases/{case_id}/policy-manifest | 绑定bundle/version/hash |
| Case | GET /internal/v1/policies/{bundle_id} | 授权政策正文/规则 |
| Case | GET /api/v1/shop/cart | 平台买家本人按店持久购物车；故障不返回部分空车 |
| Case | POST /api/v1/shop/cart/{store_id}/items | 可信绑定、绝对数量、购物车版本及原键幂等 |
| Commerce | GET /internal/v1/shop/cart/{store_id} | 仅Case checkout身份，本店本人含不可售条目 |
| Commerce | POST /internal/v1/shop/cart/{store_id}/items | 持久CAS和幂等回执，不发布订单或资金 |
| Case | POST /api/v1/shop/cart/{store_id}/quote | 本人本店选行，当前数量/价格/版本，总额上限 |
| Case | POST /api/v1/shop/cart/{store_id}/drafts | 原键不可变多行草稿与同事务选行移除，其他店保留 |
| Commerce | POST /internal/v1/shop/cart/{store_id}/quote | 仅Case checkout，可信主体及购物车版本 |
| Commerce | POST /internal/v1/shop/cart/{store_id}/drafts | 价格锁/行快照/幂等，多行付款发布复用原尝试 |

核心不开放旧entitlements、packing、cancel-before-start或补发端点。政策由受控脚本导入校验，不做管理HTTP全集。版本按订单行**支付时间**选择：取生效起点最晚且未被显式结束的版本，因此无结束日期的版本会被后继版本取代，而历史订单不会被新政策套用；选中的版本与hash在开单事务中钉在工单上，之后导入新版本不改变已开工单。Order API的公共归属仍为Case，以复用现有协议模式；不暗改网关到数据库。

政策路由同时发布每条规则的`chunk_id`与`content_hash`，因为方案引用的`PolicyRef`要求这两个成员：只有这条路由发布规则，run能引用的hash只能从这里抄。两者都由**已存正文派生**（chunk按规则在bundle中的位置编号，hash取bundle_id/chunk_id/title/text的规范JSON），不存库、不读导入文件，与bundle自身manifest hash同一构造；跨语言固定值在`contracts/fixtures`中冻结，Java与Python各自重算同一digest，否则引用核对不可验证。

## 4. 运行与回调

run请求沿用run/case/input_revision、受控context(merchant/customer/order/line)、request、policy_manifest、deadline_at、traceparent；body主体必须与service JWT及Case绑定一致。

回调kind为STARTED/QUESTION/PROPOSAL/FAILED；QUESTION与PROPOSAL互斥终局。QUESTION含稳定question_id、最多3个问题及原因；PROPOSAL使用核心方案Schema；FAILED含原因、已知观察ref。旧revision/人工接管后返回STALE且不重试；相同callback换载荷拒绝；STARTED迟到不回退状态。

PROPOSAL的接受分两类：结构或绑定错误（`schema_version`、`case_id`/`input_revision`与工单不一致、未知`case_type`/`recommended_action`、非REFUND带金额、`source_ref`是URL等）是422——这条消息不是方案；**可检内容**则是"已核对并被拒"的持久事实，存`case_proposal`为`REJECTED`并写`refusal_reason`。可检部分全用本服务自己的记录：引用必须落在工单钉住的版本上（`bundle_id`在钉住集合内、`version`等于库存版本、`rule_id`+`chunk_id`存在且重算`content_hash`相符——引用新版本、引用已改正文、引用不存在规则都算拒绝），REFUND必须至少一条政策引用，金额从Commerce行上下文重算（paid−refunded−reserved，且必须仍属该工单的商家与客户），`suggested_amount_minor`只保留作对照；重算为0或低于建议值即拒绝。`VALIDATED`只说明引用与金额通过了本服务的核对，不等于批准，也不代表run结论正确；两种结果都使工单进入`PENDING_REVIEW`（人工接管后同一revision再投递即STALE）。

人工核验（`reviewed-evidence`）与客户材料一样是**追加**：新记录用`reviewed_evidence_id`引用被核验的那一条、用`verification_result`记下CONFIRMED/REFUTED/INCONCLUSIVE，被核验记录的正文与hash一律不动（表内没有update/delete语句，引用是`(case_id, evidence_id)`外键，跨工单引用在库层面不可能）。核验对象必须是本工单的**材料**而不是别人核验的结论（核验的核验会让"核的是什么"退化成链条），客户角色不能记录核验（403）。`EvidenceView`是工单视图里材料的样子：引用形状+正文+谁在哪个revision追加的；核验结论因此是结构化事实而不是要人去解析的句子，而`EvidenceRef`（方案引用与内部复读用）仍然**不含正文**——引用不能变成夹带未核验文本的通道。核验结论本身不撤销授权：**撤销它的是输入revision被推进**（见下一段），CONFIRMED与REFUTED在这件事上效果相同——把失效归因于结论会让读者以为"确认过的材料就不会让批准失效"。`revoked_authorization_id`缺失的含义是"本来就没有活授权可撤"，不是"没人检查过"。

**任何新输入都让该工单的活授权不再算数**（C03.3c）：授权固定在它创建时的`input_revision`上、`payload_hash`也是按那份输入算的，所以revision一旦前进，这笔批准描述的就是工单已经没有的输入。三条写新输入的路由——追加材料、人工核验、人工方案——因此都在**写入的同一个事务里**把活授权置`REVOKED`（不是`EXPIRED`：有人做了动作撤掉它），`decision_reason`写明是哪次动作与推进到哪个revision。追加材料和人工核验把工单置`QUEUED`并创建新revision的持久run绑定；旧proposal读作`STALE`，旧revision回调也只能得到`STALE`。人工方案已经给出了新revision的方案，所以直接进入`PENDING_REVIEW`并形成新授权。状态因此始终对应实际下一步，不会出现“旧授权失效但没有重新调查”的空窗。

**人工方案**（`POST /api/v1/cases/{case_id}/manual-proposals`）是"没有run跑出方案时人怎么给出一个可执行方案"：请求只带作者看过的依据（`action`/`evidence_refs`/`policy_refs`/`reason`），**没有金额成员**——金额仍由本服务从Commerce行上下文重算（`docs/product-spec.md:25`），存下来的方案文档由服务自己拼（作者的`reason`就是`summary`，`recommended_action`是那条命令的动作），`origin`/`authored_by`/`authored_role`走**列**而不是写进载荷：人是作者这件事是工单的事实，不是方案文档的成员。它复用与run方案完全相同的内容校验（引用必须落在钉住版本上、hash可重算、REFUND至少一条政策引用），因此"人工方案也要核验"不是对另一份实现的承诺；差别只在被拒之后：人的提交**先检查后记录**，被拒就什么都不写（人还在线，能改），而run的投递是持久事件、说什么都得记下来。提交**推进输入revision**（人的引用集是新决策输入，不是对run方案的评论），所以上一个revision的方案与授权随之作废，`AUTHORIZED`的工单回到`PENDING_REVIEW`——这正是上一段那条规则在三条路由上的同一次应用。作者是谁只决定谁能提交：客户角色403（材料引用是商家的论点，不是当事人的诉求），跨商家404。

授权（`AuthorizationState`）在**通过重检的那一刻**与方案同事务创建，不是等人打开页面时才算：`operation_id` 此时预分配、`payload_hash` 此时按12个命令字段算定，两者都写进轨迹的"等待人工审批"行。这条顺序是"重试不会多付一次"的全部依据——载荷在批准之前就固定了，批准只是把已固定的载荷放行，重试只能复用同一个 operation id。授权因此带着**自己的** `input_revision`：材料在批准前到达会把工单推到新revision，而授权仍然描述它创建时的那份输入，所以读模型必须能让审批逻辑（和读页面的人）看到两者不同，而不是拿工单的当前revision去冒充。只有"通过重检且会动钱"的方案才会产生授权：被拒方案没有可批准的东西，通过重检但不动钱的建议也没有本服务能执行的东西，给它们建一行等于把无法执行的批准摆到审核员面前。`expires_at`目前一律缺失（核心没有到期策略），授权的失效要么是被取代、要么是被撤销、要么是被消费。

Java校验证据时按固定source_ref映射查询权威数据，而非信任Python文字。用户材料不是权威退款依据，ref不是可请求的任意URL。工具token绑定run/case/revision/merchant/customer/line/aud/scope，续签需Case确认有效，模型看不到token。

人工决定（`POST /api/v1/cases/{case_id}/reviews`）用**两把锁**管两件不同的事：`If-Match`是审阅者读过的**工单**版本（这条路由上的ETag就是工单版本，读页面和提交决定必须看同一个版本），body里的`authorization_version`是授权**自己**的版本。任一过期都回409且不写任何东西——两者都过期时也是先报工单那把锁，因为"你读的是旧页面"是更根本的那条。**决定终局**不是靠事前检查：版本与`status = 'PENDING_REVIEW'`一起写进UPDATE的WHERE，所以两个人同时决定时第二个必然匹配0行（docs/domain-model.md:31）；这也意味着同一个请求体第二次提交是409，而不是"和上次一样所以成功"。

三种决定各有后果，且都不等于"执行"。`APPROVE`先把授权置`APPROVED`（版本+1），再把工单推到`AUTHORIZED`——**不消费、不派发**，消费是派发事务的事（C05.2a：工单`AUTHORIZED→EXECUTING`、授权`APPROVED→CONSUMED`、签名命令写入`event_outbox`与`case_execution_command`四件事同一事务，由默认关闭的`ExecutionDispatchLoop`触发；批准与前消费之间那个窗口是取消和"被新输入撤回"真正活着的地方），把批准和付款合成一步会让"批准了但还没付"这个真实状态无处安放。批准前重新校验三件事，且三种失败**不是同一种失败**：授权固定的`input_revision`是否仍是工单的revision、`payload_hash`能否从本服务自己的行重算出来——这两件是关于**本服务固定下来的载荷**的陈述，不成立就是永久的，授权转`EXPIRED`并在`decision_reason`写明哪个事实动了（拒绝本身不能把这个失效回滚掉，所以这条路径用`noRollbackFor`保住它），工单留在`PENDING_REVIEW`由人处理；Commerce说这一行当前付不起则是关于**世界**的陈述，只回409、不令授权作废，因为明天可能又能付，把世界的变化写成这个服务的终局决定是越权。`REJECT`置`REJECTED`、工单转`CLOSED_REJECTED`、释放活跃slot并写`CASE_CLOSED`行：拒绝是对这份输入的结论，而该工单没有第二个活授权，留在`PENDING_REVIEW`只会让它永远躺在队列里。`REQUEST_INFO`置`EXPIRED`（不是`REJECTED`：核验者问的是问题，没有否决）、工单回到`WAITING_CUSTOMER`——客户补材料会把revision推走，而载荷是给旧revision定的，所以它此后不可能再被应用。三种都写`AUTHORIZATION_DECIDED`轨迹行，并把`decided_by`/`decided_role`/`decision_reason`/`decided_at`落库（`AuthorizationState`因此多出四个可空成员：无人决定时缺失而不是null）；决定者只能是REVIEWER或OPERATOR（客户角色403，被决定的人不能自己批），角色记进库里而不是假定。

授权表的**活授权唯一**由库保证：`live_marker`是`status`的生成列（`PENDING_REVIEW`/`APPROVED`时为`'LIVE'`，其余为NULL），唯一键在`(case_id, live_marker)`上，而MySQL的唯一索引允许多个NULL，于是一个工单可以有任意多个已终结的授权、同时最多一个活授权。"这个工单可以执行哪一次授权"因此是单行事实，由schema而不是每个写入者记得检查来保证（C03.3c的取代就建在这条不变式上）。`PENDING_REVIEW`必须没有决定列、`APPROVED`/`REJECTED`/`CONSUMED`必须有全部决定列、`EXPIRED`/`REVOKED`两者皆可——"被取代"背后没有人，"被要求补材料"背后有人，拒绝存下这个差别就是丢掉谁问的。

## 5. MQ与授权

command仅action=REFUND、target_service=commerce-service；由Case签名，Commerce验证producer、签名、hash、目标、归属和金额。授权消费与命令outbox同Case事务，授权消费后不允许更改/撤销。授权消费之前必须查证据/政策最新状态；消费后的已承诺命令不因队列延迟使授权过期而撤回。

结果payload含operation_id,line_id,state,amount_minor,provider_ref可空,reason_code,aggregate_version。Commerce签名结果，Case验证来源及签名；错误producer不能伪造成功。inbox、投影和本地timeline在同事务。未知状态不是失败；乱序/矛盾结果向Commerce查询，不凭MQ顺序更新。

## 6. C00验收

新Schema拒绝补发、负数/浮点、错target、伪造来源及未知字段；核心路由与核心OpenAPI逐项对应；旧兼容测试保持通过；新增与旧DTO显式区分。C00只建立协议/profile选择，不提前声称业务端点已经实现，未实现suite仍明确非零退出。

## 审查员工作台扩展（2026-09-28）

`GET /api/v1/cases/{case_id}/review-context` 仅商户人员可读，返回当前工单版本、允许动作、绑定政策原文、人工决定记录和当前授权对应的执行结果。无政策明确 UNAVAILABLE，不推断资格；跨商户与不存在同为404。

`POST /api/v1/cases/{case_id}/review-actions` 必须携带 If-Match。MANUAL_PROPOSAL 只接受本工单可读材料的完整来源及绑定政策引用，金额仍由Java重算，形成授权后单独审批。REJECT/REQUEST_INFO用于没有有效待审授权的工单，不伪造授权；输入修订与状态同事务更新，使旧Agent结果失效。有授权与无授权的REQUEST_INFO共用同一规则：写稳定`question_id`与问题正文，最多两轮，等待中不重复追问，已到期不再追问；客户回答必须带当前`question_id`，回答推进revision并创建新run绑定。已消费授权禁止全部输入修改。

队列原参数行为保留；新增 view=REVIEW/WAITING/PROCESSING/ATTENTION/CLOSED/ALL 和 query（工单/订单精确ID或问题描述，最长100字符）。新视图按商户隔离并使用游标分页，过滤变化时前端重置游标；绕开仅服务旧待审列表的缓存。退款结果来自已持久事件并排除标记过期的事件，不将批准视为到账。契约见 core OpenAPI；样例见 `contracts/core/fixtures/reviewer-context.json`（仓库根目录相对路径）。
## 审核调查分项输出（2026-09-28增量）

Agent Proposal 可选 `review_findings`（最多8条）：`kind` 为 FACT / INFERENCE / CONFLICT，`text` 为1–400字符，`observation_ids` 为1–8个不重复观察ID。每个ID必须出现在本方案 `evidence_refs` 中，CONFLICT至少引用两个不同观察；Python模型决策与Java接收均校验。事实支持性仍由既有Observation/Harness校验负责，ID匹配本身不证明语义正确。

FACT在审核界面标为“来源陈述 · Agent 整理”，不能覆盖原材料或人工核验记录。引用能匹配工单材料时展示原文；工具观察正文未进入审核视图时明确提示未提供，不以模型摘要补造正文。历史方案允许省略此字段；缺失不伪造分项。`missing_evidence`、过期和复核拒绝原因同时展示。该字段不产生授权或改变金额。

## 审核调查原始记录（2026-09-29增量）

公开 `GET /api/v1/cases/{case_id}/investigation` 仅商户工作人员可读。Case根据当前工单修订查绑定run，随后在事务外读取Agent；返回case_version/input_revision，前端丢弃不同工单或版本的迟到响应。无绑定是NOT_SCHEDULED；下游故障/历史数据缺失是UNAVAILABLE，不表示未进行调查。

内部 `GET /internal/v1/runs/{run_id}/review-sources?case_id=...&input_revision=...` 要求case-service身份、run:review scope、商户/客户claims，并与持久run的case/revision完全匹配。只读取agent_tool_call已保存结果，最多40条；单正文大于32768个UTF-8字节则省略并标记body_omitted，超出条数标记truncated。只输出来源/版本/hash/读取时间/结果/错误码和已保存模型提供方，不返回SDK对话、请求体、模型内部推理或服务凭证。不重新执行模型或工具，不修改原记录。

Case复核响应的run/case/revision后白名单投影；读连接/响应超时分别为3秒/5秒。页面分项仅在观察ID、来源、版本和hash全匹配时关联工具正文，展示当时保存的结果，不追写当前业务值。当前无历史修订切换器；只有当前绑定的可用记录可展开。

## 调查修订输入（2026-09-30增量）

`RunRequest.request.review_context`是可选的Case快照，包含该工单在input_revision及之前的materials和最多两轮questions。材料保留来源/版本/hash、原文、question_id及人工核验结论；问题保留question_id/field/prompt与提问修订。客户陈述不成为已确认事实，人工核验只表示人已记录的结论。该快照不改变四项EvidenceRef身份，不代替工具观察、政策资格或资金授权。

Agent拒绝未来修订或不在本次evidence_refs中的材料。非空快照纳入请求hash并持久化，恢复时使用原快照，修改同run输入返回409。旧请求未携带快照时保持原hash。模型P1保留此输入，不静默裁剪问答；必需输入超限明确转人工。核心OpenAPI定义界限，旧v1兼容模型保留原协议。

人工写入口（2026-10-02）：工作人员核验、材料追加、取消、人工方案、review-actions与reviews均要求当前负责人和原始读取的`If-Match`/`If-Collaboration-Match`。管理员必须先显式接管；角色本身不允许代批。客户材料/取消不要求协作凭证。订单复核在写事务外，随后工单锁内重查业务/协作/签名身份版本，变化即409，不记录过期方案或审批。
