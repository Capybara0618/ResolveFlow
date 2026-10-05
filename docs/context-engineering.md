# ContextBuilder · v1.2核心

这是Harness内部能力，不是独立上下文平台。目标是让模型看到必要事实、来源和缺口，同时限制输入长度。

v1.3接入AgentScope后本规格不降级：SDK历史/自动注入与工具Schema必须进入最终输入核算；关闭绕过本策略的自动压缩、LLM总结及长期记忆。框架适配按[迁移规格](agentscope-migration.md)，不能直接用默认memory替换事实视图。

## 1. 三类记录

原始合成用户输入/工具Observation持久保留；结构化facts视图保存值、来源、source_version/hash与FRESH/STALE/CONFLICT/UNVERIFIED；ContextPacket保存本次实际模型请求。

来源分AUTHORITY/USER_CLAIM/MODEL_INFERENCE。用户陈述与模型推断不能因摘要或重复出现而升级为权威；不同来源冲突同时保留，新版本替换同源旧事实仍保留原记录。

## 2. 简单分层

| 层 | 内容 | 策略 |
| --- | --- | --- |
| P0 | 系统约束、动作/工具schema | 不可裁剪 |
| P1 | 当前诉求、已确认动作、最近问答 | 保留，超长附件转原文索引 |
| P2 | 金额/数量/支付/退款/物流结论、政策版本、冲突 | 精确字段及来源，禁止生成式重写 |
| P3 | 当前Observation、政策段落、缺口 | 有界片段与引用 |
| P4 | 较早工具/问答索引 | 确定性提取，按需读回 |

不做向量长期记忆或LLM历史摘要。排序按层、观察序列和稳定ID，不能用评测Gold决定“相关性”。

## 3. 裁剪与读回

输入上限=min(8192,provider容量-输出预留,累计剩余输入)，计入system/tool schema/provider包装。最终估计值包含256包装预留，cap不再重复扣减包装；默认provider容量8192/输出1024时cap=7168。先放P0/P1/P2，转索引后仍超限则CONTEXT_REQUIRED_OVERFLOW转人工，不删约束。随后加入P3/P4，超限去重复和最旧非关键段，记录omitted_refs及原因。

工具给模型片段<=8KiB，原始接收上限256KiB。tool_call/result成对保留或一起转成历史证据消息，不留下非法provider格式。物流长轨迹用首末/异常/状态变化结构化提取，保留原文位置。

READ_OBSERVATION(offset>=0,limit<=4000字符)仅访问当前run及明确允许继承的材料；不存在ref返回NOT_FOUND，不猜内容或跨case查找。总本地读取<=8次，仍消耗模型决策和输入预算。

## 4. 快照

保存context_id、run/step、manifest_id、实际messages与tool schema hash、token_count_mode/估计值、selected_refs/omitted_refs、protected_fact_hash、context_hash。

protected_fact_hash覆盖必保留值/来源/版本/冲突，证明未被裁剪改变，不证明事实本身正确。provider适配后的最终请求hash留存，不能只保存适配前大致摘要。token不精确时标ESTIMATED，费用报告以usage及未知量分开记录。

## 5. 完成标准

2026-09-26补充验收：ContextPacket与实际ModelClient输入须逐消息一致，P0保留system角色且只发送一次；不得在裁剪后追加SDK hints/完整工具历史。计数包含最终渲染的层标签、分隔符、schema与包装预留。当前UTF-8字节估算标ESTIMATED，不宣称供应商精确token；C08真实适配还须验证最终HTTP载荷/参数/hash及供应商计数。退款P2字段直接对齐core契约的`reserved_refund_amount`，不虚构`refundable_amount`权威字段。

至少覆盖长物流、矛盾来源、缺引用、超限、恶意正文、跨scope读回、合法tool pair七类fixture。提供一个裁剪前后演示，验证必保留字段一致。

核心不要求C0/C1/C2全量live消融；若简历宣称“降低Token X%”，必须另做同数据/模型下的累计成本和质量对照，否则只描述实现及正确性证据。

## 6. 2026-10-05 第二批紧凑呈现

上下文策略p0-p4-v6-compact-material-index、计量utf8-json-bytes-v3-single-wrapper。每轮重建，不追加SDK完整历史；同来源事实共享一次完整四字段引用和authority，各值/状态/冲突仍精确保留。既有原文、facts、实际消息和模型轨迹不改写。

材料正文超过600字符时，展示首240/尾120字符、总字符长度和material:材料ID读回索引；身份、版本/hash、核验/问答关系保留。该中段索引进入omitted_refs。READ_OBSERVATION用observation_id=material:ID和arguments.offset/limit分页，仅绑定当前run派发revision；恢复从原持久快照重建，无额外网络。读回source_type保持CUSTOMER_STATEMENT/REVIEWER_VERIFICATION，citation为空，不能用读回窗口代替get_case_evidence外层引用。

每轮可选近期Observation片段和旧索引仍按预算裁剪，原文完整保留。过大的材料元数据、问题或不可裁剪条件仍会明确超限；不使用LLM摘要，不承诺任意长输入都能完成。

## 7. 2026-10-05 常驻规则与短引用

该批上下文策略为 `p0-p4-v7-run-short-refs`，见[规则/工具/引用规格](agent-context-protocol.md)。五 MCP 工具始终直接可用；常驻规则压缩，相关材料/订单/物流/政策解释随已提供或已读的对应来源出现，不增加工具发现轮次。最终建议协议仍常驻。

模型视图中，事实组用 O 编号、工具、来源类型/authority、版本表达来源，政策用 P 编号保留 bundle/版本/规则/全文。完整身份不再要求模型复制，而是保留在原始 Observation 及当前包引用映射；事实值/状态/冲突/note 与 `protected_fact_hash` 不变。这是来源呈现变化，不是删除来源/哈希校验。泛用或旧 schema 的 ContextBuilder 仍保留完整引用呈现，正式 SDK 通过 `reference_format=run-short-v1` 显式选择短编号。

建议和 review_findings 的编号在严格 ABI/原引用验证前展开，未知/错类型拒绝；只有强制 P2 的引用可通过编号提交。原文读取编号只映射当前 run 已知记录，材料/失败/窗口不因编号成为可引用权威。持久原始响应、原工具记录和 manifest 支持同版本重建，无新数据库或模型调用；当前 strict 包另冻于 context-v4，旧包不改。

## 8. 第三批调查/终止的表达边界

当前策略 `p0-p4-v8-investigation-stop`，详见[规格](agent-investigation-batch3.md)。真实模型曾把JSON说明中的type/action_fields/bounds当输出字段，现将说明用普通文字呈现，仅动作示例是独立扁平JSON。示例非业务路线/事实，引用依然只能取当前P2；动作解析不宽松化。

常驻规则明确系统事实用工具、条件足够即给建议、审批不同于缺证调查。查询用中文聚焦已知事实；核验条件按实际召回条款显示，不把丢失/质量的人审条件套到未发货，也不显示没召回的条款条件。无需全读五工具，不增加自动LLM总结/摘要。事实、来源、问答、原文、政策条件和原cap保留，超限仍明确失败。

来源检查由verifier v4执行，不靠多写提示词代替；当前回放investigation-v5七条。实际真实评测与最终工程收口的版本/限制见[报告](../reports/agent-investigation-batch3/README.md)，不能把脚本通过或历史manifest当最终LLM准确率。
