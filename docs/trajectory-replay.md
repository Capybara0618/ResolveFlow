# 轨迹记录、隔离回放与调试

框架v1.1。故障恢复、轨迹回放和新版本评测采用不同语义；见[Harness架构](agent-harness.md)。

## 1. 运行记录

session_event包含event_id,run_id,sequence,step_id,manifest_id,fence,event_type,schema_version,payload_ref,payload_hash,occurred_at。sequence由PG事务在run内分配；允许原始显式动作记录，不收集隐式思维链。

事件类型固定：RUN_CREATED、CONTEXT_BUILT、MODEL_REQUESTED、MODEL_COMPLETED、MODEL_UNKNOWN、ACTION_ACCEPTED、ACTION_REJECTED、TOOL_REQUESTED、TOOL_COMPLETED、TOOL_FAILED、BUDGET_UPDATED、CHECKPOINT_SAVED、PROPOSAL_VALIDATED、CALLBACK_ENQUEUED、RUN_STOPPED。每个原始payload在独立表持久保存，事件引用到它。

事件不是完整状态恢复的唯一来源；运行依然用checkpointer与业务状态表。记录和关键结果同事务，跨checkpointer不原子的窗口要用稳定step/call ID补齐，不能丢失事实后靠模型补写日志。

## 2. ReplayPack

目录包含manifest.json、run-input.json、events.jsonl、contexts/、observations/、model-responses/、policy-snapshot/、expected/（测试端不向模型提供）。索引列出各文件hash、来源source_run_id、schema版本、导出范围和脱敏状态。

只导出合成数据。默认不导出service token、API key、私钥或可重用审批信息；operation_id仅作非授权关联。缺文件/hash不符在回放开始前失败。包的hash只用于完整性检查，不声称防管理员篡改。

首次实现通过CLI导出，不新增公开轨迹导出API。UI只显示受限摘要，完整pack在开发者本地分析。

## 3. 三种模式

| 模式 | 模型 | 工具环境 | 能证明什么 |
| --- | --- | --- | --- |
| strict | 原记录显式模型响应 | 严格匹配原调用记录 | 相同运行逻辑可重建决策/校验/预算，不证明新模型会作同样决策 |
| counterfactual-recorded | 新模型或Prompt/context配置 | 已记录工具返回 | 有覆盖的历史状态下比较新决策，不能凭空回答新分支 |
| counterfactual-world | 新模型或Prompt/context配置 | 固定合成世界模拟器 | 新分支可查询，评估更完整的策略；不是原生产轨迹重放 |

三种mode结果分别报告。strict禁止任何模型API访问；counterfactual模式只有显式live配置才访问选定模型endpoint，mock运行仍可测流程。

## 4. 匹配与分支

strict按run/step/调用序号与tool名、规范参数、scope_hash、input_revision、source_version匹配。并行组按稳定call_id集合匹配，真实完成先后可不同；预算/trace等非语义时间字段规范化比较。

strict注入原记录的实验Clock、usage/UNKNOWN和外部错误，不把回放机器的当前时间或零网络耗时当原运行预算。source_run_id/原逻辑step与call ID用于匹配，evaluation_run_id只隔离存储，不篡改业务scope；原身份ID仅是数据，没有对应可用凭证。缺少必要时钟/用量记录的包标不完整，不能声称精确预算复现。

counterfactual-recorded按tool名、规范参数、scope_hash和快照版本匹配，不能仅按“第3个工具”返回第3条历史结果。重复相同调用返回相同冻结结果并单独计重复次数；参数变更、缺分页、未记录工具/政策查询返回REPLAY_MISS。

同一参数在历史上有多个不同版本/结果时，pack必须绑定一个明确的冻结快照；没有唯一可匹配结果则报REPLAY_AMBIGUOUS并标INCOMPLETE，不任取最新或最有利的答案。会随时间变化的故障恢复序列适合strict复现；反事实需用声明了Clock/故障语义的world评测。

REPLAY_MISS默认终止该分支并标INCOMPLETE，报告命中/缺失与完整覆盖比例。不得用空结果、最近似结果或live Java接口补齐。新检索query用冻结政策与索引版本在本地重新检索是允许的，但必须在pack声明支持local-policy-search并计为重算结果。

counterfactual-world从snapshot构建固定合成订单、物流、仓库与政策，采用实验Clock；回答没有预先录制的合法查询。语义由生成器决定，不让模型生成“更合适的工具返回”。工具失败注入也固定seed与策略。

## 5. 隔离边界

回放使用独立evaluation_run_id与临时实验库，不能连接live agent_db/case_db，不加载业务JWT/审批密钥、不挂载provider通道。ToolExecutor替换为RecordedToolAdapter或WorldToolAdapter，CallbackSink只写本地报告；无HTTP回调case和退款消息发布能力。

网络出站strict全部禁用；counterfactual-live仅放行配置的模型服务，Java、MQ、支付stub及公网其他地址拒绝。测试验证注入“退款工具/回调URL”也不产生业务效果。运行入口在启动时校验adapter与mode匹配，不能仅靠调用方约定。

原run只读，报告不能更新其状态或覆盖原pack。用新模型对历史状态作不同决策不触发原case重新授权。

## 6. 差异报告

输出：原/新manifest；首个动作分歧；工具名/参数/证据差异；上下文selected/omitted差异；结束原因；允许动作一致性；引用有效性；总tokens/时延；覆盖率与REPLAY_MISS。按case配对，不把覆盖不足case从总体分母悄悄剔除。

不得强求文本逐字一致；strict检查规范化状态/动作/引用/预算账一致，生成时间和trace ID排除。counterfactual检查Gold允许方案集合与证据条件，轨迹不同不自动算错。

## 7. 必测场景

H-RPL-01：完全录制包strict回放，无网络、无业务写入，规范化终局一致。

H-RPL-02：新Prompt选择未记录工具或不同参数，明确REPLAY_MISS，不能返回错误历史证据。

H-RPL-03：故意缺少artifact/hash冲突，启动失败且保留说明。

H-RPL-04：回放中提交PROPOSE，结果只写本地报告，原工单/退款账不变。

H-RPL-05：相同合成world支持新的合法查询，输出world模式标识，不与recorded结果混报。

H-RPL-06：strict检测模型/工具记录不匹配的首个step；并行返回顺序变化不造成伪差异。

v1.1先完成strict与counterfactual-recorded，再复用评测世界生成器实现world。开发dev包和冻结test包分开，回放不能把测试Gold混入上下文。
