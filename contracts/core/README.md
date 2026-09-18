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
| `openapi-case.yaml` / `openapi-commerce.yaml` / `openapi-agent.yaml` | 待建立（C00.2） |
| `refund-command.schema.json` / `event-envelope.schema.json` / `agent-proposal.schema.json` | 待建立（C00.2） |
| 核心正反 fixture 与核心路由覆盖测试 | 待建立（C00.2） |
| Java/Pydantic 核心 DTO | 待建立（C00.2） |
| core profile 启动/smoke 选择（不要求 fulfillment/Nacos/观测集群） | 待调整（C00.3） |

后端服务当前只有骨架与健康接口，核心路由与业务能力均未实现；`contracts/core` 里的目标文件不代表它们已经在运行。