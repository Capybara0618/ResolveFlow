# ResolveFlow · 售后调查与退款Agent

> 2026-09-28：用户主导后续改进，停止旧 CXX 计划并取消 C12。当前执行仓库 `docs/reviewer-optimization.md`；下文旧任务顺序和实验规模仅作历史参考，领域不变量继续生效。

> 框架文档v1.3，业务范围仍为v1.2个人项目核心版。AgentScope 2.0.8已接入；当前进度以[账本顶部](tasks/todo.md)为准，下一步统一读[当前交接](tasks/handoff-current.md)。规格、组件测试、真实模型与端到端验收分别记录，不把目标当成果。

面向Agent开发、AI应用开发与Java后端实习的个人技术展示项目。主链路：自主调查订单/物流与政策 → 补证或人工审批 → Java可靠执行模拟退款 → 查看轨迹及结果。

重点做深领域Harness与可靠退款，不做公司级售后平台。合成数据和模拟支付明确标记；无商用流量、高可用集群或效果提升承诺。

## 当前实施入口

| 文件 | 用途 |
| --- | --- |
| [核心范围](docs/core-scope.md) | 哪些必做、哪些退出核心、怎样算完成 |
| [当前交接](tasks/handoff-current.md) | 当前任务、验收顺序与接管规则 |
| [三角色商家工作台](docs/merchant-role-merge.md) | 当前14账号、统一商家工作台与自动归属 |
| [双端与多人协作方案](docs/product-completion-review.md) | 历史五批路线；当前角色以三角色规格为准 |
| [干净演示基础管理](docs/demo-foundation.md) | 三店/30商品/45SKU基础管理；当前14账号见三角色规格 |
| [当前体验指南](docs/clean-demo-experience.md) | 新账号、从购物到退款、基础管理及重建 |
| [持久账号与双商家](docs/persistent-identity.md) | 历史身份实施与数据兼容 |
| [客户申请工作台](docs/customer-workspace.md) | 本人订单/申请、两轮补证、撤销与公开结果 |
| [浏览器体验指南](docs/browser-experience.md) | 一条命令启动、跨角色操作顺序与可直接查看的结果 |
| [第五批整体验收](reports/product-flow.md) | 正式网页双商家/多人闭环、退款账本、失败及未运行项 |
| [多商家购物设计审查](docs/marketplace-design-review.md) | 平台买家购买多店、商城参照取舍、身份与售后连接；实现按下方新路线推进 |
| [多商家实施对应](docs/marketplace-implementation.md) | 沿目标图册按身份、商品、支付、购物车/多行、履约和整体验收推进 |
| [商品目录与直接购买](docs/catalog-checkout.md) | 公共两店目录、规格/数量、服务端报价及独立待付款草稿 |
| [模拟付款与本人订单](docs/simulated-checkout-payment.md) | 原尝试恢复、取消/到期、新旧跨店本人订单与售后入口；验证见[第三批报告](reports/checkout-payment.md) |
| [购物车与多行结算规格](docs/cart-multiline-checkout.md) | 第四批按店持久购物车/多商品结算已完成；[集中报告](reports/cart-checkout.md)，[资金前置](reports/multiline-refunds.md) |
| [商城到售后整体验收](reports/marketplace-flow.md) | 六批范围已贯通；同一买家两店购物、逐行独立退款、补证核验后新建议与撤销，67项HTTP/151项前端；mock与Live边界分开 |
| [平台买家](docs/platform-buyer.md) | 同一登录的跨店本人订单/申请与原有售后，旧客户及商家权限保留 |
| [多商家购物预期图册](docs/ui-marketplace-v1/index.html) | 11个页面视图与2张状态板，可切换/放大；配套图文合同，非当前运行截图 |
| [本商家人员管理](docs/staff-management.md) | 历史多人兼容；当前单账号商家不开放此入口 |
| [AgentScope迁移规格](docs/agentscope-migration.md) | 框架边界、恢复要求及历史迁移过程 |
| [执行账本](tasks/todo.md) | 用户最新路线、实际进度及历史成果 |
| [实现交接](docs/implementation-handoff.md) | 模型如何继续、不能走哪些捷径 |
| [DSH执行手册](tasks/dsh-reviewer/README.md) | 审查员剩余四批的详细步骤、验收与跨客户端边界 |

从当前账本顶部接续；C08–C10的已验证成果不重做，不继续旧T03–T39。旧任务记录在[归档](tasks/archive/v1.1-todo.md)，仅作历史。

## 浏览器体验

启动 Docker Desktop 后，在项目根目录打开 PowerShell，输入一条命令：

```powershell
.\demo.ps1 -Live
```

脚本启动隔离演示设施、三个Java服务、DeepSeek调查服务和桌面前端，打开[浏览器商城](http://127.0.0.1:5174/#/shop)。首次构建较慢；普通启动保留数据，不重复初始化。

当前基础环境为三家店、30种商品、45个SKU、14个账号。演示密码统一 **123456**：买家`buyer01`–`buyer10`，商家`admin01`–`admin03`，平台管理员`platform`。松间数码使用admin01，拾光家居使用admin02，轻行户外使用admin03。同一商家账号管理商品、订单及人工售后审批，新申请自动归属；staff01–staff06已取消。角色转换保留数据，当前有三笔明确标注的退款验收记录，详见[三角色规格](docs/merchant-role-merge.md)与[报告](reports/merchant-role-merge.md)。

用buyer01购物、按店结算并模拟付款，从本人订单行申请退款；另开标签用对应商家的账号进入“售后工单”，阅读原始信息、Agent建议和政策后直接人工审批。商家使用同一账号管理商品、订单和售后；platform负责商家开通/启停和买家维护，没有业务审批权限。三店政策已导入并建立索引，新店政策需受控准备。

`-Live`使用用户环境变量`Deepseek_API_KEY`，沿用项目当前DeepSeek配置，新增申请/材料会产生真实模型调用。仅体验购物和基础管理用`.\demo.ps1`即可，此模式的新调查排队。此次基础能力集中验收使用mock决策与真实HTTP/数据库/政策检索，未启收费Live。模拟付款、发货和退款均无真实资金。

```powershell
.\demo.ps1 status
.\demo.ps1 stop                       # 停服务，保留数据
.\demo.ps1 -Live -SkipBuild            # 已构建且Java源码未变
.\demo.ps1 reset -ClearDemoData        # 明确放弃本地演示数据时才用；先备份
```

完整账号、购买到退款步骤、基础管理与重建说明见[干净环境体验指南](docs/clean-demo-experience.md)，当前规格见[基础管理](docs/demo-foundation.md)。2026-10-03用户授权清除隔离演示记录并重建基础数据；旧demo-*账号、旧报告订单和工单ID不属于当前环境。共享开发库、Git和历史验收报告保留；历史真实模型与页面证据见[审查侧报告](reports/reviewer-completion.md)和[商城到售后报告](reports/marketplace-flow.md)。

本地 core profile 先运行 `java/mvnw -f java/pom.xml -DskipTests package`，再运行 `docker compose -f infra/compose.yaml --profile core up --build -d mysql postgres redis agent commerce-service case-service gateway`，最后用 `python scripts/c11_core_smoke.py` 检查健康、认证及商家队列隔离。镜像包含公开的合成契约夹具用于本地演示；真实环境须覆盖演示密钥。该 profile 默认不开收费模型调查和 MQ 传输循环；功能链路验收以对应 C08 报告为准。`docker compose -f infra/compose.yaml --profile core stop gateway case-service commerce-service agent` 只停应用，不清数据卷。

工作台另用 `pnpm --dir web install --frozen-lockfile`、`pnpm --dir web dev` 启动；Vite 将 `/api` 转到本机 Gateway。演示账号见[工程说明](docs/engineering.md)。

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
| [版本依据](docs/stack-and-sources.md) | 非Agent框架复用实际锁；AgentScope先验证后锁定 |
| [简历证据](docs/resume-evidence.md) | 7个候选亮点方向，按实际结果取舍 |
| [实施计划](tasks/plan.md) | 垂直切片与依赖 |
| [修订检查](docs/framework-review.md) | 历史与本轮检查边界 |

## 边界

Java负责业务权限/金额/审批与执行；Agent只读调查和提出方案。模型根据Observation选下一行动，不固定全量工具链。退款UNKNOWN保持占用并对账；同订单行至多一次成功退款。

保留微服务、MySQL、PG/pgvector、Redis、RocketMQ既有架构和锁。Agent目标为AgentScope SDK+领域Harness+PG运行记录，LangGraph旧锁/试验只作迁移基线。Fulfillment/补发/库存、反事实回放、全量消融及完整观测平台不在核心；旧资产保留，C00已完成core启动选择。

不根据文件数量或组件数量判断完成。核心版应有可运行演示、真实报告、可解释取舍与失败案例。
