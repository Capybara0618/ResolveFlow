# Context Builder：分层上下文与证据保真

框架v1.1，归属Harness。目标是每次调用都提供足够证据、明确来源和有界输入，并可解释删去了什么。单次调用预算与累计调用成本分开；上下文简短不代表总成本必然下降。

## 1. 三种存储

- SessionStore保存完整合成输入、模型显式输出、工具Observation与失败记录。
- EvidenceLedger是按fact_key组织的结构化事实视图，保存来源、版本、hash、observed_at、validity；与工具原文关联。
- ContextPacket是某一步实际发给模型的messages/tool schemas/允许动作与预算提示，必须保存精确序列化快照。

数据库/物流字段是权威证据；用户材料是用户陈述；模型提炼为待验证推断。三者分别标AUTHORITY/USER_CLAIM/MODEL_INFERENCE。摘要不改变source_type或提高可信等级。

## 2. 分层组装规则

| 层 | 内容 | 策略 |
| --- | --- | --- |
| P0 控制约束 | 系统任务、只读权限、可用动作Schema、预算、输出协议 | 固定前缀；不能裁掉权限和schema |
| P1 当前诉求 | 当前revision描述、用户确认动作、最近问题与回答 | 保留；大段材料保存原文并显示索引 |
| P2 关键事实 | 行金额/数量/支付状态、权益、物流结论、事实冲突、政策版本 | 精确结构化字段，保留source/version，不能LLM改写 |
| P3 当前工作证据 | 最近Observation、当前检索结果、待补缺口相关材料 | 按确定性优先级取用，包含引用 |
| P4 历史摘要与索引 | 较早成功工具结果、重复日志、历史问答 | 结构化提取+引用目录，需要时READ_OBSERVATION |

P0工具schema应紧凑且版本固定；上下文排序先按P层，再按当前缺口相关字段、更新时间、observation_id打破并列。缺口可能由模型提出，排序器不能用Gold或未知世界状态给提示。

## 3. 关键事实保真

EvidenceLedger字段：fact_key,value,source_type,source_ref,source_version,content_hash,observed_at,validity=FRESH/STALE/CONFLICT/UNVERIFIED,observation_id。金额/数量从工具结构化返回提取，模型不能覆盖。

同一来源版本更新时旧值标STALE，保留历史；来源不同且值矛盾则两条标CONFLICT，显示双方引用，不用“取最新一条”消除冲突。用户后续解释保留USER_CLAIM属性。权威金额/权益执行前仍由Java重新查询。

禁止用生成式摘要重写金额、状态、订单行、政策时间和动作范围。历史物流轨迹可确定性提取“首条、末条、异常、状态变化”并保存省略段位置。超过8KB的原工具结果完整保存，仅发受限excerpt给模型；显式标truncated和fetchable_ref。

## 4. 裁剪算法

1. 计算本次最大输入=min(8192,模型context_window-max_output-安全余量256,累计剩余输入预算)。计数必须包含system、工具Schema及模板包装。
2. 组装P0/P1/P2；若这些本身超限，先将大段非结构化用户附件转索引，仍超限则返回CONTEXT_REQUIRED_OVERFLOW并转人工。不得静默删关键事实/约束。
3. 加入P3，默认保留最近2次完整有界Observation；同调用批次的tool_call与tool_result必须成对。
4. 再加入P4；超限依次去重复内容、缩短无关历史片段、移除最旧非关键片段，只保留引用索引。
5. 输出精确ContextPacket、token计数、selected_refs/omitted_refs、每项裁剪reason、policy/manifest hash；同输入+同版本+同tokenizer输出相同packet hash。

旧模型调用的tool_call/result不能只保留一半破坏provider消息格式。若换成“历史证据索引”消息，应一起移除原pair，再以独立数据消息表示，记录转换。provider特定格式通过ModelClient适配器处理，并保存最终实际请求hash。

READ_OBSERVATION仅访问当前run及case允许继承的证据；参数offset>=0、limit<=4000字符。返回source元数据与下一个offset。跨scope请求拒绝；不存在ref返回NOT_FOUND，不从相似历史记录猜内容。

## 5. ContextPacket数据契约

ContextPacket：context_id,run_id,step_id,manifest_id,messages,tool_schema_hash,estimated_input_tokens,token_count_mode,selected_refs,omitted_refs,protected_fact_hash,context_hash。

protected_fact_hash覆盖当前P2结构化事实的值/来源/版本/冲突标记（固定排序）；用于证明压缩前后未更改关键字段，不代表事实本身必然正确。context_hash覆盖实际provider输入，含裁剪后的消息和工具Schema，不含API key、时间噪声或provider_request_id。

环境不支持官方tokenizer时使用保守估计并标ESTIMATED；live报告另存provider usage，不能以字符数冒充准确tokens。超限拒绝也计入任务失败与预算策略统计。

## 6. 测试与实验

H-CTX-01：同输入重复构建hash一致；变量排序不影响结果。

H-CTX-02：长物流记录裁剪后金额、来源、冲突、政策版本保持一致；原文可按ref精确取回。

H-CTX-03：关键层超预算显式失败；不输出缺约束packet。

H-CTX-04：旧revision材料不掩盖新材料；未经许可的历史case引用拒绝。

H-CTX-05：恶意正文中的控制指令作为数据，schema/scope不改变；消息tool pair完整。

对照C0=按时间顺序拼接+相同预算上限（超限记失败）；C1=本分层组装；C2=组装+按需READ_OBSERVATION。相同模型、数据、policy、工具和权限。报告质量、累计tokens、工具/本地读取次数、context构建时延、overflow率、关键事实保留率；累计成本包含更多轮交互，不能只报单步tokens减少。

小型正常工单可能无需压缩；另外准备含长轨迹、重复材料、矛盾证据的压力分层，分别报告，不把所有样本人为加长来制造收益。
