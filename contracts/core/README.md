# contracts/core：核心版协议目标（v1.2）

2026-09-18。本目录是 **C00 要落地的核心协议目标**，与仓库根目录的 T02 兼容基线分开存放。权威：`docs/core-scope.md`（范围）、`docs/core-contracts.md`（协议）。

## 1. 与旧基线的关系

| | 旧兼容基线（T02，保留） | 核心协议（本目录，C00 建立） |
| --- | --- | --- |
| 位置 | `contracts/*.schema.json`、`contracts/openapi-*.yaml` | `contracts/core/**` |
| 版本 | 命令/信封/方案 `schema_version=1` | 命令/信封/方案 `schema_version=2`，使用独立 URN |
| Topic | 旧 topic | 固定 `rf.case.core.v2` / `rf.commerce.core.v2` |
| 消费者 | 旧 fixture、旧枚举与 hash 冻结测试 | 核心服务与 Agent（无运行中的旧业务客户端） |
| 状态 | **兼容资产，不据此开放旧写接口** | 目标协议，尚未实现的部分不得当作已完成 |

规则：旧基线不删、不改语义后沿用旧版本号；核心文件不复用旧 `$id`/URN。旧 fixture 里的 `RESHIP`、`entitlement_*`、`cancel-before-start` 等只作为兼容资产存在，**核心命令不接受**（见 `profile.json` 的 `capabilities.deferred`）。为让旧 fixture 通过而临时伪造 `entitlement_id` 是禁止的。

## 2. profile.json

`profile.json` 是机器可读的**允许能力清单**，不是进度声明。它声明：

- 核心进程：`gateway`、`case-service`、`commerce-service`（Java）+ `agent`（Python）；
- 兼容但不部署：`fulfillment-service`；不要求：Nacos、Sentinel、完整观测集群；
- 协议版本：命令/信封/方案 = 2，harness manifest = 1（不因业务命令升级而强制改版本）；
- 事件名沿用 `RefundRequested/RefundSucceeded/RefundFailed/RefundUnknown`，topic 固定为 core v2；
- `payload_hash` 只覆盖 12 个字段（不含 `entitlement_id`、`address_hash`，不含自身 hash、trace、发送时间）；
- 允许动作只有 `REFUND`，目标服务只有 `commerce-service`；
- 延期能力逐项列出（补发/库存/权益 Saga/执行中取消/部分退款/反事实回放/世界回放器/全量 RAG 消融/观测集群/多 Agent）。

读取方式：`resolveflow.contracts.core_profile.load_core_profile()`；测试见 `agent/tests/unit/test_contracts_core_profile.py`，其中若干断言直接对比 `docs/core-contracts.md` 的字段清单，避免 profile 与权威文档各说一套。

## 3. 现状（不要当成已完成能力）

| 文件 | 状态 |
| --- | --- |
| `profile.json` | 已建立（C00.1，2026-09-18） |
| `refund-command.schema.json`（`urn:resolveflow:core:refund-command:v2`） | 已建立（C00.2a，2026-09-18） |
| `event-envelope.schema.json`（`urn:resolveflow:core:event-envelope:v2`） | 已建立（C00.2a，2026-09-18） |
| `openapi-commerce.yaml`（4 条 `/internal/v1/...` 路由） | 已建立（C00.2b-1，2026-09-18） |
| `openapi-agent.yaml`（5 条路由，含 `/health`） | 已建立（C00.2b-2，2026-09-18） |
| `openapi-case.yaml`（18 条路由：13 条 `/api/v1` + 5 条 `/internal/v1`） | 已建立（C00.2b-3，2026-09-18） |
| `agent-proposal.schema.json`（`urn:resolveflow:core:agent-proposal:v2`） | 已建立（C00.2c-1，2026-09-18） |
| 核心路由覆盖测试（三份文档逐项对应） | 已建立（C00.2b，45 个测试） |
| 核心正向 fixture（`fixtures/valid.json`） | 已建立（C00.2c-2a，2026-09-19；含 45 个语料测试） |
| 核心反向 fixture（`fixtures/reject.json`） | 已建立（C00.2c-2b，2026-09-19；51 条负例、18 个测试） |
| 核心期望值冻结（`fixtures/expected.json`，`scripts/contracts_core_freeze.py --check`） | 已建立（C00.2c-3b-1，2026-09-19；8 个测试，已纳入 contracts suite） |
| Java 核心 record 与跨语言证据（`shared/core/CoreContract.java` 等，7 个测试） | 已建立（C00.2c-3b-2，2026-09-19） |
| Java/Pydantic 核心 DTO | 已建立（C00.2c-3a/3b，2026-09-19；Python 80 个测试、Java 7 个测试） |
| core profile 启动/smoke 选择（不要求 fulfillment/Nacos/观测集群） | 已调整（C00.3，2026-09-19；17 个测试，两个 profile 各跑通一次 smoke） |

## 4. C00.2a 的形状决策（v1 → v2 显式差异）

这些差异是**有意的协议决定**，不是改名，写在这里以免被当成笔误：

1. **信封不再重复 `aggregate_id`/`aggregate_version`**。`docs/core-contracts.md` 第5节把业务版本放在结果 payload 里，`docs/domain-model.md:3` 又明确 version（乐观锁）与 input_revision（决策输入）不得混用；两个位置都能放同一个版本就会不一致，因此 core 信封只保留路由与签名所需字段，`aggregate_version` 只在结果 payload 里出现一次。
2. **结果也必须签名**。`docs/core-contracts.md:65` 要求 Commerce 签名结果、Case 校验来源与签名，所以 core 信封里 `signature`/`signing_key_id` 是必填；旧 v1 信封允许结果不签名（该行为在旧文件中原样保留）。
3. **命令不带 `schema_version` 字段**。v2 由 URN 与信封 `schema_version=2` 标识；命令自身的每个字段都被 `payload_hash` 覆盖，放一个不参与哈希的版本字段会让两条不同命令共享摘要。
4. **命令必填 `amount_minor`**，且 `action`/`target_service` 为常量。旧 v1 命令的 `amount_minor` 是条件必填，`target_service` 还允许 `fulfillment-service`——这些旧行为未被收紧，旧 fixture 照常通过。
5. **同一行版本在两个线面上名字不同，各自有权威**：结果事件 payload 用 `aggregate_version`（`docs/core-contracts.md:67`），Commerce 的 REST 视图用 `version`（`docs/domain-model.md:43` 的列名）。两处都指向同一条 `refund_operation` 行的乐观锁版本，且各自的描述里写明了对方，避免被读成两个事实。
6. **核心 commerce 文档收窄了 compat 文档**：只保留 4 条 `/internal/v1/...` 路由，`/internal/v1/entitlements/*` 与 `cancel-before-start` 不在核心（`docs/core-contracts.md:53`）；`line_refund` 状态枚举只有 `FREE/RESERVED/CONSUMED`，compat 的 `IN_USE` 属于被延期的跨服务权益协议，因此核心文档里没有 `Action`/`EntitlementState*` 组件。物流视图新增必填常量 `synthetic: true`（`docs/core-scope.md:30`），不允许伪装成真实承运商接口。
7. **核心退款 operation 只有 5 个状态**：`docs/domain-model.md:57` 明确"核心退款 operation 用 RECEIVED/IN_PROGRESS/UNKNOWN/SUCCEEDED/FAILED；不启用旧 STARTING/CANCELLED 目标协议"。因此核心文档的 `OperationState` 是这 5 个，而不是 compat 里的 14 态两阶段状态机（compat 枚举保持不动，测试同时断言两边）。这是 C00.2b 中发现的规范差异：照搬旧状态机会让核心协议声明它并不运行的 start/commit 协议。
8. **核心 agent 文档的三处收窄**（compat 文档保持不动，均有对照断言）：`requested_actions` 只有 `REFUND`（compat 还有 `RESHIP`/`EITHER`）；`evidence_source_type` 去掉 `LINE_ENTITLEMENT` 与 `PACKING_MANIFEST`（核心没有权益/打包端点可供 Java 复核，`docs/core-contracts.md:53`）；`RunAccepted.status` 是常量 `QUEUED`，不再是 `[QUEUED, ANALYZING]`——`ANALYZING` 是 case 状态（`docs/domain-model.md:55`），run 文档借用 case 词汇正是两个状态机开始互相甩锅的起点（run 词汇表在 `docs/agent-spec.md:9`）。`/health` 显式 `security: []`：编排器探活不应需要 service token。
9. **核心 case 文档是 18 条路由，不是 compat 的 21 条**：去掉 `/api/v1/policies/import`、`/publish`、`/revoke`（`docs/core-contracts.md:53` 说政策由受控脚本导入校验，不做管理 HTTP 全集），保留两条只读政策面。动作词汇收窄为 `REFUND` 单值（`Action`/`RequestedAction` 都是常量枚举，`RecommendedAction` 去掉 `RESHIP`，`docs/agent-spec.md:19`、`docs/core-scope.md:9`）；op 状态沿用五态收窄。
10. **核心 `CaseSnapshot` 带 `timeline`**（compat 把它留给另一次读取）。权威：`docs/core-scope.md:7` 要求工单展示"结果与调查轨迹"、`docs/domain-model.md:34` 有独立持久化的 `case_timeline`、`docs/core-contracts.md:67` 要求它和 inbox/投影/本地事件同事务写入。轨迹与状态同事务才能保证两者不互相矛盾。
11. **回调 payload 按 kind 强类型**：compat 把 `payload` 留成 `additionalProperties: true` 的自由对象；核心为四种 kind 各定义 `StartedPayload`/`QuestionPayload`/`ProposalPayload`/`FailedPayload`，并用 `if/then` 把 `kind` 钉到对应形状（QUESTION 的 `questions` 上限 3，`docs/core-contracts.md:59`）。`ProposalPayload` 与 `ProposalView` 拆开：payload 是 run 提交的方案本身，view 额外带 case 侧拥有的 `status`/`created_at`；C00.2c 的 `agent-proposal.schema.json` 必须与 `ProposalPayload` 字段一致，由测试守住不漂移。
12. **核心提案保留 `schema_version` 与 `case_id`（此处曾写错，已按权威改正）**：C00.2c-1 一度把两个字段都删掉，理由是"回调端点已按 case 定位、版本由 `$id` 承担"。这与权威冲突：`docs/core-contracts.md:9` 写的是"核心Agent方案 schema_version=2 且不允许 RESHIP，**其他字段复用旧结构**"，而 compat 提案（`contracts/agent-proposal.schema.json`，`schema_version` 常量 1、`case_id` 必填）正是那个"旧结构"；`docs/core-contracts.md:57` 又要求"body 主体必须与 service JWT 及 Case 绑定一致"——绑定不在 body 里，Java 就没有可交叉校验的东西。现在两个字段都在（`schema_version` 常量 2），三处（提案 Schema、`ProposalPayload`、`ProposalView`）与示例同步。测试仍断言核心字段集合与 `ProposalPayload` **逐个属性、逐条约束**一致（含 `$ref` 解引用后比较），并新增 `schema_version=1`、字符串版本、`case_id` 非 UUID 的负例。教训记录在此：**收窄 compat 字段必须有权威行号，否则就是自造协议**。
13. **`suggested_amount_minor` 不再接受 `null`**（compat 是 `[integer, null]`）："没建议金额"只由字段缺失表达，`null` 不是第二种说法。顺便修掉了同一事实两种表示的老毛病——这与决策 5 里 `aggregate_version`/`version` 的处理是同一类问题。核心 case 文档的 `ProposalPayload`/`ProposalView` 与提案 Schema 三处已同步收窄，测试同时断言三处都不允许 `null`。
14. **`source_ref` 现在真的拒绝 URL**：`docs/core-contracts.md:61` 说"ref 不是可请求的任意 URL"，但 compat 只写了 `minLength`/`maxLength`——文档声称的约束并没有被 Schema 强制。核心三处（提案 Schema 的 `evidence_refs.items`、case 的 `EvidenceRef`、agent 的 `ObservationRecord`）统一加了 `pattern: '^(?!https?://)[a-z][a-z0-9_]*:\S+$'`，并加了把 `https://…` 当负例拒绝的测试。
15. **引用行号现在被机器校验**（`agent/tests/unit/test_contracts_core_citations.py`）：扫描 `contracts/**`、`agent/src/resolveflow/contracts/**`、`java/shared-kernel/.../contract/**` 里所有 `docs/X.md:N` 形式的引用，断言该文件存在且至少有 N 行。加这条守卫是因为发现 `contracts/core/event-envelope.schema.json` 引用 `docs/domain-model.md` 的第126行（该文件仅 72 行），而当时的引用规则只覆盖 OpenAPI 文档、且只检查"写了引用"而非"引用指得通"。守卫上线后一共揪出 15 处指不到的行号（1 处在核心、14 处在 compat 基线与 Python/Java 契约源码里）：`docs/product-spec.md` 的第46行（该文件仅 40 行，真实权威是第 25 行"Java 重算金额，与建议不一致不能静默修改后执行"）、`docs/domain-model.md` 的第104/110/122/126行、`docs/engineering.md` 的第98行，全部改为真实行号：case 取消/对账 → `docs/domain-model.md:55`，旧 revision 无效 → `docs/domain-model.md:13`，方案不可原地改载荷 → `docs/domain-model.md:29`，provider 调用规则 → `docs/domain-model.md:51`（并注明 `IN_USE` 只是兼容超集 `docs/domain-model.md:59`），JWT 校验 → `docs/core-contracts.md:15`。这些改动只动描述文本与 DTO 文档串，不动任何线上形状；本 README 里对"曾引错的行号"一律用"第 N 行"表述，好让守卫只统计真正的引用。

路由覆盖测试（`agent/tests/unit/test_contracts_core_routes.py`）直接从 `docs/core-contracts.md` 第3节表格解析路由，并把每类数量钉住（Case 18 / Commerce 5 / Agent 5 = 28），逐项与核心 OpenAPI 的 `paths` 对比；同时检查每个 `$ref` 都能在文档内解析、核心错误体与 compat 错误体逐字段相同、所有示例都能通过自身组件的校验（当前 49 个测试、53 个示例），以及 case 的内部路由必须用 service token、登录接口不得要求 token、QUESTION 问题数上限为 3。

校验方式：核心 Schema 不在旧文件集里，用 `resolveflow.contracts._schemaio.CORE_SCHEMA_FILES` 传入 `validator_bundle` / `schema_registry`；测试 `agent/tests/unit/test_contracts_core_schemas.py` 断言两套 `$id` 互不相交、互不可解析，并断言命令的属性集合恰好等于 `canonical.REFUND_FIELDS + payload_hash`（Schema 与哈希实现不能各自漂移）。

后端服务当前只有骨架与健康接口，核心路由与业务能力均未实现；`contracts/core` 里的目标文件不代表它们已经在运行。

## 5. 启动范围与尚未实现的能力（C00.3）

**当前真的能启动的**（`pwsh -File scripts/verify.ps1 -Suite smoke`，默认 `-Profile core`，逐个进程启起来并读健康端点）：

| 进程 | 端口 | 健康端点 |
| --- | --- | --- |
| gateway（Java） | 8080 | `/actuator/health` |
| commerce-service（Java） | 8081 | `/actuator/health` |
| case-service（Java） | 8083 | `/actuator/health` |
| agent（Python） | 8090 | `/health` |

**默认不启动**：`fulfillment-service`（`profile.json` 的 `compat_only_services`）与 Nacos（`not_required`）。Nacos 容器在 `infra/compose.yaml` 里挂到 `compat` profile 后面，所以 `docker compose up -d` 不会拉起它——这一条有测试盯着（`agent/tests/unit/test_contracts_core_startup.py`），因为把容器悄悄放回默认集合会让"核心不依赖它"这句话变成假的，而没有任何文档需要改动。

**旧入口保留**：`-Profile compat` 才加上 `fulfillment-service`，并让 `infra-up` 带 `--profile compat`（于是 Nacos 也会起来）。旧协议、旧 fixture、旧测试与旧断言一条没删（`docs/engineering.md:40`）。

**启动集合只有一个来源**：`scripts/verify.ps1` 从 `contracts/core/profile.json` 读 `core_services` / `compat_only_services` 来决定启谁，脚本里只保留"名字 → jar 与端口"的映射；profile 里加了服务却没有启动器会当场失败，而不是被静默跳过。

**尚未实现（不要读成已有能力）**：核心 28 条路由里目前只有 1 条真的实现了（见下节），退款闭环、Agent 调查与政策检索、恢复/回放/实验，全部还是目标协议；observability 容器目前根本不存在，将来也应放在自己的 compose profile 里，而不是默认集合。

**证据**：`reports/verify/20260919-102959-smoke.txt`（核心 profile；跑之前先 `docker compose --profile compat stop nacos`，当时 Nacos 容器是停的）、`reports/verify/20260919-103025-smoke.txt`（compat profile，含 fulfillment 与 Nacos）。两份都 PASS。

## 6. C01.2 发现的契约缺口：订单视图有公共路由，没有内部来源

核心路由表里 Case 的 `GET /api/v1/orders` 写着「当前主体订单视图；内部请求Commerce」（`docs/core-contracts.md:26`），但核心 commerce 文档（compat 也一样）**没有任何按主体列订单行的内部路由**：原有 4 条都是按 `line_id` 或 `operation_id` 取单点事实。订单与支付属于 `commerce_db`（`docs/architecture.md:11`），而 Case 既没有订单表也没有订单投影（`docs/domain-model.md` 的 case_db 一节没有这类表），所以 Case 无法在不越权读别人库的前提下实现这条公共路由。

处理方式（不挑方便版本）：**补上缺的那条内部读路由**，并把它写回权威表格——
`GET /internal/v1/order-lines`（service token、`merchant_id` 必填、`customer_id` 可选、游标分页，返回 `OrderLinePage`），表格已在 `docs/core-contracts.md` 第3节新增一行，Commerce 路由数因此 4 → 5、总数 27 → 28。
作用域由 Case 从已校验的用户 token 推导后传入内部调用；公共路由不接受 `merchant_id`/`customer_id`/`scope` 参数，有测试钉住这一点，因为一旦公共路由能指定作用域，客户就能读别人的订单行。
两个文档里的 `OrderLineSummary`/`OrderLinePage`/`PageMeta` 定义逐字相同，由测试逐项比对，避免同一载荷在两个文档里各自漂移。
**这条内部路由的落地进度**：C01.2b-1 完成了 `commerce_db` 的迁移（`orders`/`order_line`/`payment_ledger`）、演示种子与按主体作用域的读服务；C01.2b-2 接上了 HTTP 路由与 service token 校验（用户 token 一律 403，缺 token 401，缺 `merchant_id` 或坏游标 400），并证明 MySQL 账户确实不跨库读取；C01.2c 起 case-service 真的在用它（`GET /api/v1/orders` 与 `GET /api/v1/orders/{order_id}`，作用域由 Case 从用户 token 推导后传入，另加可选 `order_id` 过滤）。

## 7. 已实现的核心路由（C01.1–C01.2，2026-09-19）

28 条核心路由里真正实现的目前是 **4 条**：case-service 的 `POST /api/v1/auth/login`、`GET /api/v1/orders`、`GET /api/v1/orders/{order_id}`，以及 commerce-service 的 `GET /internal/v1/order-lines`（service token 专用，供前者使用）。它按核心 OpenAPI 的 `LoginRequest`/`LoginResponse` 出入参，登录不需要 token，失败走统一错误体（401 `UNAUTHENTICATED` 对"口令错"与"账号不存在"只有同一条消息，400 `INVALID_ARGUMENT` 拒绝未知字段）。

除此之外**全部仍是目标协议**：订单、工单、证据、授权、审批、内部接口都没有实现，`GET /api/v1/orders` 之类仍是 404。演示账号见 `docs/product-spec.md:9`（CUSTOMER/REVIEWER/OPERATOR、2 个合成商家各 ≥2 用户）；口令只存 PBKDF2-SHA256 哈希（`docs/domain-model.md:24`），签名是 HS256、用户面与服务面 `aud` 分离，且算法固定不读 token 自带的 `alg`。没有 JWKS、密钥轮换、RS256、refresh 或吊销列表——这是演示身份，不是可用于生产的 IAM。