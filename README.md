# ResolveFlow · 售后调查与退款Agent

> 当前框架：v1.2个人项目核心版，2026-09-18。T00–T02有历史完成证据；核心业务与v1.2迁移仍待实施，不能把规划当成果。

面向Agent开发、AI应用开发与Java后端实习的个人技术展示项目。主链路：自主调查订单/物流与政策 → 补证或人工审批 → Java可靠执行模拟退款 → 查看轨迹及结果。

重点做深领域Harness与可靠退款，不做公司级售后平台。合成数据和模拟支付明确标记；无商用流量、高可用集群或效果提升承诺。

## 先读这四份

| 文件 | 用途 |
| --- | --- |
| [核心范围](docs/core-scope.md) | 哪些必做、哪些退出核心、怎样算完成 |
| [执行账本](tasks/todo.md) | 历史成果、新C00–C13任务与实际进度 |
| [实现交接](docs/implementation-handoff.md) | 模型如何继续、不能走哪些捷径 |
| [DSH交接](docs/dsh-migration-handoff.md) | 跨客户端断点与旧会话边界 |

下一项是C00：在已有成果上迁移核心协议/profile，不重做T00，不继续旧T03–T39。旧任务记录在[归档](tasks/archive/v1.1-todo.md)，仅作历史。

## 设计索引

| 文件 | 内容 |
| --- | --- |
| [业务规格](docs/product-spec.md) | 物流/损坏退款、追问/审批、执行中不取消 |
| [架构](docs/architecture.md) | Gateway+Case+Commerce+Python Agent |
| [领域状态](docs/domain-model.md) | 金额预留、退款幂等、版本与状态不变量 |
| [核心契约目标](docs/core-contracts.md) | C00要落实的core协议，与旧基线分离 |
| [旧协议基线](docs/contracts.md) | 已有T02测试解析的v1全集，不是必做范围 |
| [Agent规格](docs/agent-spec.md) | 5个MCP工具、动态动作、预算与恢复 |
| [Harness](docs/agent-harness.md) | 运行层模块、上下文、控制与验证 |
| [上下文](docs/context-engineering.md) | 关键事实保真、裁剪与按需读回 |
| [严格回放](docs/trajectory-replay.md) | 选定完整轨迹离线复现，不做反事实平台 |
| [可靠性](docs/reliability-security.md) | 消息、UNKNOWN、权限与事务边界 |
| [政策检索](docs/policy-rag.md) | dense+BM25基线、硬过滤与引用 |
| [验证计划](docs/evaluation.md) | 小规模真实对照、核心故障、性能与演示 |
| [工程命令](docs/engineering.md) | 现有入口与未实现目标入口分开 |
| [版本依据](docs/stack-and-sources.md) | 复用实际锁，不重新大规模选型 |
| [简历证据](docs/resume-evidence.md) | 7个候选亮点方向，按实际结果取舍 |
| [实施计划](tasks/plan.md) | 垂直切片与依赖 |
| [修订检查](docs/framework-review.md) | 历史与本轮检查边界 |

## 边界

Java负责业务权限/金额/审批与执行；Agent只读调查和提出方案。模型根据Observation选下一行动，不固定全量工具链。退款UNKNOWN保持占用并对账；同订单行至多一次成功退款。

保留微服务、MySQL、PG/pgvector、Redis、RocketMQ和LangGraph现有版本锁。Fulfillment/补发/库存、反事实回放、全量消融及完整观测平台退出核心；旧代码不删除，默认部署的实际切换待C00。

不根据文件数量或组件数量判断完成。核心版应有可运行演示、真实报告、可解释取舍与失败案例。
