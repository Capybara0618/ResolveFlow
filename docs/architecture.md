# 系统架构与决策记录

## 1. 部署单元与所有权

| 服务 | 端口（容器内部） | 所有数据 | 核心职责 |
| --- | --- | --- | --- |
| gateway | 8080 | 无业务库 | 入口路由、JWT验证、请求ID、Redis分布式限流 |
| commerce-service | 8081 | commerce_db / MySQL | 订单、支付账、行权益、退款操作；模拟支付provider适配 |
| fulfillment-service | 8082 | fulfillment_db / MySQL | 物流、仓库清单、库存预留、补发操作；模拟承运商适配 |
| case-service | 8083 | case_db / MySQL | 工单、材料、方案、政策原件和结构化规则、授权、审批、编排、进度投影、演示身份 |
| agent-service | 8090 | agent_db / PostgreSQL | Harness调度、上下文/证据账、版本化会话轨迹、任务租约、LangGraph检查点、政策索引、模型调用 |

Java内部按api/application/domain/infrastructure分包。case-service中身份、政策、审批是独立模块，不额外部署服务。共享库只包含错误协议、观测、认证与事件信封，禁止共享JPA实体/Mapper或跨库join。

Python同一镜像可以启动API进程和worker进程；二者共用agent_db。部署进程数量不是微服务亮点，划分依据是状态所有权与故障隔离。

## 2. 固定调用方式

- 浏览器 -> gateway -> Java服务：REST；页面通过case-service的SSE读进度。
- Java <-> Java：Spring HTTP客户端或OpenFeign（固定选择OpenFeign+LoadBalancer；T00验证starter），Nacos服务发现；内部service JWT。
- Java业务事件：RocketMQ，采用本地Outbox，消费者inbox去重。
- case-service -> agent-service：HTTP持久化任务提交，202仅在PG任务记录提交后返回；Java outbox专用HTTP dispatcher重试。
- agent-service -> case-service：持久化回调队列提交问题、方案或失败，所有请求有回调幂等键。
- Agent业务工具：Python官方MCP SDK，以同仓独立stdio工具适配进程提供只读工具，适配器调用Java受控REST。每个run传入受限context；不开放公共MCP端点。
- Agent政策查询：本进程调用检索模块；无需绕MCP访问本地索引。
- Python不直接消费RocketMQ，避免双语言客户端兼容成为关键路径。异步任务由PG持久队列+租约执行，不再加Celery或第二个MQ。

MCP适配器是协议适配层，不拥有业务数据。模型只能给工具业务参数，不能提供Authorization、用户身份、URL或SQL。

## 3. 主流程与可靠交接

1. case本地事务创建工单、input_revision=1和AgentRequested outbox。
2. dispatcher POST agent /internal/v1/runs；PG以case_id/input_revision唯一入队；同请求重试返回原run。
3. Python worker租约领取任务，执行单Agent循环；工具读取限定订单数据，结果持久化。
4. Agent将proposal或question写入PG callback_outbox；回调case服务时携带input_revision，旧结果被记录为STALE且不触发写入。
5. Java复核Schema、证据、适用政策和业务条件。低风险自动授权，其他路径进入补充、审核或明确拒绝。
6. case形成授权和执行操作。编排先从commerce预留行权益，再向目标服务投递RefundRequested或ReshipRequested。
7. 目标服务先inbox去重并记录操作，再异步调用provider；调用结果经本地事务及outbox回传。
8. case更新进度；权益提交/释放使用独立幂等步骤，只有所有必须步骤收敛才显示工单完成。

## 4. 决策记录（ADR）

| ADR | 决策 | 原因与取舍 |
| --- | --- | --- |
| 01 | 4个Java进程+1个Python服务 | 足够展示独立事务、服务调用和故障；避免为每个名词拆服务 |
| 02 | commerce同时管理订单/支付/退款/权益 | 金额和退款上限可在单库事务强制执行；仍有case、履约跨服务流程 |
| 03 | Outbox + inbox +编排补偿，不引入Seata | 学习故障语义，允许服务独立提交；明确没有端到端exactly-once |
| 04 | 退款、补发共享订单行权益 | 防止“退款幂等正确却又补发一次”的跨动作错误 |
| 05 | Python LangGraph StateGraph + PG checkpointer | 使用成熟持久化机制，技术深度集中在业务恢复和一致性 |
| 06 | MCP stdio只读适配器+HTTP控制面 | 展示实际MCP集成；服务间认证仍由受限JWT保证 |
| 07 | 结构化政策为执行权威，RAG负责定位解释 | 向量相似度不能决定资金权限 |
| 08 | 执行授权为Java数据库记录 | 可撤销、可绑定版本、可原子消费；不把一次性token交给模型 |
| 09 | MySQL业务+PG Agent/pgvector | Python持久化与向量检索共用一个PG；避免再引入ES/Milvus |
| 10 | Redis非权威缓存 | Redis故障不能破坏权益或资金不变量 |
| 11 | 模型mock与live双模式 | CI无外部成本；真实评测才能形成模型质量结论 |
| 12 | 框架基线采用Boot4/Cloud2025.1 | 已核实对应SCA发布，替代早期未核对的Boot3建议；补丁T00验证锁定 |
| 13 | 领域Harness作为Agent主线 | LangGraph提供执行/恢复基础；自建上下文、预算、动作ABI、证据验证及会话记录，不自研图引擎 |
| 14 | 回放分严格/历史反事实/合成世界三模式 | 历史日志无法回答未见分支；隔离回放无Java写能力，变体比较记录覆盖率与缺失分支 |

## 5. 同步/异步与隔离

读请求默认连接超时500ms、总超时2s，最多一次带抖动重试（仅幂等读），总预算不超过4s。写调用不能由Feign和业务层同时自动重试。异步操作统一operation_id；消息投递与业务重试分别计数。

Agent单任务模型调用并发有限；Java请求线程不等待完整推理。Agent失效时新工单仍持久化并展示排队，超过10分钟转人工队列；后台恢复不能再覆盖已人工接管的工单。

Sentinel保护内部读依赖（熔断/隔离）；Gateway用Redis令牌桶做跨实例入口限流。两者职责不同。缓存过期的物流不能用于授权，只允许展示并明确时间。

## 6. 部署与资源

Docker Compose base启动MySQL 8.4、PG16+pgvector、Redis7、RocketMQ5、Nacos3、业务服务和stub；observability profile增加OTel Collector、Prometheus、Grafana、Tempo。只对宿主暴露gateway、web和本地监控端口，其余通过Compose网络。

预计开发机需16GB可用内存以上更舒适，实际需求在T00测量；资源紧张时关闭观测profile或仅启动当前切片，不能取消MQ、DB事务等语义。单节点演示不等于高可用集群，压测必须报告副本数和资源限制。

## 7. 框架修订规则

任务允许补充字段、索引、内部帮助类、补丁版本。若需要改变服务归属、数据库、自动执行边界或业务范围，记录现象、证据、备选方案和代价再修订本文及相关契约。禁止通过关掉版本兼容性检查完成T00。
