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

| 所属 | 方法与路由 | 行为 |
| --- | --- | --- |
| Case | POST /api/v1/auth/login | 合成账号登录 |
| Case | GET /api/v1/orders | 当前主体订单视图；内部请求Commerce |
| Case | GET /api/v1/orders/{order_id} | 本人/商家授权订单 |
| Case | POST /api/v1/cases | line_id/description/requested_actions=[REFUND] |
| Case | GET /api/v1/cases/{case_id} | 状态与公开证据 |
| Case | POST /api/v1/cases/{case_id}/evidence | 追加材料并增revision，消费后409 |
| Case | POST /api/v1/cases/{case_id}/cancel | 仅授权消费前可取消 |
| Case | GET /api/v1/cases/{case_id}/events | SSE，Last-Event-ID，鉴权不放URL |
| Case | GET /api/v1/review/cases | 商家内审核队列：仅 PENDING_REVIEW，按 updated_at 倒序，keyset 游标分页；客户角色 403，坏游标/坏 limit 400 |
| Case | POST /api/v1/cases/{case_id}/reviews | 人工决定当前授权；`If-Match`为工单版本、body带授权自己的版本，任一过期409；批准前重新校验；客户角色403 |
| Case | POST /api/v1/cases/{case_id}/reviewed-evidence | 人工核验追加，不改原材料：新记录引用被核验记录（`reviewed_evidence_id`）并带 `verification_result`，两条都在工单视图的 `EvidenceView` 里可读；客户角色 403，跨工单引用 422 |
| Case | POST /api/v1/cases/{case_id}/manual-proposals | 新revision/方案，非直接付款 |
| Case | POST /api/v1/operations/{operation_id}/reconcile | OPERATOR请求查状态，不再次付款 |
| Agent | POST /internal/v1/runs | PG落库后202，同case/revision唯一 |
| Agent | GET /internal/v1/runs/{run_id} | 受权运行摘要 |
| Agent | GET /internal/v1/runs/{run_id}/observations/{observation_id} | 仅Case校验证据 |
| Agent | POST /internal/v1/runs/{run_id}/cancel | 停后续调查，不承诺撤回已发LLM计费 |
| Agent | GET /health | 健康 |
| Case | POST /internal/v1/cases/{case_id}/agent-callbacks | callback_id幂等，ACCEPTED/DUPLICATE/STALE |
| Case | POST /internal/v1/runs/{run_id}/tool-credential | 当前revision受限工具凭证 |
| Commerce | GET /internal/v1/order-lines/{line_id}/context | 权威订单/支付/行金额 |
| Commerce | GET /internal/v1/order-lines | 按主体列出订单行，供Case构建公共订单视图 |
| Commerce | GET /internal/v1/order-lines/{line_id}/shipment | 明确标synthetic的版本化物流数据 |
| Commerce | GET /internal/v1/order-lines/{line_id}/refund-status | 已退/预留/当前退款状态 |
| Commerce | GET /internal/v1/operations/{operation_id} | 权威退款状态，供Case对账 |
| Case | GET /internal/v1/cases/{case_id}/evidence | 当前case材料及来源 |
| Case | GET /internal/v1/cases/{case_id}/policy-manifest | 绑定bundle/version/hash |
| Case | GET /internal/v1/policies/{bundle_id} | 授权政策正文/规则 |

核心不开放旧entitlements、packing、cancel-before-start或补发端点。政策由受控脚本导入校验，不做管理HTTP全集。版本按订单行**支付时间**选择：取生效起点最晚且未被显式结束的版本，因此无结束日期的版本会被后继版本取代，而历史订单不会被新政策套用；选中的版本与hash在开单事务中钉在工单上，之后导入新版本不改变已开工单。Order API的公共归属仍为Case，以复用现有协议模式；不暗改网关到数据库。

政策路由同时发布每条规则的`chunk_id`与`content_hash`，因为方案引用的`PolicyRef`要求这两个成员：只有这条路由发布规则，run能引用的hash只能从这里抄。两者都由**已存正文派生**（chunk按规则在bundle中的位置编号，hash取bundle_id/chunk_id/title/text的规范JSON），不存库、不读导入文件，与bundle自身manifest hash同一构造；跨语言固定值在`contracts/fixtures`中冻结，Java与Python各自重算同一digest，否则引用核对不可验证。

## 4. 运行与回调

run请求沿用run/case/input_revision、受控context(merchant/customer/order/line)、request、policy_manifest、deadline_at、traceparent；body主体必须与service JWT及Case绑定一致。

回调kind为STARTED/QUESTION/PROPOSAL/FAILED；QUESTION与PROPOSAL互斥终局。QUESTION含稳定question_id、最多3个问题及原因；PROPOSAL使用核心方案Schema；FAILED含原因、已知观察ref。旧revision/人工接管后返回STALE且不重试；相同callback换载荷拒绝；STARTED迟到不回退状态。

PROPOSAL的接受分两类：结构或绑定错误（`schema_version`、`case_id`/`input_revision`与工单不一致、未知`case_type`/`recommended_action`、非REFUND带金额、`source_ref`是URL等）是422——这条消息不是方案；**可检内容**则是"已核对并被拒"的持久事实，存`case_proposal`为`REJECTED`并写`refusal_reason`。可检部分全用本服务自己的记录：引用必须落在工单钉住的版本上（`bundle_id`在钉住集合内、`version`等于库存版本、`rule_id`+`chunk_id`存在且重算`content_hash`相符——引用新版本、引用已改正文、引用不存在规则都算拒绝），REFUND必须至少一条政策引用，金额从Commerce行上下文重算（paid−refunded−reserved，且必须仍属该工单的商家与客户），`suggested_amount_minor`只保留作对照；重算为0或低于建议值即拒绝。`VALIDATED`只说明引用与金额通过了本服务的核对，不等于批准，也不代表run结论正确；两种结果都使工单进入`PENDING_REVIEW`（人工接管后同一revision再投递即STALE）。

人工核验（`reviewed-evidence`）与客户材料一样是**追加**：新记录用`reviewed_evidence_id`引用被核验的那一条、用`verification_result`记下CONFIRMED/REFUTED/INCONCLUSIVE，被核验记录的正文与hash一律不动（表内没有update/delete语句，引用是`(case_id, evidence_id)`外键，跨工单引用在库层面不可能）。核验对象必须是本工单的**材料**而不是别人核验的结论（核验的核验会让"核的是什么"退化成链条），客户角色不能记录核验（403）。`EvidenceView`是工单视图里材料的样子：引用形状+正文+谁在哪个revision追加的；核验结论因此是结构化事实而不是要人去解析的句子，而`EvidenceRef`（方案引用与内部复读用）仍然**不含正文**——引用不能变成夹带未核验文本的通道。核验结论本身不撤销授权：**撤销它的是输入revision被推进**（见下一段），CONFIRMED与REFUTED在这件事上效果相同——把失效归因于结论会让读者以为"确认过的材料就不会让批准失效"。`revoked_authorization_id`缺失的含义是"本来就没有活授权可撤"，不是"没人检查过"。

**任何新输入都让该工单的活授权不再算数**（C03.3c）：授权固定在它创建时的`input_revision`上、`payload_hash`也是按那份输入算的，所以revision一旦前进，这笔批准描述的就是工单已经没有的输入。三条写新输入的路由——追加材料、人工核验、人工方案——因此都在**写入的同一个事务里**把活授权置`REVOKED`（不是`EXPIRED`：有人做了动作撤掉它），`decision_reason`写明是哪次动作与推进到哪个revision（从哪个revision来不写进句子，授权行自己的`input_revision`列已经说了），响应里的`revoked_authorization_id`点名被撤的那一笔。`AUTHORIZED`的工单随之回到`PENDING_REVIEW`：状态不能比它命名的事实活得更久，否则工单会声称"可以执行"却没有任何活授权。留下的空窗由下一次方案（run的或人的）填补，撤销本身不会替它造一笔新授权。这不是批准路径的兜底检查——把失效留到有人点"批准"时才发生，工单视图会在一段时间里显示一笔对不上输入的批准，而轨迹里没有任何东西说明它为什么还在。

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
