# 可执行任务清单

初始状态：全部40个工作包待实施。每个T下的小步骤依次完成；验收通过后才勾选。命令入口在T01建立，之后所有验证均应返回真实结果。v1.1新增T35–T39，按依赖插入，不等T34结束才开始。

进度：T00 已完成（2026-09-15，实测 38 个测试通过）。T01 已完成（2026-09-17，`verify --suite all-offline` 14/14，27 个测试通过）。下一项为 T02。

## P0 基础

### T00 依赖兼容与版本锁

- [x] T00.1：按stack-and-sources建立最小Java兼容试验，验证Boot/Cloud/SCA、MySQL事务、MQ收发。
- [x] T00.2：验证Python PG checkpointer、MCP stdio和跨语言JSON；锁全部版本/digest。
- 依赖：无。文件：spikes/compatibility/*、infra/versions.lock.yaml、docs/compatibility-report.md（待创建）。
- 验收：无跳过兼容检查、无SNAPSHOT；报告列出实际运行版本与结果，失败有复现。
- 验证：最小Java集成测试、Python保存/恢复测试、一次真实MCP调用；通过后进入G0。
- 实际记录：
  - 日期：2026-09-15。状态：**完成**，G0 两条硬性要求由 Maven Enforcer 机器校验通过。
  - 修改文件：
    - `spikes/compatibility/java-spike/`（父 POM + `spike-service` + `spike-gateway`；含 Enforcer 守卫、Flyway 迁移、EntitlementService/Mapper、`PayloadHash`）
    - `spikes/compatibility/java-spike/spike-service/src/test/java/.../{MySQLTransactionIT,RocketMqIT,SentinelIT,CrossLanguageHashIT}.java`
    - `spikes/compatibility/infra/spike-compose.yaml`、`spikes/compatibility/infra/rocketmq/broker.conf`
    - `spikes/compatibility/python-spike/`（`pyproject.toml`、`uv.lock`、`src/spike_py/{canonical,mcp_server}.py`、`tests/{test_canonical,test_checkpointer,test_mcp_stdio}.py`）
    - `spikes/compatibility/web-spike/`（Vue3+TS+Vite 最小工程 + `pnpm-lock.yaml`）
    - `spikes/compatibility/contracts/cross-language-hash-{inputs,expected}.json`
    - `infra/versions.lock.yaml`（新建）、`docs/compatibility-report.md`（新建）
    - `reports/t00-compatibility/`（原始日志 7 份 + `EVIDENCE-SUMMARY.md` + `compose-status.txt`）
  - 实际执行命令：
    - `docker compose -f spikes/compatibility/infra/spike-compose.yaml up -d`
    - `mvn -B -ntp validate`（Enforcer）、`mvn -B -ntp test`（Java 全量）
    - `java -jar spike-service-0.0.1-SPIKE.jar --spring.profiles.active=nacos` 与 gateway 同跑，curl 验证路由/发现/配置/Feign
    - `uv lock`；`uv sync --frozen`；`uv run --frozen pytest tests/ -v`
    - `pnpm install --frozen-lockfile`；`pnpm build`
  - 测试结果：
    - Java **20/20 通过**（MySQLTransactionIT 9、CrossLanguageHashIT 6、SentinelIT 3、RocketMqIT 2），BUILD SUCCESS
    - Python **18/18 通过**（canonical 10、checkpointer 5、mcp_stdio 3）
    - 前端 `vue-tsc --noEmit && vite build` 通过，产出 `dist/`（61.87 kB js）
    - Enforcer 4 条规则全部 passed
    - 全部跑在真实容器上：MySQL 8.4、PostgreSQL 16 + pgvector、RocketMQ 5.3.3、Nacos 3.1.0；无 mock 替代
  - 锁定结果：Boot 4.0.8 / Cloud 2025.1.3 / SCA 2025.1.0.0 / MyBatis starter 4.1.0 / Flyway 11.14.1 / RocketMQ client 5.3.1（classic）/ Testcontainers 2.0.5 / LangGraph 1.2.11 / checkpointer-postgres 3.1.2 / MCP SDK 2.2.0；6 个镜像全部按 digest 固定。明细见 `infra/versions.lock.yaml`。
  - 报告路径：`docs/compatibility-report.md`
  - 未决项：
    1. `docs/stack-and-sources.md:12` 的"RocketMQ starter"表述与事实不符（该坐标不存在），建议修订；本次已按用户确认改用 classic 客户端直连。
    2. `docs/stack-and-sources.md:13` 未点名 Gateway 坐标，Cloud 2025.1 已改名为 `spring-cloud-starter-gateway-server-webflux`，建议补上。
    3. RocketMQ client 版本：SCA 管理 5.3.1，社区最新 5.5.1；本次以 BOM 一致性优先，若后续需要 5.5.x 需重新验证。
    4. Nacos 客户端 3.1.1 与服务端 3.1.0 **无官方书面兼容矩阵**，本次仅实测可用（注册/发现/配置导入通过），结论限于实测范围。
    5. `spikes/` 为临时工程，待 T01 建立正式骨架后按需清理，未擅自删除。
    6. Docker Hub 在本网络 DNS 被污染，走镜像源 + digest 固定；CI 需另配可达镜像源。
  - 未运行项（不得视为通过）：Redis Lua 限流（T27）、OTLP 链路（T26）、live 模型调用与效果（未配置 API/预算）、embedding revision 与 pgvector 维度过滤（T19）、故障/性能/RAG 实验（T29/T30）、CI（T01/T32）。

### T01 工程与命令入口

- [x] T01.1：Maven模块、Python包、共享fixture布局、服务健康接口。
- [x] T01.2：Compose基础设施与doctor/verify入口，建立最小CI。
- 依赖：T00。文件：java/pom.xml与模块构建文件、agent/pyproject.toml、infra/compose.yaml、scripts/*；按模块分批。
- 验收：每个服务可单独构建；命令找不到依赖时清晰失败；app启动能读健康状态。
- 验证：doctor、Java test、Python unit、Compose配置检查和smoke。
- 实际记录：
  - 日期：2026-09-16/17。状态：**完成**，`verify --suite all-offline` 14/14 步通过。
  - 修改文件：
    - `java/`：父 `pom.xml`（自 T00 继承全部版本锁与 Enforcer 守卫，另加 Spotless 与 integration profile）、`mvnw`/`mvnw.cmd`/`.mvn/`、`shared-kernel/`（`ApiError` 错误协议 + 5 个测试）、`gateway/`、`commerce-service/`、`fulfillment-service/`、`case-service/`（各含 pom、Application、application.yml、健康测试）
    - `agent/`：`pyproject.toml`、`uv.lock`、`src/resolveflow/{__init__,api/{__init__,app},runtime,harness,tools,policies,callbacks}`、`tests/{unit,integration}`（5 个测试）
    - `web/`：`package.json`、`vite.config.ts`、`tsconfig.json`、`index.html`、`src/{main.ts,App.vue,money.ts,env.d.ts}`、`tests/{money,app}.spec.ts`（9 个测试）、`pnpm-lock.yaml`
    - `infra/`：`compose.yaml`、`.env.example`、`mysql/init/01-databases.sql`、`postgres/init/01-extensions.sql`、`rocketmq/{broker.conf,broker-entrypoint.sh}`（`versions.lock.yaml` 属 T00）
    - `scripts/`：`doctor.ps1`、`doctor.sh`、`verify.ps1`、`verify.sh`
    - `.github/workflows/ci.yml`
    - 目录占位：`fixtures/{business,policies,provider}`、`contracts/fixtures`、`evals/{datasets,baselines,runner,metrics,replay,variants}`、`tests/{system,faults,performance}`（各带 README 说明归属任务）
  - 实际执行命令：
    - `java/mvnw -f java/pom.xml -B test`；`mvnw -pl <module> -am test`；`mvnw verify -Pintegration`
    - `uv lock --project agent`；`uv sync --project agent --frozen --all-extras`；`uv run --project agent --frozen pytest agent/tests/unit`
    - `pnpm --dir web install`；`pnpm --dir web test`；`pnpm --dir web build`
    - `docker compose -f infra/compose.yaml up -d`
    - `bash scripts/doctor.sh`；`powershell -File scripts/doctor.ps1`
    - `bash scripts/verify.sh --suite all-offline`（最终一次 EXIT=0）
  - 测试结果（最终 all-offline，14/14 通过）：
    - java-spotless PASS、python-ruff PASS、python-mypy PASS、web-typecheck PASS
    - java-unit PASS（13 个测试：shared-kernel 5 + 4 服务 × 2）、python-unit PASS（5）、web-test PASS（9）
    - infra-up PASS、package PASS、smoke ×5 PASS（gateway / commerce / fulfillment / case / agent 均启动并读到健康）
    - 合计 **27 个测试**；报告：`reports/verify/20260917-*-all-offline.txt`
  - 实测确认的关键点：
    - MySQL 初始化建出 commerce_db / fulfillment_db / case_db，三个账号各自只有本库权限；实测 `commerce` 读 `case_db.orders` 返回 **ERROR 1142 拒绝**——数据归属边界是被强制的，不只是约定。
    - PostgreSQL 16.15 + pgvector 0.8.6 就位。
    - RocketMQ broker 以 `127.0.0.1:10911` 注册（宿主机可达）。
    - verify 入口三态明确：已实现 suite 执行、延后 suite 退出 2、未知 suite 退出 64，均不会零步骤报成功。
  - 未决项（前两项已于 2026-09-18 处理）：
    1. ~~基础服务命令含 `provider-stub` 必然失败~~ **已处理**：`docs/engineering.md` 表格中 4 类"尚未可执行"的命令加了 ※ 标记，并在表下集中说明归属任务——`provider-stub`（T12）、`--profile app`（T32 前为空操作）、`scripts/replay.ps1`（T38）、各 `-Suite` 子命令。特别写明**不要为让命令通过而放不实现协议的空占位 stub**。实测标注后的表格结构完好（27 行、管道符一致）。
    2. ~~本机没有 pwsh~~ **已处理**：经 winget 安装 PowerShell **7.6.6**（用户级，位于 `%LOCALAPPDATA%\Microsoft\WindowsApps\pwsh.exe`）。用 pwsh 7 复跑并验证：`doctor` suite PASS、`format` suite 4/4 PASS、`unit` suite 3/3 PASS、未知 suite 退出 64、延后 suite 退出 2。`docs/engineering.md:36` 的 `pwsh -File ...` 现在可直接执行。两个 .ps1 同时兼容 Windows PowerShell 5.1（需 UTF-8 BOM）。
    3. **"每个服务可单独构建"需带 `-am`**：`mvnw -pl case-service test` 在干净本地仓库下失败（shared-kernel 是 reactor SNAPSHOT），`-pl case-service -am test` 成功。已在 `java/pom.xml` 注释写明，失败信息明确。
    4. Docker Desktop 在本机反复自行停止（内存紧张：15.3 GB 总量、空闲一度 0.5 GB），期间 `infra-up` 会失败；这是环境问题不是代码问题，doctor 已能报告。用户确认由其手动启动。
    5. `app` / `observability` profile 与 provider-stub 一样留待后续任务；`--profile app` 目前是 no-op（compose 不虚构不存在的服务），已在 engineering.md 说明。
    6. 审计中一条 nit 称 `ApiError` 使用了 Jackson 2 注解搭配 Jackson 3 运行时——**该结论不成立**：Jackson 3 的 POM 明确注明注解仍留在 Jackson 2.x groupId，实测序列化正常，已驳回。
  - 未运行项（不得视为通过）：contracts / system / faults / performance / agent-eval / rag-eval / harness / harness-eval 全部未实现（各自的 verify 调用返回 exit 2 并说明归属任务）；Redis Lua 限流（T27）、OTLP（T26）、live 评测（未配置 API 与预算）。

### T02 契约固化与跨语言fixture

- [ ] T02.1：生成4份OpenAPI、DTO/Pydantic与正确/错误fixture。
- [ ] T02.2：固定规范化hash、事件签名字段和enum映射。
- 依赖：T01。文件：contracts/openapi-*.yaml、contracts/fixtures/*、对应契约测试。
- 验收：所有contracts.md端点覆盖；未知字段、负金额、错action/target组合被拒绝。
- 验证：verify -Suite contracts；Java/Python对同一fixture产生相同hash。
- 实际记录：未执行。

### T03 身份、网关与资源授权

- [ ] T03.1：演示用户登录、JWT签发/验证、商家与用户范围。
- [ ] T03.2：网关剥离伪造头，资源服务独立校验service scope。
- 依赖：T02。文件：gateway安全配置、case身份模块、shared安全库、授权集成测试。
- 验收：合法请求可达；跨用户/商家、过期token、错误aud拒绝；不信任前端role。
- 验证：JWT单元+双商家越权集成测试。
- 实际记录：未执行。

## P1 业务与决策

### T04 订单与支付事实读取

- [ ] 建立commerce迁移/种子/Repository/API，固定行实付金额与支付时间。
- 依赖：T03。文件：commerce migration、order domain、repository、controller及测试。
- 验收：整数金额、订单归属及版本正确，空库迁移可重复启动。
- 验证：MySQL Testcontainers + order context契约测试。
- 实际记录：未执行。

### T05 物流、仓库证据读取

- [ ] 建立shipment/轨迹/packing模型、版本化种子与只读API。
- 依赖：T03。文件：fulfillment migration、evidence domain/repository/controller/tests。
- 验收：缺少仓库记录与“确认无差异”区分；迟到轨迹不覆盖新状态。
- 验证：版本乱序和SC-L/SC-W evidence fixtures。
- 实际记录：未执行。

### T06 创建工单、材料与状态机

- [ ] T06.1：创建工单、active slot、幂等与timeline。
- [ ] T06.2：补充材料revision、撤销、超时转人工。
- 依赖：T04,T05。文件：case domain/application/api/migration及状态测试。
- 验收：一个line一个活跃case；相同key换body409；旧版本修改失败。
- 验证：状态表所有合法/非法边、并发建单、可注入Clock测试。
- 实际记录：未执行。

### T07 政策原件、结构化规则与版本

- [ ] T07.1：导入/发布/撤销、区间冲突锁、不可变bundle。
- [ ] T07.2：三场景政策与合同时间选择、safety_epoch。
- 依赖：T06。文件：case policy模块、迁移、fixtures/policies、policy tests。
- 验收：旧订单不会用新政策；多版本冲突拒绝发布；正文规则一致性检查。
- 验证：边界时间、撤销、跨商家、并发发布测试。
- 实际记录：未执行。

### T08 Java方案校验与风险路由

- [ ] 实现Schema引用验证、权威事实校验、金额重算、AUTO/REVIEW/NEED_INFO/BLOCK。
- 依赖：T07。文件：case decision domain/application、fixtures、tests。
- 验收：缺证/用户单方陈述不自动退款；200元阈值边界正确；confidence无授权作用。
- 验证：产品规则表驱动测试、伪造引用和建议金额不符测试。
- 实际记录：未执行。

### T09 版本化审批与授权消费

- [ ] T09.1：人工方案、批准/驳回/请求信息、expiry。
- [ ] T09.2：授权消费CAS+唯一operation、输入更新/撤销竞争。
- 依赖：T08。文件：case authorization/approval/application/migration/tests。
- 验收：过期或换payload不能执行；批准与撤销有可解释线性化点。
- 验证：并发双审批、修改材料与消费竞态；G1。
- 实际记录：未执行。

## P2 可靠退款

### T10 Outbox/inbox基础设施

- [ ] T10.1：MySQL本地事件、dispatcher租约、MQ持久投递。
- [ ] T10.2：inbox事务去重、毒消息与DLQ/重驱。
- 依赖：T02,T06。文件：shared messaging、各service迁移、MQ集成测试。
- 验收：F01–F03正常恢复，broker ACK不等价业务成功。
- 验证：真实RocketMQ容器重复/崩溃测试。
- 实际记录：未执行。

### T11 权益与金额预留

- [ ] T11.1：reserve/start/commit/release API及状态约束。
- [ ] T11.2：退款/补发互斥、订单账条件UPDATE、不同operation冲突。
- 依赖：T04,T10。文件：commerce entitlement/ledger/application/migration/tests。
- 验收：INV-01/02/03及IN_USE不能超时释放；重复请求同结果。
- 验证：100并发同line、多行共订单余额、start/release竞态。
- 实际记录：未执行。

### T12 持久provider模拟器

- [ ] 实现SQLite持久退款/运单API、幂等键、GET状态与注入点。
- 依赖：T02。文件：fixtures/provider应用/容器/协议/tests。
- 验收：成功后丢响应、重启保留结果、相同key不同金额409。
- 验证：provider协议测试与进程重启实验。
- 实际记录：未执行。

### T13 退款目标服务

- [ ] T13.1：消费命令、操作持久化、start权益、provider调用。
- [ ] T13.2：成功/失败/UNKNOWN账务与结果事件。
- 依赖：T10,T11,T12。文件：commerce refund worker/application/repository/tests。
- 验收：网络调用在事务外；未知不释放；成功一次记账。
- 验证：F04/F05及重复命令集成测试。
- 实际记录：未执行。

### T14 case执行编排与退款闭环

- [ ] T14.1：授权消费后reserve/dispatch，持久编排步骤。
- [ ] T14.2：结果投影、权威查询、收敛与timeline。
- 依赖：T09,T13。文件：case orchestration/results/query/tests。
- 验收：从人工/低风险方案到退款成功，重启不丢操作。
- 验证：verify -Suite system -Case refund；G2并记录首条可演示链路。
- 实际记录：未执行。

## P3 补发与恢复

### T15 补发库存与Saga

- [ ] T15.1：库存条件预留、补发操作、承运商交互。
- [ ] T15.2：正向commit与确定失败补偿，复用case编排。
- 依赖：T14,T05。文件：fulfillment inventory/reship、case action adapter、tests。
- 验收：不足库存不负数；发货成功后不能释放已用库存。
- 验证：F06/F07/F08。
- 实际记录：未执行。

### T16 取消墓碑、启动竞态与对账

- [ ] T16.1：目标cancel-before-start与STARTING保护。
- [ ] T16.2：UNKNOWN扫描、操作台reconcile端点、原ID重驱。
- 依赖：T15。文件：target operation state、case reconciliation、tests/faults。
- 验收：迟到消息不启动取消操作；UNKNOWN继续占用；不凭超时回滚资金。
- 验证：F09/F10及跨服务重启，G3。
- 实际记录：未执行。

## P4 Agent

### T17 Python持久任务控制面

- [ ] T17.1：run接收、唯一revision、PG任务表及查询。
- [ ] T17.2：Java HTTP outbox调度、取消和过载响应。
- 依赖：T02,T06,T10。文件：agent/api、agent migrations、case agent dispatcher、tests。
- 验收：202发生在落库后；重复提交同run；无模型也能排队重启。
- 验证：PG集成+HTTP响应丢失测试。
- 实际记录：未执行。

### T18 MCP工具与受限身份

- [ ] T18.1：6个真实stdio MCP tools及Java HTTP适配。
- [ ] T18.2：run token签发/续签、scope注入、日志持久化。
- 依赖：T17,T04,T05,T07。文件：agent/tools、case tool-token、scope tests。
- 验收：模型无法改URL/line身份；真实tools/list/call可运行。
- 验证：跨主体、伪造参数、过期token、工具失败测试。
- 实际记录：未执行。

### T19 政策索引与检索

- [ ] T19.1：bundle同步、generation原子就绪、精确过滤。
- [ ] T19.2：BM25+dense+RRF+rerank、引用、降级。
- 依赖：T07,T17。文件：agent/policies、PG migrations、RAG fixtures/tests。
- 验收：硬过滤不可被查询覆盖；索引未就绪不使用旧规则；固定模型revision。
- 验证：同名跨商家/历史版本检索与F17。
- 实际记录：未执行。

### T20 Harness驱动的单Agent循环与预算

- [ ] T20.1：ModelClient mock/live、StateGraph动作循环与结构化输出。
- [ ] T20.2：证据引用校验、预算、重试、取消、工具并发。
- 依赖：T18,T19,T35,T36,T37。文件：agent/harness、agent/runtime、model adapter、prompt版本、tests。
- 验收：模型观察后决定下一行动；无隐式预取；预占预算/无进展停止，重试计费；Schema最多修复一次；上下文与执行可追溯。
- 验证：H-AUT/H-RUN mock轨迹测试；具备API配置时做live小样本能力冒烟并记录成本。
- 实际记录：未执行。

### T21 回调、追问与旧版本隔离

- [ ] T21.1：PG callback_outbox与Java幂等接收。
- [ ] T21.2：QUESTION补证新run，PROPOSAL进入Java授权，旧run STALE。
- 依赖：T20,T08,T09,T17。文件：agent/callbacks、case agent callbacks、system tests。
- 验收：完整Agent退款/人工审批链路；迟到STARTED不回退状态。
- 验证：F14/F18与US-02/03/04。
- 实际记录：未执行。

### T22 Checkpoint、租约与恢复

- [ ] T22.1：PG checkpointer、租约心跳、fence/advisory lock。
- [ ] T22.2：已落库工具/模型结果复用，未知模型调用单独计费统计。
- 依赖：T21。文件：agent/runtime persistence/scheduler/model-call ledger、fault tests。
- 验收：旧worker不能提交有效结果；两种崩溃窗口不同语义清晰。
- 验证：F12/F13/F18，G4 mock完整链路+live能力冒烟。
- 实际记录：未执行。

### T23 数据集与Gold

- [ ] T23.1：240案例（含24组自治配对）及分层划分、60安全例、120 RAG查询；另列至少30个长上下文压力例。
- [ ] T23.2：Gold规则生成、人工抽查清单、冻结hash。
- 依赖：T07,T08。文件：evals/datasets、fixtures、dataset validation tests。
- 验收：模板/订单家族隔离、正确动作集合、分母完整；人审待做明确列出。
- 验证：泄漏扫描、标签一致性、数据manifest校验。
- 实际记录：未执行。

### T24 基线与评测runner

- [ ] T24.1：B0/B1/A统一输入、工具权限与安全层。
- [ ] T24.2：结果落盘、失败不丢弃、统计区间、Token成本。
- 依赖：T20,T23。文件：evals/baselines/runner/metrics、unit tests。
- 验收：mock可一键复现；结果包含全部case；provider价格配置不硬编码为事实。
- 验证：固定fixture计算指标手算对照、verify -Suite agent-eval -Mode mock。
- 实际记录：未执行。

## P5 工程完善

### T25 SQL与Redis缓存

- [ ] T25.1：工单游标、索引、基线SQL执行计划。
- [ ] T25.2：非权威读缓存、single-flight、失效和Redis故障回源。
- 依赖：T14。文件：commerce query/cache、case query、migration、performance fixtures。
- 验收：授权不走陈旧缓存；分页稳定；故障不突破资金不变量。
- 验证：查询集成、缓存冷/热测试、EXPLAIN记录。
- 实际记录：未执行。

### T26 全链路观测

- [ ] T26.1：HTTP/MQ/Python工具及模型trace。
- [ ] T26.2：业务指标、看板、告警、脱敏审计展示。
- 依赖：T22,T16。文件：infra/observability、shared tracing、agent instrumentation、tests。
- 验收：单case能定位失败工具/消息；无高基数ID指标标签，无token泄漏。
- 验证：完整trace样例、故障告警触发、日志脱敏扫描。
- 实际记录：未执行。

### T27 服务治理与有界资源

- [ ] T27.1：Gateway跨实例令牌桶、Sentinel下游熔断。
- [ ] T27.2：worker并发、总deadline、MQ积压/模型故障转人工。
- 依赖：T25,T26。文件：gateway限流、Java client、agent scheduler、fault tests。
- 验收：无多层重试风暴；Agent故障仍能建单；资源上限可观测。
- 验证：F15及限流/超时集成。
- 实际记录：未执行。

### T28 工单工作台与SSE

- [ ] T28.1：消费者建单/补证、员工审核页面。
- [ ] T28.2：时间线、脱敏工具轨迹、SSE续读与错误状态。
- 依赖：T21,T16。文件：web各视图、case events API、Playwright tests；分视图实施。
- 验收：三个视图完成US-01到08主要交互，旧审批提示刷新。
- 验证：web test/build、SSE Last-Event-ID重连、浏览器权限测试。
- 实际记录：未执行。

### T32 完整CI与可启动性

- [ ] 完善矩阵、固定镜像、依赖缓存、全新环境迁移、mock端到端。
- 依赖：T22,T28,T38。文件：.github/workflows、scripts/verify、infra、tests。
- 验收：all-offline执行真实全部必要检查；关键项不能skip冒充pass。
- 验证：干净lab库构建/测试/启动（不得清用户库），G5。
- 实际记录：未执行。

## P6 实验与交付

### T29 故障实验完整矩阵

- [ ] 编排F01–F18注入、固定seed、自动查询不变量及恢复分位数。
- 依赖：T16,T22,T27,T32。文件：tests/faults、scripts、reports/faults。
- 验收：每类>=20次，有原始日志/最终账/未决项，违规效果为0。
- 验证：verify -Suite faults -Seed 42；错误必须修复并保留旧报告。
- 实际记录：未执行。

### T30 性能与RAG对照

- [ ] T30.1：后端冷/热/无缓存与索引前后同负载实验。
- [ ] T30.2：BM25/dense/hybrid/rerank四组RAG对照。
- 依赖：T25,T27,T19,T23,T32。文件：tests/performance、evals/rag、reports。
- 验收：资源/负载/样本/配置齐全，效果退化如实呈现。
- 验证：verify -Suite performance及-Suite rag-eval -Mode live。
- 实际记录：未执行。

### T31 live模型评测与人工抽查

- [ ] T31.1：模型访问/预算确认后先dev，再冻结test运行B0/B1/A各3次。
- [ ] T31.2：人工抽查至少60例、分析错误、报告成本/区间。
- 依赖：T24,T22,T23,T32,T38。文件：evals配置、reports/agent、人工抽查记录。
- 验收：mock/live分开、全部test计入分母、提示与模型版本可追踪。
- 验证：verify -Suite agent-eval -Mode live；无key可BLOCKED不能标完成。
- 实际记录：未执行。

### T33 演示与技术讲解

- [ ] 完成9个固定fixture演示（原6个+自治/上下文/回放3个）、运行手册、故障解释、技术取舍FAQ。
- 依赖：T28,T29,T30,T31,T39。文件：docs/demo.md、docs/runbook.md、docs/interview-notes.md、reports索引。
- 验收：陌生使用者可按命令完成演示，能解释每条简历主张证据。
- 验证：新lab环境按手册逐项执行并保存记录。
- 实际记录：未执行。

### T34 最终架构与证据审计

- [ ] 校核INV-01到10、US-01到08、R01到14、G0到G6及GH证据映射，修复缺口。
- 依赖：T29,T30,T31,T32,T33,T39。文件：docs/resume-evidence.md、reports/final-review.md、tasks状态。
- 验收：技术实现、实验结论和展示描述一致；没有未证实“高可用/零重复/真实用户”等主张。
- 验证：all-offline最终回归、报告manifest核对、G6通过。
- 实际记录：未执行。

## v1.1 Harness工作包（按依赖插入P4/P6）

### T35 Harness边界、manifest与动作ABI

- [ ] T35.1：按agent-harness建立类型化模块接口，落地严格ModelDecision Schema/Pydantic和manifest加载/内容hash。
- [ ] T35.2：检查模型参数能力、预算关系、版本兼容；保留Prompt artifact，禁止静默升级恢复配置。
- 依赖：T02,T17。文件：agent/harness/types与manifest、contracts/model-decision.schema.json、contracts/fixtures、unit tests。
- 验收：6种动作严格区分，运行身份不可由模型指定；manifest不含凭证；无效hash/超预算/不兼容版本明确拒绝。
- 验证：verify -Suite contracts及-Suite harness -Case manifest；正反fixture、hash与版本测试。
- 实际记录：未执行。

### T36 ContextBuilder与EvidenceLedger

- [ ] T36.1：实现P0–P4确定性组装、来源分级/版本/冲突、关键字段保留及token预算；不引入LLM摘要器。
- [ ] T36.2：实现按scope读取原始Observation、裁剪索引、合法tool pair和实际请求快照；依T35仓储接口用fixture测试，在T20与T37实际存储集成。
- 依赖：T35,T18,T19。文件：agent/harness/context与evidence、unit tests、fixtures/context；分算法与持久适配交付。
- 验收：H-CTX-01–05通过；同输入hash一致；长材料可精确读回；关键层超限显式失败，无推断升级权威事实。
- 验证：verify -Suite harness -Case context；边界/冲突/恶意文本/多语言长度fixture。
- 实际记录：未执行。

### T37 SessionStore、调用账与轨迹包

- [ ] T37.1：agent_db追加manifest/context/event/evidence/budget迁移，事件与关键记录同事务、fence保护、稳定call_id。
- [ ] T37.2：持久显式模型输出和实际请求、用量预占/结算/UNKNOWN；实现合成ReplayPack只读导出与hash清单。
- 依赖：T35,T17。文件：agent/harness/session、agent migrations、scripts/replay.ps1 export、PG integration tests。
- 验收：event sequence唯一有序；重入不伪造或丢观察；导出无凭证、不覆盖原pack，日志不是新的业务状态权威。
- 验证：PG事务/并发/旧fence测试、导出hash/脱敏测试；预留崩溃fixture给T22/T38。
- 实际记录：未执行。

### T38 隔离回放与GH验收

- [ ] T38.1：strict记录响应回放、RecordedToolAdapter、临时评测库和本地CallbackSink；固定完整golden packs。
- [ ] T38.2：counterfactual-recorded分支匹配/REPLAY_MISS；复用T23合成世界实现world模式；记录首个差异/覆盖率。
- [ ] T38.3：执行容器出站约束、拒绝业务凭证/回调/原库写入；综合验收GH。
- 依赖：T22,T24,T37。文件：evals/replay、scripts/replay.ps1 run、infra/replay、agent/tests、reports/harness-gate。
- 验收：H-RPL-01–06通过；strict不访问模型或Java，变体缺分支不猜答案；无权威业务效果，三模式不混报。
- 验证：verify -Suite harness、strict golden packs、mock反事实、无网络测试及GH；live小样本沿用同版本T20有效记录，否则补测。
- 实际记录：未执行。

### T39 Harness消融与简历证据

- [ ] T39.1：dev定C0/C1/C2，冻结配置后test各3次；正常/压力分层，复用符合条件的T31 C2结果。
- [ ] T39.2：完成live自治配对、上下文总成本/质量/overflow、回放覆盖和安全有界的停止策略消融报告。
- [ ] T39.3：映射R07/R08/R11/R13/R14到代码、测试、实际报告和面试解释，保留负面结果。
- 依赖：T31,T38,T36,T23。文件：evals/variants、evals/metrics、reports/harness、docs/resume-evidence.md。
- 验收：全部分母和UNKNOWN/INCOMPLETE明确；未见分支不混充回放成功，未提升如实报告；API预算不足标阻塞，不填假指标。
- 验证：verify -Suite harness-eval -Mode live -Seed 42；报告hash/配对统计校验；交由T34最终审计。
- 实际记录：未执行。
