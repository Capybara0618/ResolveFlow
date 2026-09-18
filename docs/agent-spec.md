# Agent业务与执行规格

## 1. 职责与框架

Python 3.12 + FastAPI + LangGraph StateGraph + PostgreSQL checkpointer；Pydantic用于契约。单Agent按观察选择下一项行动，固定外层控制资源预算、权限和终止。业务执行由Java完成。

核心实现依据为[Agent Runtime Harness](agent-harness.md)：模型负责动态决策，Harness负责上下文、工具调度、状态、预算和输出验证。配套[上下文工程](context-engineering.md)和[轨迹回放](trajectory-replay.md)是必做规格，不新增服务或第二套Agent框架。

模型接入通过ModelClient接口：支持结构化tool calling、记录用量/请求ID、超时、可取消。提供 deterministic/mock 和 live 两模式。具体模型ID、供应商、价格表在实验manifest记录；不绑定Astra，不把开发助手的模型选择带入项目产品。

## 2. 输入与状态

控制面输入：run_id、case_id、input_revision、merchant_id/customer_id/order_id/line_id的服务端绑定、用户诉求、允许动作、当前证据引用、固定policy_manifest、绝对deadline、traceparent。身份上下文来自case签发的凭证，模型无修改权。

GraphState至少保存：case/run/revision、message_refs、facts、missing_evidence、observation_refs、policy_refs、candidate_actions、questions、step_count、model_call_count、external_call_count、local_read_count、consumed_tokens、pending_reservations、remaining_budget、errors、next_action、final_proposal、manifest_id、index_generation、context_id、last_event_sequence、checkpoint_id。原始长文本在SessionStore，不反复复制进checkpoint；manifest_id替代不明确的config_hash作为运行配置身份。

agent_run状态固定QUEUED/RUNNING/CALLBACK_PENDING/WAITING_INPUT/COMPLETED/FAILED/CANCELLED/STALE。lease失效并不直接将任务标FAILED；可恢复run回QUEUED，维持原run_id及checkpoint。WAITING_INPUT run收到新revision后标STALE，其历史问题仍保留，新run继续业务。COMPLETED仅表示有效方案回调已由Java确认接收，不表示退款完成；QUESTION确认接收后进入WAITING_INPUT。

facts必须携带来源和版本。用户陈述与仓库/承运商事实分开标记；多次模型复述不增加证据可信度。对外展示短的理由摘要及工具轨迹，不要求存储或展示模型隐式思维链。

## 3. 循环与动作

固定外层节点：load -> build_context -> model_decide -> validate_action -> dispatch/read/ask/propose -> persist_observation -> next/end。PROPOSE经过ProposalVerifier后才写回调；错误Observation返回模型，超权/超预算等硬停止由Harness处理。状态图固定不代表业务工具路径固定。

模型每步可选择：

- READ_TOOL：调用当前白名单只读工具。
- SEARCH_POLICY：检索当前manifest允许的政策。
- READ_OBSERVATION：按需读取已持久化且获准可见的证据片段，非新增MCP/Java工具。
- ASK_CUSTOMER：提出最多3个聚合问题，写回调后结束本run为WAITING_INPUT。
- PROPOSE：生成结构化方案，进入确定性证据/Schema检查。
- ESCALATE：证据矛盾、范围外、依赖持续故障或预算不足时转人工。

不用模型控制消息确认、数据库事务、工单状态或授权。没有业务需要时不强制多工具；工具调用路径长不代表Agent质量高。基线和动态Agent使用相同业务工具与安全执行层。

## 4. 工具目录

| 工具 | 模型参数 | 返回 | 限制 |
| --- | --- | --- | --- |
| get_order_context | 空对象 | 当前订单行、支付状态、已确认动作 | scope注入line_id，不允许枚举订单 |
| get_shipment_trace | cursor可选、limit<=20 | 物流状态/轨迹/结论/版本 | 当前行；最大分页2次 |
| get_packing_manifest | 空对象 | SKU/数量、核验标记、版本 | 当前行 |
| get_entitlement_status | 空对象 | 是否已有补救/占用 | 只读且不返回无关支付信息 |
| get_case_evidence | kind可选 | 当前工单材料与来源 | 文本长度及总量上限 |
| get_policy_manifest | 空对象 | case给出的可用bundle/hash | 绑定当前决策版本 |

search_policy(query,top_k<=5)为本地检索动作。MCP适配进程只注册上述6个read tools，实际通过MCP tools/list与tools/call交互，不能只给普通HTTP函数起名叫MCP。

每条返回封装observation_id、source_type、source_ref、source_version、observed_at、content_hash、data。工具读取错误包括NOT_FOUND、FORBIDDEN、TIMEOUT、UNAVAILABLE；不存在数据不等价于否定事实。未经授权的失败立即终止，不换ID重试。

## 5. 输出与确定性验证

正式Schema见 ../contracts/agent-proposal.schema.json。输出包括proposal_id、run_id、case_id、input_revision、case_type、recommended_action、evidence_refs、policy_refs、reason_codes、summary、missing_evidence。可选suggested_amount仅作展示，执行金额Java重算并要求与方案一致，不允许自动静默调整金额。

模型不输出有授权意义的confidence/requires_approval；Python可以输出风险提示reason_codes，Java返回route=AUTO/REVIEW/NEED_INFO/BLOCK。引用必须在该run可见的observation/policy集合内，版本/hash吻合；无引用不能据此退款。Schema允许一次修复，第二次失败转人工。

## 6. 运行预算与退避

配置默认：每run最多12次模型调用（含修复及网络重试）、16次外部工具/检索attempt、8次本地证据读取、累计输入40,000 tokens、累计输出4,000 tokens、活动执行120秒；单模型调用30秒。单步输入最多8192、输出最多1024 tokens，同时服从provider容量与剩余预算。一个case最多2轮向用户追问，第三轮仍不足转人工。人工等待时间不计活动执行延迟。

请求前持久预占、返回后结算；UNKNOWN保留保守预占，恢复不清零。相同动作连续无进展、预算耗尽、必保留上下文超限有明确停止原因，详见Harness与上下文规格。模型调用次数与业务决策步数分别记录，不用一次修复伪装成零成本。

工具返回给模型的单条excerpt最多8KiB（UTF-8字节），超出用确定性结构化提取+分页；已接收原文保存于SessionStore，模型不得靠摘要覆盖权威字段。底层单次工具响应最多256KiB，超限返回TOOL_RESULT_TOO_LARGE并要求后端分页，不无限下载或静默丢弃。独立只读工具可并行最多3个；写工具数量为0。

两种deadline分开：控制面deadline_at由Java创建，默认建单后10分钟，限制排队/依赖等待及调查；worker首次开始调查时持久化active_deadline_at=min(deadline_at,首次开始时间+120秒)。同run恢复不重置该时间，故障停机与重试消耗此窗口。120秒是调查窗口而非累计CPU时间；方案已落库后的可靠回调重试不受模型调查预算限制，但仍校验revision。人工等待在Java，补证建立新revision/new run及新的deadline。

工具瞬时错误最多重试2次（含首次总3次，抖动退避），受全局deadline限制；模型网络错误最多额外重试1次。不得Python SDK、LangGraph节点和网关三层同时默认重试。所有attempt均计入预算。

## 7. 持久调度与恢复

API只接收并持久化任务。worker以PG SKIP LOCKED领取、30秒租约、10秒心跳，fence递增。每次保存运行状态/回调都校验fence；单run使用数据库会话级advisory lock守护Graph执行，新worker只有拿到同一锁才继续。数据库连接丢失立即中止当前run的后续动作。

checkpointer写入也必须受fence约束，不能只保护agent_run表。实现FencedCheckpointer适配层：每次checkpoint事务先SELECT agent_run FOR UPDATE验证fence、lease_owner和未取消状态，再在同一事务写checkpoint；回调/观测完成提交使用相同模式。若锁定版本的官方PG checkpointer不能复用该事务，T00提供最小适配验证再确定接入方法，不可用“先查后另起事务写”代替。领取新fence也锁相同run行，失效worker的外部LLM返回只能记隔离日志，不能推进图或发有效回调。

checkpointer与业务观测日志并非跨表天然原子：工具结果先以稳定call_id持久化再进入图状态，恢复通过日志查找已完成结果。LLM结果落库后可复用；provider已返回但本地未存储的窗口可能重复调用，记录UNKNOWN与重复成本，绝不宣称全故障窗口零重复调用。

consumer补充材料时，case增input_revision并创建新run，旧run停止/标STALE。新run可复制前轮已持久化的用户问答引用；物流、权益、政策必须重新取有效版本，不跨revision盲用旧观察。该机制是“业务继续”；同revision worker故障用checkpointer恢复是“执行恢复”。两者分别测试。

审批等待完全在Java，不让Agent进程一直挂起；Python持久化方案及回调后释放worker，回调被接受才标COMPLETED。LangGraph中断仅用于确有图内等待需要的节点，重入前副作用必须幂等。官方说明见[中断文档](https://docs.langchain.com/oss/python/langgraph/interrupts)和[持久化文档](https://docs.langchain.com/oss/python/langgraph/persistence)。

## 8. 可信边界与人工接管

用户文本、政策正文、工具返回文本都作为数据隔离；不能赋予其系统指令地位。控制面绑定context，工具后端再次验证授权，最终写入口验证service identity和已消费授权。只靠Prompt不能防越权。

人工接管递增input_revision并撤销未消费授权。迟到回调返回STALE，不能重新排队或批准。Agent失败保留run日志、已知证据和原因；Java人工处理入口仍可完成流程。

## 9. 专项验收

- 同样问题因物流/仓库证据不同而走不同工具路径；提供3个可复现对照case。
- 缺证追问、更新输入后续接、worker故障恢复、旧run回调均有测试。
- 提示注入不能创造退款工具/授权/跨用户数据读取。
- live实验度量动作质量、引用质量、成本与端到端时延；mock成功不能当作模型效果。
- H-AUT/H-CTX/H-RPL专项及GH门槛必须通过；24组自治配对样本纳入240案例集，固定序列不是Gold。
