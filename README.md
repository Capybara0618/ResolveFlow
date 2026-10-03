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
| [双端与多人协作方案](docs/product-completion-review.md) | 用户已批准的新五批产品补齐路线 |
| [持久账号与双商家](docs/persistent-identity.md) | 本地演示账号、身份校验与数据兼容 |
| [客户申请工作台](docs/customer-workspace.md) | 本人订单/申请、两轮补证、撤销与公开结果 |
| [浏览器体验指南](docs/browser-experience.md) | 一条命令启动、跨角色操作顺序与可直接查看的结果 |
| [第五批整体验收](reports/product-flow.md) | 正式网页双商家/多人闭环、退款账本、失败及未运行项 |
| [多商家购物设计审查](docs/marketplace-design-review.md) | 平台买家购买多店、商城参照取舍、身份与售后连接及重画清单；新上游尚未实现 |
| [本商家人员管理](docs/staff-management.md) | 管理员新增、维护、启停、角色及密码重置与审计 |
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

脚本会启动隔离的演示数据库和消息设施、三个 Java 服务、DeepSeek 调查服务和桌面前端，并在默认浏览器打开 `http://127.0.0.1:5174`。登录账号是 `demo-reviewer`，密码是 `demo-pass-1003`。第一次启动需要构建服务，耗时会长一些；保持服务运行时再次执行会直接复用并打开页面。

商家管理员使用 `demo-admin` / `demo-pass-1100`，在“商家概览”查看本商家真实待办与异常，进入工单协调；“人员管理”维护账号，“政策与版本”只读已导入原文、有效区间和真实索引状态。人员维护不会自动转移工单，转交或接管在工单中明确操作。管理员只能管理自己的商家，并且不能停用或降级最后一个启用管理员。仅查看已有结果可用`.\demo.ps1`，不加`-Live`时不启动新模型调查。

客户工作台使用 `demo-customer` / `demo-pass-1001`，从“我的订单”发起申请，在“我的申请”查看进度、回答当前问题或撤销。客户和专员可分别登录两个浏览器标签页，模拟申请与审核；各标签的会话相互独立，刷新后需重新登录。已有3条新合成闭环及桌面截图见[客户验收记录](reports/customer-workspace.md)，更多不同商家/客户账号见上方持久账号说明。

专员使用公共队列、我的工单、结果待确认与历史工单入口；可见且空闲的队列每30秒更新，客户申请列表每15秒更新。已展开多页的列表保留原记录并提示刷新，更新不会切换当前工单或清除填写中的材料。第四批界面与只读验收见[商家工作台报告](reports/merchant-workspace.md)；第五批已完成正式网页双商家/多人、补证核验、冲突及人工审批闭环：三笔329元模拟退款、一拒绝、一撤销，见[整体验收](reports/product-flow.md)。从启动到跨角色操作的详细步骤见[浏览器指南](docs/browser-experience.md)。

`-Live` 使用用户环境变量 `Deepseek_API_KEY`，固定连接官方 `https://api.deepseek.com/chat/completions`，模型 ID 为 `deepseek-flash`（V4.1 Flash）。密钥不写入项目文件。新增材料、核验或补证回答会触发真实调查并产生模型用量；审批后执行的是模拟退款。仅浏览历史数据可用 `.\demo.ps1`，此模式关闭新调查，仍可查看已有记录和退款执行结果。

```powershell
.\demo.ps1 status       # 查看状态
.\demo.ps1 stop         # 停止演示服务，保留演示数据
.\demo.ps1 -Live -SkipBuild   # 服务停止后复用已有 jar，快速重启
.\demo.ps1 -Live -NoBrowser   # 只启动，不自动打开浏览器
```

完整隔离方式、演示样本与验收结果见[审查员演示说明](reports/reviewer-demo/README.md)。
审查侧真实模型与浏览器验收见[收尾记录](reports/reviewer-completion.md)，包含成功和失败记录，以及可直接查询的工单编号。

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
