# ResolveFlow · 智能售后决策与执行平台

> 当前阶段：框架文档 v1.1（Harness深化），2026-09-15。尚未实现业务代码，尚无性能、准确率或可靠性实测结果。

面向 Java 后端、Agent 开发和 AI 应用开发岗位的个人工程项目。消费者提交售后诉求，Python Agent 自主调查业务证据、检索适用政策并提出方案；Java 微服务校验方案、处理审批，可靠执行模拟退款或补发。

目标是用可运行代码、故障实验和可复现评测形成简历证据。数据与商家政策均为明确标识的合成样例，不接真实支付，不宣称商业流量或真实客户。

## 阅读入口

| 文件 | 回答的问题 |
| --- | --- |
| [项目规格](docs/product-spec.md) | 做什么、用户是谁、业务范围、完成标准 |
| [架构决策](docs/architecture.md) | 服务拆分、调用方式、存储、技术取舍 |
| [领域与数据模型](docs/domain-model.md) | 状态、表、约束、资金及商品权益 |
| [Agent规格](docs/agent-spec.md) | Agent如何取证、追问、恢复与结束 |
| [Harness核心架构](docs/agent-harness.md) | 模型与运行层如何分工，模块接口、动作与预算如何约束 |
| [上下文工程](docs/context-engineering.md) | 每步看什么，关键证据如何保留，长轨迹如何按需读取 |
| [轨迹回放](docs/trajectory-replay.md) | 如何复现失败、比较变体，为什么历史日志不能回答所有新分支 |
| [接口与事件契约](docs/contracts.md) | Java/Python如何协作，消息和接口有哪些 |
| [可靠性与安全](docs/reliability-security.md) | 重复退款、未知结果、过期审批、故障如何处理 |
| [政策与检索](docs/policy-rag.md) | 政策时间语义、结构化规则、检索评测 |
| [验证与实验](docs/evaluation.md) | 如何证明有效，如何防止指标失真 |
| [工程与运行规范](docs/engineering.md) | 目录、命令、代码规范、CI和部署 |
| [依赖与来源](docs/stack-and-sources.md) | 版本线、首轮兼容性关卡、官方资料 |
| [简历证据映射](docs/resume-evidence.md) | 技术点必须提供哪些实验证据 |
| [实施计划](tasks/plan.md) | 阶段、顺序、里程碑 |
| [任务清单](tasks/todo.md) | 每项任务的验收、验证和依赖 |
| [后续模型交接](docs/implementation-handoff.md) | 从哪里开始、怎样持续推进与报告 |
| [框架审阅记录](docs/framework-review.md) | 本轮验证了什么、实施阶段还要验证什么 |

## 框架的固定边界

- Java：Gateway、Commerce、Fulfillment、Case 四个进程；Python：Agent 一个服务（API与worker可使用同镜像分别启动）。
- 一张售后单处理一个订单行的全部购买数量；一个订单行最多成功获得一次退款或补发。
- Agent只读业务数据、提出方案；授权、金额、权益占用和写操作由Java负责。
- 单Agent动态决策，由领域Harness提供上下文工程、受控工具执行、持久恢复、版本化轨迹和隔离回放；不以固定业务工具链冒充自主调查。
- MySQL保存业务事实；PostgreSQL保存Agent状态与政策索引；Redis用于缓存、限流和短期协调；RocketMQ用于Java业务事件。
- 真实模型模式用于Agent效果评测；确定性模拟模型用于离线CI和故障测试，两类结果分别报告。
- 本轮仅确定框架。后续实现从T00开始；基础设施补丁版本在T00用实际兼容性测试锁定。

## 推荐下一条实施指令

阅读 AGENTS.md、docs/implementation-handoff.md 和 tasks/todo.md，从 T00 开始按依赖逐项实施。遵循已确定的服务边界和数据不变量；先完成版本兼容性验证，再交付第一条端到端业务链路。每项任务提供测试证据并更新进度。遇到重大架构冲突先提交有证据的修订建议，常规实施细节自行处理。
