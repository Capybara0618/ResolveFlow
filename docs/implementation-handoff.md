# 实现模型交接 · v1.2

目标是个人技术展示，不是公司级平台。用户已批准瘦身；请从[核心范围](core-scope.md)、[新任务账本](../tasks/todo.md)继续，不按旧40项计划推进。

## 当前事实

T00–T02有已完成证据，包含锁、骨架、旧协议与测试。C00（核心协议与启动范围迁移）已完成：`contracts/core` 下已有 profile、三个 v2 Schema、三份核心 OpenAPI、正反 fixture 与冻结期望值，Python/Java 两侧核心 DTO 与跨语言字节级一致测试，启动/smoke 已按 core profile 选择。旧资料见tasks/archive，不要重新生成全部项目或删除已有测试。

### 当前可启动的服务（2026-09-19）

`pwsh -File scripts/verify.ps1 -Suite smoke` 默认 `-Profile core`，实际启动并读健康端点：gateway(8080)、commerce-service(8081)、case-service(8083)、agent(8090)。commerce-service 自 C01.2b 起在启动时连接 `commerce_db` 并跑 Flyway 迁移（compose 的 mysql 由 smoke 的 infra-up 先起，本机默认 `commerce/commerce`），所以它现在真的需要一个数据库才能健康。默认**不**启动 `fulfillment-service` 与 Nacos；`-Profile compat` 才加上它们（旧入口与旧断言保留）。证据见 `reports/verify/` 下的两份 smoke 报告。

### 尚未实现（不要读成已有能力）

后端服务基本仍只有骨架与健康接口，外加三处例外：case-service 的 `POST /api/v1/auth/login`（演示账号换 JWT）、`GET /api/v1/orders` 与 `GET /api/v1/orders/{order_id}`（作用域由已校验主体推导，内部调 commerce-service 的 `GET /internal/v1/order-lines`，后者 service token 专用，数据来自 `commerce_db` 的迁移与种子）。核心其余 25 条路由、退款闭环、Agent 调查/政策检索、恢复与回放、实验与主张都未实现；observability 容器尚不存在。`contracts/core` 里的目标协议不代表已在运行。

## 开始步骤

1. 读AGENTS.md、README.md、core-scope、dsh-migration-handoff、tasks/plan和todo。
2. 检查git status与当前实现；并行客户端如仍在改同一文件，先停止冲突编辑并确认交接，不覆盖其工作。
3. C00已完成（协议/profile/DTO/fixture/启动范围），下一项C01；C00之后不回到旧T03扩展，按tasks/todo.md的C01–C13图推进。
4. 只加载当前任务相关专题规格；每子步3–5核心文件，先失败测试、再实现/验证、更新真实记录。

## 不再必做

补发/库存/Fulfillment独立部署、跨动作权益Saga、执行中取消协议、反事实/world回放、完整RAG/上下文消融、完整观测集群。旧T35–T39不自动继续；其核心内容已并入C06–C10/C12。

## 不能简化掉

真实MCP、自主动作、预算/上下文/恢复边界；Java权限、金额、退款幂等、UNKNOWN处理、Outbox/inbox与旧授权拒绝；真实评测分母及严格回放隔离。不用固定工具workflow冒充Agent，不用内存状态冒充恢复。

## 持续推进

普通实现字段/索引/帮助类自行处理；改契约同步类型/fixture/消费者，迁移只追加。重大架构矛盾、外部权限或API预算需要用户决定。无密钥可先mock/独立任务，不声称live完成。

每阶段报告可演示行为、实际命令/测试/报告、失败/未运行、下一步。C05审查退款边界，C09审查恢复，C12审查实验，C13审查简历主张。文档不能替代代码验证。

## 可直接给DSH的指令

> 项目已调整为v1.2个人项目核心版。请先停止按旧T03–T39清单扩展，保存当前进度，不删除现有代码。阅读AGENTS.md、docs/core-scope.md、docs/core-contracts.md、docs/implementation-handoff.md和tasks/todo.md，检查工作区后从C00开始。复用T00–T02成果，保持旧兼容测试，并新增核心协议/profile，不实现延期功能。每次交付一个可验证小步骤，执行相关测试、更新实际记录；不要把目标规格当成已有实现，不启动未经确认的收费评测。
