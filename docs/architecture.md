# 系统架构 · v1.2核心版

按[核心范围](core-scope.md)收缩部署与业务，不更换T00实测版本。

## 1. 部署单元

| 单元 | 所有数据/责任 |
| --- | --- |
| gateway :8080 | 入口路由、JWT验证、入口限流；无业务库 |
| case-service :8083 | case_db：工单、材料、政策、方案、审批、授权、进度、Java→Python任务outbox |
| commerce-service :8081 | commerce_db：订单、支付账、退款操作/预留、模拟物流快照、退款provider适配 |
| agent-service :8090 | agent_db：run、LangGraph checkpoint、模型/工具记录、上下文、政策索引 |
| provider-stub | 独立持久模拟退款通道，用于丢响应/重启实验；非核心业务微服务 |

Java按api/application/domain/infrastructure分包；共享库不共享Mapper或业务实体，禁止跨库join。Python API与worker共镜像，可分进程运行；同run单执行者。

fulfillment-service原骨架保留但不在核心启动图中。物流模块是明确标注的synthetic外部数据适配，放Commerce内；不实现仓库、库存或补发。

## 2. 调用

- 用户经gateway访问Case；订单公共视图由Case调用Commerce，不跨库查询。
- Java内部保留OpenFeign/HTTP受控调用；默认核心profile通过显式地址/Compose DNS寻址。Nacos可选，不是门槛。
- Case→Agent用持久HTTP outbox提交，PG落库后才返回202。
- Agent通过官方MCP SDK stdio适配器访问受scope保护的Java读接口，本地调用政策检索。
- Agent→Case通过PG callback_outbox交付问题/方案/失败，callback_id幂等、revision防旧结果。
- Case→Commerce用RocketMQ退款命令，Commerce→Case用退款结果；各自Outbox/inbox。
- Python不消费MQ；不加Celery、第二套Agent框架或第二种消息中间件。

## 3. 退款边界

Case完成授权消费并在同事务建立固定operation_id与RefundRequested outbox。Commerce消费后在本地事务创建operation、预留金额并占用该订单行；网络调用在事务外。UNKNOWN保持预留，成功/确定失败在Commerce本地事务结算并发结果。

不再跨服务reserve/start/commit/release权益。Case只跟踪目标操作，不能释放Commerce资金。授权消费后不支持输入变更或取消，因此不需要跨服务取消墓碑协议。安全性靠这个业务限制与事务边界，不能保留取消按钮却删协议。

## 4. ADR修订

v1.2替代旧ADR01/04及涉及履约的编排设计：三个Java进程+Python；单退款本地金额预留；以真实消息重复/未知结果展示可靠性。保留领域Harness、结构化规则与检索分离、版本授权、mock/live分开。

不构建通用Harness平台。LangGraph承担图执行/checkpoint，自有代码仅实现本场景上下文、预算、受控工具、证据验证与记录。完整反事实回放退出核心。

## 5. 资源与发布

MySQL8.4、PG16/pgvector、Redis7、RocketMQ5使用现有锁。核心profile不默认启动Nacos或全套观测容器，服务副本默认各1。租约/旧worker测试不代表高可用集群。

保留本地Compose、有限指标、关联日志；资源不足可分切片运行，但集成验收必须使用真实DB/MQ。公网发布、真实支付、云资源购买仍需新授权。
