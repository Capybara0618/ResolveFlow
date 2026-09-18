# 接口、事件与错误契约

此文和 contracts/*.schema.json 是实施契约。T02据此生成完整OpenAPI文件并加入双语言验证，不能先各自实现再猜接口。REST使用snake_case JSON，Java内名可camelCase；所有内部事件schema_version=1。

v1.1增加[HarnessManifest Schema](../contracts/harness-manifest.schema.json)，不改变既有Java执行命令。T35根据[Harness决策ABI](agent-harness.md)生成严格ModelDecision Schema/Pydantic和正反fixture；T37固化ContextPacket/session_event/ReplayPack的内部版本化类型。READ_OBSERVATION是本地可见证据读取，不增加对外REST或MCP工具。对外方案仍只使用agent-proposal.schema.json；模型不得指定运行时身份字段。

## 1. 公共约定

- 外部请求：Authorization: Bearer <JWT>，写操作必填Idempotency-Key，修改已有资源必填If-Match: <version>。
- 内部请求：服务JWT，aud限定目标服务，scope限定动作；traceparent按W3C透传。外部的X-User/X-Role/X-Merchant等头全部剥离。
- 身份和merchant_id从验证后的token取得；外部请求不能以body中的customer_id决定归属。
- POST持久化异步任务返回202，Location及resource_id；GET返回200，创建同步资源201。
- 同幂等键同payload返回原资源；换payload返回409 IDEMPOTENCY_CONFLICT；请求hash按RFC8785规范化JSON（或经跨语言fixture验证的等价固定序列化），不得直接对原始请求字节hash。
- 错误体：{code,message,retryable,trace_id,details}。400输入错误，401未认证，403无scope，404本主体下不存在，409冲突/状态/版本，422语义无效，429限流，503暂不可用。
- 列表采用created_at+id cursor稳定分页，limit默认20最多100，避免深offset。

hash固定规则：execution payload_hash仅覆盖{operation_id,case_id,authorization_id,input_revision,line_id,merchant_id,action,quantity,currency,amount_minor(仅退款),address_hash(仅补发),policy_version,target_service}的规范化JSON，不包含payload_hash自身、entitlement_id（预留后填入）、trace或发送时间。event签名用Ed25519对规范化信封（排除signature本身，保留signing_key_id）签名；密钥ID在目标服务信任列表，public key可随构建配置，私钥运行时挂载。T02必须用跨语言测试固定这两种输入和字节结果。

authorization_id与planned_operation_id在生成待批准授权时预分配，再计算载荷hash；批准消费时创建该ID的case_operation。金额上限为1,000,000,000分，version/revision不超过2^53-1，确保Java/Python/JavaScript规范化数字一致；禁止NaN/float金额。UUID不是认证凭证。

## 2. 外部API

| 方法与路由 | 请求要点 | 返回/权限 |
| --- | --- | --- |
| POST /api/v1/auth/login | username,password | 演示JWT；固定种子账号，密码hash |
| GET /api/v1/orders | cursor,limit | 当前消费者订单行 |
| GET /api/v1/orders/{order_id} | 无 | 仅本人订单；员工必须商家范围 |
| POST /api/v1/cases | line_id,description,requested_actions | 202 case_id,status,input_revision,version |
| GET /api/v1/cases/{case_id} | 无 | 当前状态/公开证据/方案/操作摘要 |
| POST /api/v1/cases/{case_id}/evidence | question_id可选,text,evidence_kind | 202 revision+1；只允许可接收材料状态 |
| POST /api/v1/cases/{case_id}/cancel | reason | 200；AUTHORIZED及之后不能直接取消 |
| GET /api/v1/cases/{case_id}/events | Last-Event-ID可选 | SSE，范围授权，持久sequence重放 |
| GET /api/v1/review/cases | status,cursor | REVIEWER商家内队列 |
| POST /api/v1/cases/{case_id}/reviews | authorization_id,authorization_version,decision,reason | APPROVE/REJECT/REQUEST_INFO；If-Match校验case |
| POST /api/v1/cases/{case_id}/manual-proposals | action,evidence_refs,policy_refs,reason | 创建新proposal及revision；不可直接改原载荷 |
| POST /api/v1/cases/{case_id}/reviewed-evidence | source_evidence_id,verification_result,reason | REVIEWER商家内人工核验；追加证据、revision+1，撤销未消费授权 |
| POST /api/v1/operations/{operation_id}/reconcile | reason | OPERATOR，幂等触发状态查询，非再次付款 |
| POST /api/v1/policies/import | bundle_json,source_markdown | POLICY_ADMIN，创建DRAFT |
| POST /api/v1/policies/{bundle_id}/publish | expected_hash | 发布不可变版本，校验区间 |
| POST /api/v1/policies/{bundle_id}/revoke | reason | 撤销，safety_epoch递增 |

SSE使用fetch流读取以携带Authorization；不把token放URL。每15秒心跳；断连后客户端携带Last-Event-ID续读。事件是通知，最终以GET工单快照为准。示例进度种类CASE_CREATED/AGENT_STARTED/QUESTION_REQUIRED/PROPOSAL_READY/APPROVAL_REQUIRED/EXECUTION_UPDATED/CASE_CLOSED。

## 3. Agent控制面

### case -> Python

POST /internal/v1/runs

```
{run_id,case_id,input_revision,context:{merchant_id,customer_id,order_id,line_id},
 request:{description,requested_actions,evidence_refs},
 policy_manifest:{bundle_ids,manifest_hash,safety_epoch},deadline_at,traceparent}
```

run_id由case生成、(case_id,input_revision)唯一；同key不同载荷409。模型看不到service token。Python API验证调用者case-dispatcher，PG持久成功才202 {run_id,status}。过期token由dispatcher重签后投递，不把token持久放outbox正文。

scope字段与内部JWT声明必须一致，冲突403；运行时从已认证任务上下文注入run/case/revision及schema_version到最终proposal，模型不能指定另一run身份。proposal_id也由运行时稳定分配。

GET /internal/v1/runs/{run_id} -> 状态、已发回调ID、版本、脱敏结果摘要，供case对账。

GET /internal/v1/runs/{run_id}/observations/{observation_id} -> 对应只读工具记录与source/hash，供Java校验证据，仅case-service可调。Java不能只相信Python返回的文字结论：按固定source_type/ref映射重新读取权威业务数据，校验归属、版本和引用内容；版本变化触发重新调查。对用户陈述仅校验case_evidence记录，不将其升级成权威仓库事实。tool source_ref禁止任意URL。

POST /internal/v1/runs/{run_id}/cancel -> 标记取消；正在进行的模型请求可能无法撤回计费，后续结果被丢弃。

### Python -> case

POST /internal/v1/cases/{case_id}/agent-callbacks

```
{callback_id,run_id,input_revision,kind:STARTED|QUESTION|PROPOSAL|FAILED,
 payload:{...},traceparent}
```

QUESTION={question_id,questions:[{field,prompt}],reason_codes}；PROPOSAL按JSON Schema；FAILED={reason_codes,retryable,last_observation_refs}；STARTED={started_at}。

唯一(callback_id)，相同id不同hash拒绝。重复返回200 {disposition:DUPLICATE}；旧revision/已接管返回200 {disposition:STALE}并记录，不再重试；当前合法返回200 {disposition:ACCEPTED,case_version}。网络/503重试；422进入callback失败记录并人工可见。

同一run的STARTED晚于PROPOSAL到达时不回退状态。QUESTION和PROPOSAL是互斥终局回调；run终局后不能再产生另一种终局。

## 4. 业务只读接口与凭证

| 接口 | 服务 | 返回核心数据 |
| --- | --- | --- |
| GET /internal/v1/order-lines/{line_id}/context | commerce | 订单、支付、行金额、version |
| GET /internal/v1/order-lines/{line_id}/entitlement | commerce | state,operation_id（必要时脱敏）,version |
| GET /internal/v1/order-lines/{line_id}/shipment | fulfillment | status,conclusion,events,source_version |
| GET /internal/v1/order-lines/{line_id}/packing | fulfillment | packing evidence,source_version |
| GET /internal/v1/cases/{case_id}/evidence | case | 当前材料引用与内容 |
| GET /internal/v1/cases/{case_id}/policy-manifest | case | bundle/version/hash/effective范围 |
| GET /internal/v1/policies/{bundle_id} | case | 已发布政策原文+规则+hash |

Agent工具凭证：case_id,run_id,input_revision,merchant_id,customer_id,line_id,aud,scopes,exp，5分钟有效。worker续签通过case端点POST /internal/v1/runs/{run_id}/tool-credential，case确认run仍有效且未被接管。商家/用户/行三重约束由每个资源服务验证；Agent不能自行扩大scope。provider密钥不对Agent可见。

## 5. 权益与操作接口

均仅允许case-orchestrator或指定target-service，不暴露外部网关。

| 接口 | 请求 | 语义 |
| --- | --- | --- |
| POST /internal/v1/entitlements/reserve | operation_id,line_id,action,payload_hash | commerce原子占行权益；REFUND同时占资金 |
| POST /internal/v1/entitlements/{operation_id}/start | target_service,payload_hash | RESERVED->IN_USE，目标启动前的独占CAS |
| POST /internal/v1/entitlements/{operation_id}/commit | result_ref,payload_hash | 已成功执行，IN_USE->CONSUMED |
| POST /internal/v1/entitlements/{operation_id}/release | terminal_failure_ref,payload_hash | 验证无执行/确定失败；释放占用 |
| GET /internal/v1/entitlements/{operation_id} | 无 | 权威状态查询 |
| GET /internal/v1/operations/{operation_id} | 无 | commerce/fulfillment各自目标操作 |
| POST /internal/v1/operations/{operation_id}/cancel-before-start | reason | 持久CANCELLED墓碑；已开始返回409 |

cancel-before-start即使目标operation不存在也必须插入同id的取消墓碑，防止迟到消息启动；目标inbox接收消息时在同事务检查墓碑。目标已在IN_USE但未发provider时，也只能由目标串行化取消与启动，不能case自行release。

## 6. MQ契约

三个普通持久topic：rf.case.v1、rf.commerce.v1、rf.fulfillment.v1。消费者组按服务用途固定：case-results-v1、commerce-refund-v1、fulfillment-reship-v1。broker重试最多5次后DLQ；精确退避由锁定客户端配置验证，业务对账不依赖broker延时消息。

所有消息信封按 ../contracts/event-envelope.schema.json；payload按 ../contracts/execution-command.schema.json（命令）或下列事件定义。key=operation_id，仅帮助定位，正确性不依赖顺序。

| event_type | 发布者/topic | 消费者 | payload |
| --- | --- | --- | --- |
| RefundRequested | case/rf.case.v1 | commerce | execution-command，action=REFUND |
| ReshipRequested | case/rf.case.v1 | fulfillment | execution-command，action=RESHIP |
| RefundSucceeded/RefundFailed/RefundUnknown | commerce/rf.commerce.v1 | case | operation_id,line_id,state,provider_ref,amount_minor,reason_code |
| ReshipSucceeded/ReshipFailed/ReshipUnknown | fulfillment/rf.fulfillment.v1 | case | operation_id,line_id,state,provider_ref,quantity,reason_code |
| EntitlementCommitted/EntitlementReleased | commerce/rf.commerce.v1 | case | operation_id,line_id,state,version |

UNKNOWN不是终局失败。结果事件的provider_ref在公开响应中脱敏。schema_version不支持或hash不一致：隔离记录并报警，不能无条件ACK丢弃；毒消息最终DLQ，需要操作台可追踪。

execution-command中的authorization_id只是关联ID，消费方不能仅凭它信任消息；验证case签名与固定payload_hash、目标aud，查询/启动对应权益。case事件签名排除broker属性，只覆盖规范化业务正文。消息中无用户Bearer token。

## 7. 契约变更与验证

T02生成contracts/openapi-{case,commerce,fulfillment,agent}.yaml，包含所有表内接口的required/enum/error和示例。schema文件对未知字段默认拒绝；同一版本只允许双方同意的向后兼容新增字段。跨语言fixture用相同JSON验证金额、时间、hash、enum；OpenAPI和Schema冲突必须先修订文档。
