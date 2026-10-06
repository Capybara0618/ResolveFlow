# 领域Agent Harness · v1.3 AgentScope目标

2026-10-06接续[建议与停止来源改进](agent-decision-handoff.md)：引用反馈定位finding字段和短编号、系统字段与客户补证责任分开、具体REQUEST_INFO在动作/最终校验同检查，SDK停止不再记作模型ESCALATE。有效模型转交的FAILED回调保留其原因码；不将COMPLETED当转交原因。结果见[集中报告](../reports/decision-handoff/README.md)，真实模型质量仍待对照，旧版本回放保持。

当前纠错协议见[Harness纠错闭环](harness-correction-loop.md)：结构/来源/有限关键事实检查、共享一次修正、临时读故障有界重试与受fence保护的恢复。AgentScope驱动唯一循环，Harness给短反馈和硬门禁；最终建议仍需Java与商家审批。真实模型质量与任意自然语言幻觉不由这些有限检查保证。

范围见[core-scope](core-scope.md)，框架边界见[AgentScope迁移规格](agentscope-migration.md)。这里实现售后调查运行层，不研发通用图引擎或Agent平台。AgentScope SDK已接入唯一推理—行动循环；模型负责下一业务行动，领域Harness负责硬约束，PG RunStore/恢复适配的目标是受fence保护的运行快照，Java负责权威事实与退款授权。接入不等于持久恢复完成，实际进度见任务账本。

## 1. 核心模块

| 模块 | 职责 | 必须证明 |
| --- | --- | --- |
| HarnessRunner/AgentScope适配 | 装配SDK唯一循环，接入动作守卫和领域终止 | Observation后动作来自模型，不是case_type固定路线；无双重Agent循环 |
| ContextBuilder | 分层输入、关键事实/冲突保留、原文引用 | 保存实际请求，超限明确拒绝 |
| ToolExecutor | 白名单MCP/本地检索/证据读取、scope、attempt | 模型不能改主体/URL，无写工具 |
| BudgetGuard | 持久预占/结算、deadline、防无进展 | 恢复不清零、有限终止 |
| ProposalVerifier | Schema、可见引用、hash/版本、缺证检查 | Python通过不等于Java批准 |
| RunStore/ModelClient | 调用/上下文记录、checkpoint/fence、mock/live | 复用已落库结果，UNKNOWN成本可见 |

这些是同一Python服务内的职责，可用小模块/Protocol，不要求每个名词独立类、表或插件系统。SessionStore可由run/model_call/tool_observation/context_snapshot组合实现；EvidenceLedger只是结构化事实视图，不强制额外服务或数据库表。SDK内置预算/权限/会话能力只作适配基础，不能代替项目调用前预占、资源侧鉴权和故障验收。

## 2. 单步顺序

1. 检查run、fence、取消、deadline及manifest兼容。
2. 构造ContextPacket，保存精确provider输入（不含凭证）及hash。
3. 同事务预占预算并建立稳定model_call_id，网络调用在事务外。
4. 返回后带fence保存响应、usage；未落库外部结果标UNKNOWN。
5. 校验模型动作，再保存工具请求；执行后先保存Observation，再推进checkpoint。
6. PROPOSE通过验证后持久最终方案与callback_outbox；其他路径将Observation交回模型。

网络期间不持有长业务事务。锁丢失后停止后续动作；旧worker结果不能推进运行快照或有效回调。回调投递不是“模型又决定了一次”。终止后禁止SDK自动总结/继续工具；模型重试、格式修复、压缩等若发生调用，均须经过同一预占与记录边界。框架默认额外调用应关闭或验证已被拦截。

## 3. 动作与运行包

动作字段和工具以[Agent规格](agent-spec.md)、C00核心Schema为准。模型不提供run/case/revision、credentials或authorization；PROPOSE候选用recommended_action，运行时补schema_version=2与ID。

沿用[HarnessManifest Schema](../contracts/harness-manifest.schema.json)固定code/运行编排/state、prompt_hash、context策略、tool schema hash、verifier、模型/参数、token计数、预算、政策和index generation。为兼容v1协议保留`graph_version`字段名，AgentScope目标值为`agentscope@<精确版本>+resolveflow@<适配版本>`，不表示仍运行LangGraph；`state_schema_version`区分新快照格式，代码/锁文件可追溯。manifest_id是排除自身后的canonical SHA-256。原Prompt按hash保留，参数只记录实际发送值，不存密钥。不能直接增删冻结Schema字段。

同run恢复用原manifest，未支持版本返回FAILED/MIGRATION_REQUIRED并转人工；不实现自动迁移或滚动版本共存调度。新revision可以新manifest。模型别名漂移必须记录限制，不假定可重现供应商内部权重。

新run累计token消费不设上限，记录usage；显式旧run预算恢复仍检查累计限制。单步输入窗口和输出长度检查保留，provider包装计入输入估计，timeout不超活动窗口。未知token标为估计，不当实际账单。见[用量规则](model-usage-policy.md)。

输出验收：新run每次以单步输出长度1024预占并传给ModelClient，不随累计消费收缩；显式旧预算使用`min(单步长度, 累计剩余输出)`。已知usage结算未用部分，未知/估算usage不得把记录退为0；供应商超出请求长度仍真实记账并在工具/终局动作前停止。持久恢复保存null累计限制及原计数；同时验证旧预算耗尽不发新请求、超额响应不执行工具、UNKNOWN不重复结算。

## 4. 上下文、回放和停止

[ContextBuilder](context-engineering.md)核心保留精确结构化事实+有界历史+按需读回。不做LLM摘要器、长期记忆或自动Prompt进化。

[strict回放](trajectory-replay.md)仅复现选定完整记录，不评价新模型/Prompt的新策略。反事实和world退出核心，不为此开发事件平台。仍保留缺记录失败、不回源网络、不写业务的边界。

预算耗尽、无进展、关键上下文超限、引用连续失败、权限拒绝都有稳定reason_code及可见证据，不能输出虚构退款成功。冲突需追加权威证据或人工核验；模型解释文字本身不能消除事实冲突。

## 5. 核心验收

- H1 自主性：至少6组配对案例，同诉求不同证据；记录模型动作与真实调用对应，允许多个正确路径。
- H2 上下文：同输入hash稳定，金额/来源/政策/冲突不被裁剪篡改，读回scope安全。
- H3 控制：预算、重试、防循环及取消有界，错误Observation回到模型。
- H4 恢复：两类崩溃窗口、旧fence、manifest不兼容、旧revision回调。
- H5 回放：选定完整轨迹strict一致，损坏/缺记录显式失败，零业务写能力。

H1/H2/H3在C06–C08，H4在C09，H5在C10。AS01提前验证AgentScope拦截/恢复/回放可行性，AS02替换循环，不代表H1–H5已验收。C12做核心模型对照，不要求原T39全量Harness消融。术语必须落到代码与失败测试，不以模块命名冒充工程能力。
