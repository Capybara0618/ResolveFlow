# 领域Agent Harness · v1.2核心

范围见[core-scope](core-scope.md)。这里实现售后调查运行层，不研发通用图引擎或Agent平台。LangGraph负责图执行/checkpoint，模型负责下一业务行动，Java负责权威事实与退款授权。

## 1. 核心模块

| 模块 | 职责 | 必须证明 |
| --- | --- | --- |
| HarnessRunner | 动态决策循环、控制动作分派和结束 | Observation后动作来自模型，不是case_type固定路线 |
| ContextBuilder | 分层输入、关键事实/冲突保留、原文引用 | 保存实际请求，超限明确拒绝 |
| ToolExecutor | 白名单MCP/本地检索/证据读取、scope、attempt | 模型不能改主体/URL，无写工具 |
| BudgetGuard | 持久预占/结算、deadline、防无进展 | 恢复不清零、有限终止 |
| ProposalVerifier | Schema、可见引用、hash/版本、缺证检查 | Python通过不等于Java批准 |
| RunStore/ModelClient | 调用/上下文记录、checkpoint/fence、mock/live | 复用已落库结果，UNKNOWN成本可见 |

这些是同一Python服务内的职责，可用小模块/Protocol，不要求每个名词独立类、表或插件系统。SessionStore可由run/model_call/tool_observation/context_snapshot组合实现；EvidenceLedger只是结构化事实视图，不强制额外服务或数据库表。

## 2. 单步顺序

1. 检查run、fence、取消、deadline及manifest兼容。
2. 构造ContextPacket，保存精确provider输入（不含凭证）及hash。
3. 同事务预占预算并建立稳定model_call_id，网络调用在事务外。
4. 返回后带fence保存响应、usage；未落库外部结果标UNKNOWN。
5. 校验模型动作，再保存工具请求；执行后先保存Observation，再推进checkpoint。
6. PROPOSE通过验证后持久最终方案与callback_outbox；其他路径将Observation交回模型。

网络期间不持有长业务事务。锁丢失后停止后续动作；旧worker结果不能推进图或有效回调。回调投递不是“模型又决定了一次”。

## 3. 动作与运行包

动作字段和工具以[Agent规格](agent-spec.md)、C00核心Schema为准。模型不提供run/case/revision、credentials或authorization；PROPOSE候选用recommended_action，运行时补schema_version=2与ID。

沿用[HarnessManifest Schema](../contracts/harness-manifest.schema.json)固定code/graph/state、prompt_hash、context策略、tool schema hash、verifier、模型/参数、token计数、预算、政策和index generation。manifest_id是排除自身后的canonical SHA-256。原Prompt按hash保留，参数只记录实际发送值，不存密钥。

同run恢复用原manifest，未支持版本返回FAILED/MIGRATION_REQUIRED并转人工；不实现自动迁移或滚动版本共存调度。新revision可以新manifest。模型别名漂移必须记录限制，不假定可重现供应商内部权重。

预算跨字段检查：单步不能超过累计，输入+输出+256不能超过provider容量，timeout不超活动窗口。未知token/计费保守估计，超实际预占时记录超额并停后续调用，不伪称严格费用保证。

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

H1/H2/H3在C06–C08，H4在C09，H5在C10。C12做核心模型对照，不要求原T39全量Harness消融。术语必须落到代码与失败测试，不以模块命名冒充工程能力。
