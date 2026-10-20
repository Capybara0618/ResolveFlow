# 客服 Agent / RAG 接入 v1

2026-10-20。承接[客服会话契约](customer-support-contract-v1.md)、[首场景](customer-agent-scenario-v1.md)及用户“开始”授权。本批接真实自动问答和转交建议，不改原退款动作或重新搭框架。进度仅[todo顶部](../tasks/todo.md)。

## 执行方式

客户发送ASSISTANT消息时，在Case短事务中保存消息和独立support_agent_turn；记录run_id、conversation_id、input_version。正式派发开关开启时，调度器将待办交给Python咨询接口，网络请求不放数据库事务。客户可继续发送/纠正/换商品，旧turn的发布必须比较会话版本与派发fence，过时结果标STALE，不追加成最新回复。历史消息不会在升级时补造Agent任务。

Python咨询运行独立于退款agent_run，不填虚假case_id。AgentScope Agent驱动唯一推理/工具循环，复用AgentScopeModelAdapter、ModelClient/LiveModelClient、BudgetGuard、固定token计数与PolicyIndex；咨询ABI独立定义READ_TOOL/SEARCH_POLICY/ANSWER，不能把聊天回答包装成退款PROPOSE。每个run重新建立SDK对象，不共享跨店记忆。

工具通过Case的咨询只读facade取得当前订单、物流、适用政策及本会话历史；工具身份绑定run/conversation/input_version/merchant/customer/line，仅含support:read，不含退款/审批/政策写或原Case工具权限。现有退款调查MCP保留；咨询facade是SDK的只读HTTP工具，不宣称新增MCP实现。

## 上下文与检索

Case从真实订单支付时间选择并固化商家政策manifest，保留订单商品快照、最近客户/助手/商家消息及更早历史索引。客户陈述、工具事实、政策原文分别标记来源；不做LLM历史摘要，较早材料按需读回。输入超限明确失败，不能删掉当前问题/关键来源后假装正常。

模型决定是否读取订单/物流或检索政策，不预先串好全量路径。政策检索复用现有PolicyIndex的dense生产路径，召回前限定商家、bundle、manifest及固定generation；不回退到BM25或外部原文评测库。订单物流问询可以不搜索政策；索引不可用作为明确观察返回，用户仍可选择商家核查。

回答引用只能来自当前run已读事实或政策，展示来源/版本及相关原文。转交建议包含可编辑摘要，不自动创建人工核查单或退款Case。客户仍需预览共享范围并确认；Agent不得冒充商家已经核实或退款已经成功。

## 预算与持久化

沿用默认12次模型/16次外部读/8次本地读、单模型输出1024及120秒活动窗口，所有模型/工具调用先记账；SDK重试关闭，不设额外模型总结循环。保存实际请求、响应、用量、模式和显式工具行动，不存隐式思维链。

Python PG追加咨询run/call记录。run输入/manifest/deadline固定；领取带租约与fence，保存结果重新验证fence。已落库完整调用可以确定性重放，已完成run重复派发直接复用结果；未落库模型响应标UNKNOWN，保留预算，不承诺零重复计费。第一版遇到未完成调用不静默重置预算重付，明确失败并允许客户重新发送形成新turn。旧run不会因配置或代码变化自动换manifest。

## 交付顺序与验证

1. 咨询协议、AgentScope循环/预算/引用及只读检索适配，先脚本模型与独立变体验证。
2. PG持久调用账、内部咨询API与Case短事务派发/身份/旧版本发布，测试恢复/fence及跨店归属。
3. 网页助手回复、引用出处、运行状态及采用转交摘要，保留人工接续；mock跨进程接线与真实本地dense检索分开报告。

每个已验证独立小步精确commit并正常push；不改旧冻结Gold/简历/量化报告，不清库删卷或重放已有退款任务。开发验证使用明确mock及本地检索，真实模型质量实验和费用另行确认；工程通过不当作Agent完成率提升。
