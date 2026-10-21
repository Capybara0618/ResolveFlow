# 客服 Agent 上下文工程：企业产品与公开源码对照

2026-10-21。用户要求调研真实企业客服工程。本轮查阅 Intercom Fin、Cognigy、Rasa 官方资料、AWS Memory 开发文档及 Chatwoot 源码，区分公开行为、源码事实和本项目建议。没有运行这些产品，不把商业文档推断成私有prompt/压缩算法；不修改已冻结评测清单或生产逻辑。实际进度只看 tasks/todo.md 顶部。

## 1. 实际查到的做法

| 系统 | 可核实的工程行为 | 能借鉴什么 |
| --- | --- | --- |
| Intercom Fin | [API](https://developers.intercom.com/docs/guides/fin-agent-api)分别接收当前消息、用户信息、初始化历史、会话属性；start历史最多10条、会话属性最多20项。Helpdesk转人工可附摘要及额外内部背景，Fin for Platforms的context传递行为不同 | 历史与业务属性分开，人工交接有独立上下文；这些是接口限制，不能推断内部始终只看10条或使用何种摘要模型 |
| Cognigy | [官方记忆配置](https://support.cognigy.com/hc/en-us/articles/17346572088348-Give-your-AI-Agent-access-to-memory)区分当前会话短期信息和跨会话Contact Profile；[工程示例](https://www.cognigy.com/product-updates/an-ultimate-guide-to-ai-agent-memory)展示按时间定位新增/更新/删除记忆以及选择注入资料 | 区分会话状态与长期画像，记忆有更新生命周期；不把每次物流状态存成永久偏好 |
| Rasa CALM | [Dialogue Understanding](https://learning.rasa.com/rasa-pro/dialogue-understanding/)结合对话状态、flows/slots、当前活跃flow/slot生成命令；[Conversation Repair](https://learning.rasa.com/rasa-pro/deviations-from-happypath/)明确处理纠正、打断、撤回、澄清与人工接续 | 除文本窗口外，保留当前任务及已收集信息，显式建模对话变化；不用迁移Rasa才能采用这些思想 |
| Chatwoot Captain | 固定develop revision `39314c979aa4192bc1c6bced9cbbebcabde2fbb1`，见下文代码事实 | 会话角色/事件边界、结构化业务状态、迟到结果抑制和可追踪上下文，不是单纯截断聊天 |
| AWS AgentCore | [开发文档](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness-memory.html)区分session原始事件与可提取的长期记忆，按actor/session限定；提供sliding_window和summarization两类截断策略 | 摘要是可选策略，不是成熟度门槛；记忆范围与检索配置需要独立管理，不需要本项目新增云依赖 |

### Chatwoot 定点源码核验

读取以下6文件，保存固定revision和SHA-256到 [来源清单](../reports/customer-context-engineering-review-v1/sources.json)，原始源码只缓存于忽略tmp目录。另3条猜测路径404保留记录，没有据其推断能力。

- [MessageHistoryBuilderService](https://github.com/chatwoot/chatwoot/blob/39314c979aa4192bc1c6bced9cbbebcabde2fbb1/enterprise/app/services/captain/conversation/message_history_builder_service.rb)：过滤private/forwarded消息、按时间/id排序、映射角色，并把resolved活动变为会话边界。此模块没有显示摘要步骤，但不能据此断言SDK/整个产品完全没有压缩。
- [AgentRunnerService](https://github.com/chatwoot/chatwoot/blob/39314c979aa4192bc1c6bced9cbbebcabde2fbb1/enterprise/app/services/captain/assistant/agent_runner_service.rb)：当前最后user消息与先前历史分开，context含session、history及state。
- [RunnerStateHelper](https://github.com/chatwoot/chatwoot/blob/39314c979aa4192bc1c6bced9cbbebcabde2fbb1/enterprise/app/services/captain/assistant/runner_state_helper.rb)：选择会话/联系人/渠道及验证相关字段组成state，不仅传聊天文本。
- [ResponseBuilderJob](https://github.com/chatwoot/chatwoot/blob/39314c979aa4192bc1c6bced9cbbebcabde2fbb1/enterprise/app/jobs/captain/conversation/response_builder_job.rb)：生成前后及发布事务内检查更新的客户消息，避免旧回答抢在新诉求后发布。
- [SessionCaptureService](https://github.com/chatwoot/chatwoot/blob/39314c979aa4192bc1c6bced9cbbebcabde2fbb1/enterprise/app/services/captain/assistant/session_capture_service.rb)：保存本轮输入/工具/回答及引用等审查信息；源码注明当前失败run尚不纳入该会话捕获，不应照搬为完整失败审计。
- RunnerCallbacksHelper：工具、handoff及trace回调。它证明有观测接口，不证明最终业务正确率。

以上属于仓库enterprise目录的公开代码，不表示全部功能无商业许可限制；本轮没有安装或部署。

## 2. 对我们项目的判断

从上述公开做法归纳，适合本项目的上下文可以由以下几类数据组装；这是综合设计建议，不是某一家产品私有架构的复刻。

1. 原始会话事件：保留消息和来源，供展示、审查和精确读回。
2. 当前会话状态：订单行、接收方、核查状态和目前处理阶段，由后端提供。
3. 当前有效陈述与已做排查：如客户是否收到、是否问过家人/代收点、当前诉求；保留原句位置及纠正关系。
4. 任务与待确认问题：哪些诉求活跃、暂停、撤回、待客户补充或需商家核查。
5. 本轮新鲜业务事实与相关知识：业务来源带版本/读取时间，政策保留适用版本、条件及例外。
6. 预算内近期原文、必要旧原文及可选摘要；最终请求和裁剪决定可追溯。

当前我们已有原文持久化、可信消息/核查状态、任务提示、预算裁剪/首尾索引/读回、来源去重/版本、同输入发布门禁和持久恢复。主要不足是当前有效陈述尚依赖模型重读历史，任务缺显式暂停/恢复结构，原文召回主要按时间或模型指定位置，不是基于事项的关联选择。用户纠正虽然写进提示并做过脚本测试，还不能等同明确的事实更新机制。

## 3. 优先建议：先补状态，再按需要加摘要

### 第一项：带来源的当前有效陈述

建议按会话/订单行记录小规模字段：客户自述收货情况、已排查事项、当前诉求/明确不想做的动作、材料和待确认问题。系统物流状态保留为工具事实，不能与客户陈述合并成一个真假值。

例：M12“家人可能代收”→ M27“纠正，家人没代收”。保留两条原文，当前有效客户陈述指向M27，M12标记被替代；不覆盖旧消息，也不把“客户说没收到”变成“系统确认丢失”。冲突尚未解决时并列展示，不能简单对所有字段实行最后一句覆盖。

实现候选是同次模型动作附小型、受schema约束的陈述更新，带message_id与精确原句；程序核验原句和scope，业务字段只由Java/工具更新。该机制不需要额外提取模型，但语义抽取仍需评测，不以schema通过冒充理解正确。

### 第二项：显式对话变化

分清“改事实”“撤回诉求”“暂时插问”“永久切换诉求”。例如正在核查签收时问退款入口，可能只是插问，不应清掉核查任务；明确找到包裹时则结束相应争议诉求。借鉴Rasa的repair模式，使用轻量任务/变更记录即可，不引入新框架或完整flow平台。

### 第三项：相关旧信息自动补入

有了来源化状态，先固定带入与当前订单事项相关的有效陈述、纠正及未完成任务，减少模型自己猜应该读哪页历史。保留read_context精确读回作为补充。初期使用字段/事项关联，不急着给全部聊天做向量库；将来数据增长再比较语义召回。

### 第四项：摘要按触发条件引入

长期背景超过预算时才考虑增量摘要，记录覆盖消息范围/版本及原文指针；摘要是派生文本，不替代业务事实/政策。摘要时的模型调用、延迟和错误都计量，不每轮另起一次模型调用。转商家的简短交接摘要与提供给LLM的历史摘要是两种不同产物；仍遵守客户确认共享范围。

这些是调研后的建议，当前未实现，需用户确认下一工作包再更改已冻结评测版本。当前“可开始评测”仍指上一批已实现方案，不自动变成上述建议均已完成。

## 4. 如何判断改善

优先测长距离纠正是否生效、已做排查重复询问率、插问后能否继续原任务、旧事实误用、交接信息完整性以及整会话任务完成率；再比较实际请求token和延迟。前后使用相同事实/政策、不同表述及留出的开发可见变体，原结果保留。不能只凭token减少宣布记忆更好。

本轮仅研究文档/来源记录，无新模型请求、运行服务、权重下载或数据库写入，也未修改原29文件冻结输入及生产代码。
