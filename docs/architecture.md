# 系统架构 · v1.3

按[核心范围](core-scope.md)保留三个Java进程与Python Agent；唯一生产循环由AgentScope驱动。2026-11-02按[服务边界调整](service-boundary-plan.md)拆分商城与售后公共入口，现有依赖锁与退款约束保持。实际验证见[本批报告](../web/checks/service-boundary-20261102.md)，当前进度只看任务账本。

## 1. 部署单元

| 单元 | 所有数据/责任 |
| --- | --- |
| gateway :8080 | 按方法/路径路由、清除客户端伪造身份头；无业务库，业务服务拥有认证/资源授权 |
| case-service :8083 | case_db：工单、材料、政策、方案、审批、授权、进度、Java→Python任务outbox；暂部署账户与媒体能力 |
| commerce-service :8081 | commerce_db：商品、购物车、结算、订单、评价、支付账、退款操作/预留、模拟物流、退款provider适配 |
| agent-service :8090 | AgentScope单Agent；agent_db：run、领域运行快照、模型/工具调用账、上下文、政策索引 |
| provider-stub | 独立持久模拟退款通道，用于丢响应/重启实验；非核心业务微服务 |

Java按api/application/domain/infrastructure分包；共享库不共享Mapper或业务实体，禁止跨库join。Python API与worker共镜像，可分进程运行；同run单执行者。

fulfillment-service原骨架保留但不在核心启动图中。物流模块是明确标注的synthetic外部数据适配，放Commerce内；不实现仓库、库存或补发。

## 2. 调用

- 用户经Gateway按业务直达Commerce或Case。Commerce提供购物/交易/评价/商家商品管理与订单公共接口，自行按资源归属查询；Case提供咨询/售后/账户及媒体接口，按需查询Commerce事实，不跨库读取。
- Commerce通过独立service JWT与identity:resolve scope向暂在Case的账户模块复核用户会话、身份版本、可信绑定及可选本人地址；实时检查失败不回退离线JWT。Case停机时公共目录可读，受保护交易503。旧Case商城门面默认关闭，旧测试显式开启兼容开关。
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

v1.3替换Agent运行实现：AgentScope SDK承担唯一推理—行动循环；自有领域Harness通过受控适配/中间件实现上下文、预算、工具、证据验证与终止，PG RunStore和薄恢复适配承担快照/调用账/fence。SDK状态持久化不能自动替代项目事务语义，AS01须验证公开接口可接入，生产恢复归C09。不套双重循环、不部署AgentScope整套Agent Service，也不构建通用Harness/图平台。完整反事实回放仍退出核心。

## 5. 资源与发布

MySQL8.4、PG16/pgvector、Redis7、RocketMQ5使用现有锁。核心profile不默认启动Nacos或全套观测容器，服务副本默认各1。租约/旧worker测试不代表高可用集群。

保留本地Compose、有限指标、关联日志；资源不足可分切片运行，但集成验收必须使用真实DB/MQ。公网发布、真实支付、云资源购买仍需新授权。
