# ResolveFlow：七条简历文案与量化实验

2026-10-07。用户确认保留七条贡献，以实验决定最终成果表达。本文件取代六条模板作为本轮简历入口；下文由实测逐项更新，详细规模、场景矩阵、评分和批次以[量化实验执行计划](resume-quantification-plan.md)为准。当前实施进度仍只维护于 tasks/todo.md 顶部。

## 项目介绍

**ResolveFlow｜基于微服务与 Agent 的电商智能售后平台｜个人项目**

面向多商家售后场景，贯通购物、退款申请、Agent 调查、人工审批与模拟退款执行。Agent 根据订单、物流和政策证据动态选择调查动作并生成建议，Java 服务负责业务状态、版本化授权与资金约束，提供工单及调查轨迹展示。

技术栈：Python、FastAPI、AgentScope、MCP、PostgreSQL/pgvector、BGE、RAG；Java、Spring Boot、Spring Cloud Gateway、MyBatis、MySQL、Redis、RocketMQ、Vue 3、TypeScript、Docker。

## 七条正文

1. **多租户电商微服务**：采用 Gateway、Case、Commerce 与 Python Agent 四服务架构，通过 RocketMQ 与 HTTP 协作；实现商家数据与权限隔离、平台买家跨店购物，通过版本校验及行级锁处理购物车并发与金额一致性，支持单店多行订单原子发布和逐行独立退款。

2. **Agent 自主决策**：基于 AgentScope 与 MCP 构建观察驱动的调查循环，动态选择工具、补充材料及生成有引用的建议；围绕32个售后场景完成与固定调查流程的128次真实模型对照，动态组有效建议率87.5%，业务HTTP读取次数减少17.2%。

3. **政策检索与 RAG**：基于 BGE 与 pgvector 检索政策，绑定付款时刻的适用版本并过滤商家与品类；对外部原始政策文档开展五组检索实验，采用BM25→rerank使Recall@3达85.8%、较BM25提升4.4个百分点，商城政策Recall@3由93.5%提升至98.1%。

4. **版本化授权控制**：通过 input_revision 使补证或人工核验后的旧方案失效并触发新调查，审批及消费均复核版本；覆盖8类80次版本失效与竞争场景，90次过期授权尝试全部拦截，80次当前有效授权控制全部通过。

5. **分布式可靠退款**：通过 RocketMQ、Outbox/Inbox、操作幂等与金额预留处理消息重投和并发退款，UNKNOWN保留占用并按原操作对账；在6类60次故障实验中，重复成功退款和资金超额均为0，10次UNKNOWN全部查询收敛。

6. **Agent Harness 防护**：统一调用预算、工具白名单与schema/引用校验，通过有限纠错及防循环控制调查；采用数据库租约、fence和持久快照恢复运行，在3类中断窗口的15组真实模型对照中，续跑模型请求减少16.4%、token减少12.2%，18条strict离线回放全部匹配。

7. **Redis 缓存与限流**：为审核队列建立复合索引与游标分页，采用 Redis 短期缓存及 Semaphore 有界回源；在2万工单、30并发下，三轮测量的接口p95由63.9ms降至18.9ms，每成功请求数据库查询数减少99.76%；12个Redis故障窗口实测回源并发峰值8。

七条实验已完成，完整原始记录和计量口径见[统一报告](../reports/resume-quantification-v1/README.md)。动态Agent的质量低于固定流程（87.5% vs96.9%），所以删除预设准确率/复杂处理提升；17.2%只指业务HTTP读取减少，不能表述为模型费用或整体效率提升。RAG重排为本轮实验接线、生产默认仍dense，CPU重排耗时在报告保留。正常性能18窗口有1次transport失败；Redis超时场景拒绝率中位数42.50%，12故障窗口峰值8是实际Mapper计量，非配置值。

## 已执行的实验设计（细项及原始结果以报告为准）

| 条目 | 实验与指标 | 规模及现有基础 |
| --- | --- | --- |
| 1 | 不单独增加量化；保留架构、隔离与事务设计 | 复用[业务闭环](../reports/product-flow.md)及[多行退款](../reports/multiline-refunds.md)证据 |
| 2 | 动态 Agent 对比固定调查流程；相同 LLM、RAG、源事实、工具权限与输出校验；收集整体建议准确率、复杂场景有效处理率及模型/工具调用 | 32场景、每组每场景2次，共128次；评测固定流程已实现，Codex按来源完成128次语义复核，见[本轮报告](../reports/resume-quantification-v1/agent/README.md) |
| 3 | 外部原始政策文档主实验：BM25、dense、BM25→rerank、BM25+dense→RRF、BM25+dense→RRF→rerank；商城政策作业务补充 | 共用原文/分块/query/标签，BGE-reranker-base本地CPU实测，冻结模型revision；外部29query与18附加探针、商城60query，见[本轮报告](../reports/resume-quantification-v1/rag/README.md) |
| 4 | 过期授权拦截，同时核对有效授权正常通过；补证/核验、审批、消费及迟到结果的竞争窗口 | 8 类场景×10 轮=80 次，V1–V8矩阵和过期/有效尝试分母见执行计划；已有[版本与业务链](../reports/product-flow.md) |
| 5 | 重投、同行/跨行并发、provider 成功响应丢失、资金落库后中断及结果重投；核对 provider、操作和账本 | 6 类故障×10 轮=60 次；统计重复成功/超额退款及 UNKNOWN 收敛。已有[资金并发证据](../reports/multiline-refunds.md)，模拟 provider 范围保留 |
| 6 | 相同任务与故障点下，持久恢复对比从头执行；同时收集恢复阶段模型请求及真实输入/输出 token，另测 strict 匹配 | 3 个故障窗口各 5 对=15对/30次运行；复用[跨进程恢复](../reports/c09-production-recovery.md)与[18 包回放](../reports/agent-handoff-live/README.md)。mock/HTTP 桩用于调用计数验证，token 对照单独收集真实 provider usage |
| 7 | 原索引、优化索引、优化索引+缓存三条件性能对照；另测缓存/Redis 故障回源 | 用户采用本方案：2 万工单，10/30 并发，30 秒预热、60 秒测量，各 3 轮；统计 p95、成功 RPS、错误率及 DB 查询量。故障窗口另记录回源峰值/拒绝率。复用[现有测量入口](../reports/c11-review-query.md) |

建议准确率按动作、事实、适用政策及补证责任逐例评定；复杂场景在运行前分类。两组的检索 query 使用同一模型，固定流程按预设次序调查，动态 Agent 按 Observation 选择行动。评分由 Codex 按实际输入和完整轨迹复核，无新增用户人工标签步骤。

RAG 先比较候选，随后两组 Agent 共用选定检索方案。RRF 融合召回排名，再执行 rerank。Recall@3 为必需条款的覆盖比例，完整依据命中率@3 为前三找齐全部必需条款的查询比例；MRR 衡量首个相关条款的排名。检索耗时包含 query 编码、实际召回、融合及重排，不含首次模型下载/加载。外部与商城结果分别报告。

恢复请求减少量按「从头执行新增请求−持久恢复新增请求」统计；输入与输出 token 分开留原始 usage，再汇总差异。每个窗口分别统计，strict 匹配与恢复收益独立报告。

本轮按既定协议执行；原输入、Gold及历史报告保留，原始资产与逐项结果见统一报告。当前进度只看tasks/todo.md顶部，无默认下一项付费评测或业务优化任务。
