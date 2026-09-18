# Agent Runtime Harness 核心架构

框架v1.1。Agent技术主线：围绕自主售后调查，构建可控、可恢复、可解释和可回放的运行层。业务行为仍以[Agent规格](agent-spec.md)为准；本文件确定运行机制及模块接口，细节见[上下文工程](context-engineering.md)和[轨迹回放](trajectory-replay.md)。当前为实施规格，未实现或取得实验结果。

## 1. 三层职责与自主性

| 层 | 决定什么 | 不拥有的权限 |
| --- | --- | --- |
| 模型决策 | 下一工具/检索词/读取历史证据/追问内容/何时提出方案 | 身份、预算、交易授权、数据库写入 |
| Harness | 构造输入、校验行动、路由工具、持久状态、预算、验证输出、结束运行 | 擅自把模型调查改成固定分类路由；代替Java审批 |
| Java业务 | 权威事实、政策硬规则、风险路由、审批、退款/补发 | 把LLM建议当作未经检查的事实 |

正常路径每次Observation返回后都重新调用模型决定下一行动。允许外层固定StateGraph，但READ_TOOL/SEARCH_POLICY/READ_OBSERVATION/ASK_CUSTOMER/PROPOSE/ESCALATE的选择和参数由模型产生。固定的语法修复、凭证验证、超时终止、业务写校验不影响这个边界。

不实现“识别case_type后代码决定全套工具顺序”。只读工具并行组由模型明确提出，Harness检查独立性与权限后执行，不在后台偷偷把全部证据预取给模型。

## 2. 组成与内部接口

同一个agent-service内的Python模块，不新增部署单元。使用类型化函数/Protocol，避免通用插件框架。

| 模块 | 输入 -> 输出 | 核心约束 |
| --- | --- | --- |
| RunCoordinator | RunRequest -> 当前run/worker claim | revision、lease/fence、取消、终局回调 |
| HarnessRunner | RunSnapshot -> StepOutcome | 驱动下面模块，统一处理持久化边界 |
| ContextBuilder | RunSnapshot + StepBudget -> ContextPacket | 分层组装、证据版本、token计数、裁剪记录 |
| ModelClient | ContextPacket + DecisionSchema -> ModelDecision | mock/live适配、请求ID、用量、超时 |
| ActionValidator | ModelDecision + AllowedCapabilities -> ValidatedAction/Feedback | 只能使用授权工具；拒绝伪造身份和任意URL |
| ToolExecutor | ValidatedAction + BoundContext -> Observation[] | MCP/本地检索/证据读取、重试、稳定call_id |
| SessionStore | AppendBatch + fence -> event sequence | 原始记录、上下文和结果持久化，旧worker隔离 |
| BudgetGuard | actual usage + pending reservation -> Admit/Stop | 累计和单步预算、截止时间、无进展循环 |
| ProposalVerifier | proposed result + seen refs -> Accepted/Feedback | Schema、证据引用、冲突；Java最终再校验 |
| ReplayRunner | ReplayPack + variant manifest -> ReplayReport | 隔离身份与网络、分支缺失明确失败 |

LangGraph负责图执行、检查点和恢复基础。项目代码负责ContextBuilder、预算账、scope绑定、业务证据验证、事件记录、回放与对照实验。简历使用“基于LangGraph构建领域Harness”，不宣称自研完整通用图引擎。

## 3. 单步事务与调用顺序

1. 领取run并确认fence、revision、状态和manifest有效。任何side effect前检查取消与deadline。
2. ContextBuilder从持久记录组装本步packet，写context_snapshot及CONTEXT_BUILT。
3. BudgetGuard为本次模型请求预占估计输入和max_output，写MODEL_REQUESTED、稳定model_call_id，提交事务。
4. 事务外调用模型。完成后在带fence校验的事务中持久响应、实际usage、MODEL_COMPLETED；未保存的外部响应视为UNKNOWN。
5. ActionValidator验证模型动作，写ACTION_ACCEPTED或ACTION_REJECTED。失败反馈只指出违反的约束，不替模型生成下一项业务行动。
6. 工具调用前持久TOOL_REQUESTED，事务外执行；回传结果先保存Observation和TOOL_COMPLETED再推进图。恢复可以补齐“结果已保存但checkpoint未前进”的窗口。
7. 更新预算、facts引用和图状态；下一步重新组装上下文。最终方案由ProposalVerifier检查，通过后同事务建立callback_outbox与终局记录。

Session事件与相关行尽可能同一PG事务；checkpointer仍遵守agent-spec的fence事务要求。不能因为加了event log而宣称整个系统改成Event Sourcing；业务读仍来自明确的状态表，事件用来审计、恢复对照和回放。

## 4. 决策ABI

每次模型只输出一个ModelDecision。以下字段均拒绝未知属性；T35实现JSON Schema及Pydantic验证。

| kind | 业务payload | 行为 |
| --- | --- | --- |
| READ_TOOL | calls:[{tool_name,arguments}]，1–3个 | 选择实际MCP工具；参数互不依赖才可并行 |
| SEARCH_POLICY | query,top_k<=5 | 访问绑定manifest的本地检索 |
| READ_OBSERVATION | observation_id,offset,limit | 按需读取本run/获准继承的持久证据片段 |
| ASK_CUSTOMER | questions:[{field,prompt}]，1–3项；reason_codes | 合并必要追问，等待外部补证 |
| PROPOSE | case_type,recommended_action,evidence_refs,policy_refs,reason_codes,summary,missing_evidence,可选suggested_amount_minor | 形成候选；由运行时补全schema_version及run/case/revision/proposal ID |
| ESCALATE | reason_codes,summary | 提出人工处理；最终回调为recommended_action=MANUAL_REVIEW的方案 |

READ_OBSERVATION是本地存储访问能力，不新增Java权限或第7个MCP业务工具。模型看不到run manifest中的密钥位置、运行身份凭证或内部网络配置。

## 5. 版本化运行包

每次run固定HarnessManifest，见[Schema](../contracts/harness-manifest.schema.json)。记录代码/图/状态schema、Prompt、context策略、工具schema、验证器、模型及生成参数、token计数器、预算、政策与索引hash。敏感值只保存是否已配置，不保存API key或可复用token。

同run重启必须使用原manifest；旧版本worker已不可用时标MIGRATION_REQUIRED并转人工/运维，不以新Prompt继续旧checkpoint。实现层作为FAILED的reason_code，不新增Java工单状态。输入revision变化启动新run时可以采用新manifest，并保留parent_run_id和继承证据出处。

manifest_id为规范化manifest内容（排除manifest_id自身）的SHA-256；模型别名不能保证供应商权重不变，优先固定snapshot；不能固定时记录请求日期与provider返回版本，并在报告注明外部漂移限制。

Schema固定prompt_hash、context_policy_version、tool_schema_hash、verifier_version等字段；Prompt原文作为可寻址artifact保留。parameters仅填写provider支持且实际发送的生成参数，不支持的字段省略，不能记录一个实际未发送的seed。模型返回版本/请求日期记录在model_call，不回写不可变manifest。JSON Schema校验结构；T35语义验证器另检查hash、模型能力及预算关系：max_prompt_tokens<=累计输入上限，max_output_tokens<=累计输出上限，单步输入+输出+256<=provider容量，单次timeout<=活动deadline。更严格的预算允许，超过框架上限需显式修订。

首次执行前固定manifest与READY索引；入队尚未准备好时不调用模型。等待依赖仍受控制面deadline约束，未就绪按F17转人工。ESCALATE缺少分类时由运行时使用OUT_OF_SCOPE作为保守技术兜底并带原因；只引用已有可见证据，不补造事实。

## 6. 预算、重复与停止

累计上限沿用agent-spec：12次模型调用、16次外部工具/检索调用、40k输入和4k输出、120秒活动deadline。修复和网络重试算模型调用次数。READ_OBSERVATION不算外部调用，但计入决策步、输入tokens及单独local_read_count（最多8次）。单次模型输入最多8192 tokens、预留输出最多1024 tokens，受provider上下文容量和剩余总预算进一步收紧。

每个模型请求预占上限，成功按真实usage结算；UNKNOWN无法知道精确成本时保守保留预占，报告已知消耗与未知上界。SDK支持usage时记录准确值，不支持时按锁定token计数器估算并标ESTIMATED。不能在重启后清零预算。

输入token计数若只能估算，预占使用保守余量并记录估算误差；provider返回实际usage超过预占时记BUDGET_OVERRUN并停止后续调用，不倒扣数据掩盖超额。严格可保证的是请求次数、配置的输出上限和后续准入，未知provider计费/隐藏token不能宣称绝不超过精确费用。实验另设用户确认的整体费用上限及停止规则。

工具反馈指纹=(kind,规范化参数,scope,input_revision,source_version)。连续两次无新证据的同动作返回NO_PROGRESS反馈，第三次仍无进展由Harness停止并转人工；新source_version、下一分页不视为重复。实际工具读取可以复用未过期Observation，但复用会作为明确Observation告知模型，不能悄悄把旧事实当新事实。

输出验证最多一次修复机会；超权限工具403直接停止；429/暂时超时按唯一重试负责人处理。预算耗尽、无进展、manifest不兼容等停止均有稳定reason_code、可见进度和已知证据，不发虚构退款成功回调。

## 7. 验证与有限反馈

ProposalVerifier负责：结构合法；ref出自当前可见记录；来源/版本/hash匹配；关键事实被保留；同一事实存在未解释冲突时不能自动提交退款建议。验证器可以要求模型修复缺失引用或解释冲突，但不注入“正确答案”。

Java独立复核可退金额、权益、政策和审批，Python验证通过不赋予写权限。提示注入检测可以给出告警，但权限控制不能依赖分类器检出率。只有观测到的材料可以被引用，模型自行生成的事实保持UNVERIFIED。

## 8. 必须证明的自主性

H-AUT-01：给定同一用户诉求，不同工具Observation导致可解释的后续行动变化，不能只换最终文字。

H-AUT-02：工具可用集合固定，模型能选择追问/继续调查/停止；程序未按case_type硬编码全套工具顺序。

H-AUT-03：工具失败后模型接收到错误Observation，选择其他合法证据来源或转人工；预算终止由Harness决定。

H-AUT-04：原决策、实际分派、拦截/复用原因均记录；实际工具调用与模型意图可对应，禁止后台预跑工具后伪造轨迹。

用24组配对合成fixture覆盖以上情况（含在总240案例集中，并按家族整体划分）；验证允许动作/证据满足情况，不强制唯一轨迹。更少调用或更早正确停止可能是更好的结果。

## 9. 实施及证据

T35先确定manifest、动作契约、模块边界；T36/T37实现上下文和日志；T20/T22实现循环/恢复；T38实现回放并验收GH；T39完成Harness消融后进入G6。GH检查上下文不丢关键字段、严格回放一致、分支缺失显式报告、无进展退出、自治配对可解释、回放无写能力；完整live对照在G6验收。

优先级固定：1)运行层+基础上下文+可信工具；2)持久轨迹与恢复；3)隔离回放；4)有证据的上下文优化。暂不增加自进化、通用插件市场、多Agent或LLM长文本总结器。

## 10. 工程参考

Harness术语用于模型外的运行循环和工具路由，参考[Anthropic工程说明](https://www.anthropic.com/engineering/managed-agents)。长期任务的状态衔接参考[long-running harness文章](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)。本项目选择短时调查+跨事件继续，不能把人工等待72小时描述成模型自主运行72小时。
