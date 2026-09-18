# ContextBuilder · v1.2核心

这是Harness内部能力，不是独立上下文平台。目标是让模型看到必要事实、来源和缺口，同时限制输入长度。

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

输入上限=min(8192,provider容量-输出预留-256,累计剩余输入)，计入system/tool schema/provider包装。先放P0/P1/P2，转索引后仍超限则CONTEXT_REQUIRED_OVERFLOW转人工，不删约束。随后加入P3/P4，超限去重复和最旧非关键段，记录omitted_refs及原因。

工具给模型片段<=8KiB，原始接收上限256KiB。tool_call/result成对保留或一起转成历史证据消息，不留下非法provider格式。物流长轨迹用首末/异常/状态变化结构化提取，保留原文位置。

READ_OBSERVATION(offset>=0,limit<=4000字符)仅访问当前run及明确允许继承的材料；不存在ref返回NOT_FOUND，不猜内容或跨case查找。总本地读取<=8次，仍消耗模型决策和输入预算。

## 4. 快照

保存context_id、run/step、manifest_id、实际messages与tool schema hash、token_count_mode/估计值、selected_refs/omitted_refs、protected_fact_hash、context_hash。

protected_fact_hash覆盖必保留值/来源/版本/冲突，证明未被裁剪改变，不证明事实本身正确。provider适配后的最终请求hash留存，不能只保存适配前大致摘要。token不精确时标ESTIMATED，费用报告以usage及未知量分开记录。

## 5. 完成标准

至少覆盖长物流、矛盾来源、缺引用、超限、恶意正文、跨scope读回、合法tool pair七类fixture。提供一个裁剪前后演示，验证必保留字段一致。

核心不要求C0/C1/C2全量live消融；若简历宣称“降低Token X%”，必须另做同数据/模型下的累计成本和质量对照，否则只描述实现及正确性证据。
