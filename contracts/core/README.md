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
| `openapi-case.yaml`（18 条路由，含 5 条内部路由） | 待建立（C00.2b-3） |
| `agent-proposal.schema.json` | 待建立（C00.2c） |
| 核心正反 fixture 与核心路由覆盖测试 | 待建立（C00.2b/C00.2c） |
| Java/Pydantic 核心 DTO | 待建立（C00.2c） |
| core profile 启动/smoke 选择（不要求 fulfillment/Nacos/观测集群） | 待调整（C00.3） |

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

路由覆盖测试（`agent/tests/unit/test_contracts_core_routes.py`）直接从 `docs/core-contracts.md` 第3节表格解析路由，并把每类数量钉住（Case 18 / Commerce 4 / Agent 5 = 27），逐项与核心 OpenAPI 的 `paths` 对比；同时检查每个 `$ref` 都能在文档内解析、核心错误体与 compat 错误体逐字段相同、以及所有示例都能通过自身组件的校验。

校验方式：核心 Schema 不在旧文件集里，用 `resolveflow.contracts._schemaio.CORE_SCHEMA_FILES` 传入 `validator_bundle` / `schema_registry`；测试 `agent/tests/unit/test_contracts_core_schemas.py` 断言两套 `$id` 互不相交、互不可解析，并断言命令的属性集合恰好等于 `canonical.REFUND_FIELDS + payload_hash`（Schema 与哈希实现不能各自漂移）。

后端服务当前只有骨架与健康接口，核心路由与业务能力均未实现；`contracts/core` 里的目标文件不代表它们已经在运行。