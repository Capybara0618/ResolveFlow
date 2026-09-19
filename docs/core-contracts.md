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
| Case | GET /api/v1/review/cases | 商家内审核队列 |
| Case | POST /api/v1/cases/{case_id}/reviews | 审核当前授权；批准时重新校验 |
| Case | POST /api/v1/cases/{case_id}/reviewed-evidence | 人工核验追加，不改原材料 |
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

Java校验证据时按固定source_ref映射查询权威数据，而非信任Python文字。用户材料不是权威退款依据，ref不是可请求的任意URL。工具token绑定run/case/revision/merchant/customer/line/aud/scope，续签需Case确认有效，模型看不到token。

## 5. MQ与授权

command仅action=REFUND、target_service=commerce-service；由Case签名，Commerce验证producer、签名、hash、目标、归属和金额。授权消费与命令outbox同Case事务，授权消费后不允许更改/撤销。授权消费之前必须查证据/政策最新状态；消费后的已承诺命令不因队列延迟使授权过期而撤回。

结果payload含operation_id,line_id,state,amount_minor,provider_ref可空,reason_code,aggregate_version。Commerce签名结果，Case验证来源及签名；错误producer不能伪造成功。inbox、投影和本地timeline在同事务。未知状态不是失败；乱序/矛盾结果向Commerce查询，不凭MQ顺序更新。

## 6. C00验收

新Schema拒绝补发、负数/浮点、错target、伪造来源及未知字段；核心路由与核心OpenAPI逐项对应；旧兼容测试保持通过；新增与旧DTO显式区分。C00只建立协议/profile选择，不提前声称业务端点已经实现，未实现suite仍明确非零退出。
