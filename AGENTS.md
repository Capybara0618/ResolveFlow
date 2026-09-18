# ResolveFlow 实施约定

## 当前目标

框架v1.2，2026-09-18。用户已确认：这是展示个人能力的简历项目，不做公司级平台。保留领域Agent Harness和可靠退款的深度，减少业务宽度与平台配套。T00–T02有完成记录，v1.2代码迁移尚未执行；任务账本优先于旧聊天。

## 开始工作

1. 读README.md、docs/core-scope.md、docs/implementation-handoff.md、docs/dsh-migration-handoff.md、tasks/plan.md、tasks/todo.md。
2. 检查工作区现状与当前实际记录，再读当前任务相关规格/源码/测试；不加载整个旧聊天。
3. 当前从C00开始，复用T00版本锁与T01/T02骨架/契约，不按旧T03–T39推进。
4. 已有客户端可能仍在执行旧计划，发现同文件并行编辑先确认交接，不能覆盖别人的改动。

## 规范权威

范围以docs/core-scope.md为准，业务以product-spec、状态/不变量以domain-model、Agent以agent-harness及agent-spec/context-engineering/trajectory-replay为准。

docs/core-contracts.md是当前目标协议；docs/contracts.md与现有根目录Schema/OpenAPI是T02旧兼容基线。C00创建contracts/core、对应类型/fixture与核心路由覆盖，旧测试保留。不把旧Schema允许的RESHIP当核心可执行权限，也不删除断言来通过迁移。

tasks/todo.md中的C00–C13是当前计划；tasks/archive与旧审阅记录仅为历史，旧T35–T39“全部必做”已撤销，核心部分纳入新任务。规范冲突应指出并解决，不任选方便版本。

## 固定范围与不变量

- 核心为Gateway、Case、Commerce三个Java进程与Python Agent；不默认部署Fulfillment或完整观测集群。
- 只执行单订单行全量模拟退款；不开发补发、库存、跨动作权益Saga或执行中取消。
- 同行最多一次成功退款；订单已退+预留不超过支付额；UNKNOWN不释放、不换ID重付。
- 授权消费前可撤销/更新并使旧revision失效；消费后禁止修改输入和取消。
- Agent无退款、审批、政策修改或跨主体读取权限；模型confidence不是授权。
- Outbox按至少一次；inbox、业务结果和本地事件同事务；外部网络调用不放长事务。
- Java拥有工单/授权/金额，Python拥有run；checkpoint与回调受fence保护。
- 已持久模型结果可复用；未落库响应可能重复计费，不承诺零重复调用。
- 模型按Observation选行动，Harness控制权限/预算/终止，不预设完整工具路径。
- 上下文保留关键事实、来源/版本/冲突，原文与模型推断分开；实际请求可追溯。
- 同run恢复不静默换manifest或重置预算/deadline；strict回放不访问网络/业务写入口，缺记录明确失败。
- 指标必须真实，mock/live/合成数据分开，不宣称商用用户或生产高可用。

## 实施方式

- 按纵向小步，单次通常3–5核心文件；大工作包先拆子步，先关键失败测试再实现。
- 复用Java21/Spring/MyBatis与Python/FastAPI/LangGraph现有锁；不再做无证据的主版本重选。
- 风格/命令见docs/engineering.md；已有verify入口可用，但未来suite/profile未实现不可零步骤报成功。
- 契约、类型、fixture、生产者/消费者同步；迁移只追加，不改已执行迁移。
- 每完成项记录日期、文件、实际命令、测试/报告、失败与未运行；不得只勾任务。
- 保留代码、测试、数据库和用户改动；不清库、删卷、重写历史或擅自推送。
- 不提交密钥，不开未经确认的收费评测、购买资源或公网部署。
- 范围内普通实现自行处理；不默认加多Agent、通用插件平台、反事实world回放、额外MQ或微服务。

## 完成标准

按核心任务及evaluation验收即可完成，不因延期功能阻塞。各阶段报告可演示行为、通过/失败/未运行和下一步。审查重点C05退款、C09恢复、C12实验、C13主张；简历证据以真实实现决定，不以组件数量凑亮点。
