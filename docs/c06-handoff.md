# C06 交接（2026-09-25）

> 历史快照，不作当前起点。“Harness空包”等描述已过时；当前实现先核对任务账本。2026-09-25AgentScope迁移入口见[迁移规格](agentscope-migration.md)，从AS00接管开始，不重复本文件已完成步骤。

给接续会话的交接说明。**先读 `AGENTS.md`**，再读本文件；规范权威仍是 `docs/core-scope.md` 等文档，本文件只负责"现场状态 + 下一步 + 门命令 + 已知陷阱"，不代替规范。

## 0. 现场

| 项 | 值 |
| --- | --- |
| 工作副本 | `E:\Code\Agent+Backend`（**`Code` 与 `Agent` 之间是反斜杠**；书写路径时用正斜杠 `E:/Code/Agent+Backend`，见 §6 陷阱） |
| HEAD | `54b4eec`（`main`，= `origin/main`） |
| 未提交改动 | 59 项（**C06 的全部工作都在工作区，未提交、未推送**） |
| 容器 | `resolveflow-postgres-1`（`127.0.0.1:55432`）、`resolveflow-mysql-1`（`127.0.0.1:3306`）均 healthy |
| `JAVA_HOME` | `C:\Users\hjn\.jdks\jdk-21.0.12.1+1` |
| 证据目录 | `reports/c06-runs/`（C06 期间的每次真实运行都在这里，文件名带切片号） |

**当前测试基线（已核验，2026-09-25）**：

- Python 全量 `pytest agent/tests` → **697 passed, 9 skipped**
- Java 全量 `.\java\mvnw.cmd -B test` → **350 tests, 0 failures, 4 skipped**（shared 59 / gateway 5 / commerce 85 / fulfillment 2 / case 199）
- `spotless:check` → **BUILD SUCCESS**（145 文件）
- `ruff check agent/src agent/tests` → **All checks passed**
- strict mypy → **9 errors，全是既有问题**（见 §5，**门命令有陷阱**）

## 1. C06 已完成的部分

C06 的大目标是"Agent 控制面、MCP 与能力冒烟"（`tasks/todo.md:977`）。已交付的是**控制面与工具面**，**Harness 本体还没有**（`agent/src/resolveflow/harness/` 目前只有空 `__init__.py`）。

| 子步 | 内容 | 关键文件 | 证据 |
| --- | --- | --- | --- |
| C06.1a | PG 持久 run 入口 + 服务令牌校验（幂等排队、同键异体 409、身份不符 422、未知 run 404） | `runtime/db.py`、`runtime/runs.py`、`runtime/migrations/001_agent_run.sql`、`api/identity.py`、`api/app.py` | `20260924-c061*` |
| C06.1b | agent 侧回调 outbox 的落库与投递记账 | `runtime/callbacks.py`、`runtime/migrations/002_...sql` | `20260924-c061b-*` |
| C06.1b-2 | 投递客户端：取件 → POST 回调 → 按 disposition 记账（退避 5/10/20/…上限 300s，永久拒绝记 DEAD） | `runtime/delivery.py`、`runtime/migrations/003_...sql` | `20260924-c061b-*` |
| C06.1c | Java 侧 Case→Agent 派发绑定（`202` + fence） | `casefile/AgentRunDispatch.java`、`AgentRunClient.java`、`AgentRunBindingRepository.java`、`AgentRunId.java`、`V15__agent_binding.sql` | `20260925-c061c-*` |
| C06.3 | 两个常驻循环（`ExecutionDispatchLoop`、`AgentRunDispatchLoop`、Python `CallbackDeliveryLoop`），**开关默认关闭** | `casefile/*Loop.java`、`runtime/dispatch.py`、`runtime/delivery.py` | `20260925-c063a-*`、`20260925-c063b-*` |
| C06.2a | Commerce 模拟物流只读适配 | `commerce/shipment/*`、`V6__commerce_shipment_adapter.sql` | `20260925-c062a-*` |
| C06.2b | **5 个白名单工具走真实官方 MCP stdio**（`mcp==2.2.0`） | `tools/upstream.py`、`tools/catalog.py`、`tools/server.py`、`tests/integration/test_mcp_tools.py`、`stub_upstream.py` | `20260925-c062b-*` |
| C06.2c | 补齐 Commerce `GET /internal/v1/order-lines/{line_id}/refund-status` | `commerce/order/LineRefundStatusRepository.java`、`refund/RefundStatusReadService.java`、`RefundStatusController.java` | `20260925-c062c-*` |

细节（含每一步的真实失败与修法）在 `tasks/todo.md:985` 起，**那才是权威记录**，本表只是索引。

## 2. 下一步：C06.4

**让 Harness 真正驱动这五个工具**。`harness/` 现在是空的，这是 C06 的缺口，也是 C07（上下文/政策）的前置。

建议拆成小步，每步红测试先行：

1. **HarnessRunner 骨架 + mock ModelClient**：按 `docs/agent-harness.md` 的循环（模型 → 工具 → Observation → 模型）跑通一次，先只用 mock 模型，不接真模型。预算按 `docs/agent-spec.md:40`（12 次模型调用、16 次工具尝试、8 次本地读取、40000/4000 tokens）。
2. **把 5 个工具接进 Harness**：Harness 通过 MCP 客户端调用 `python -m resolveflow.tools.server` 子进程（`tools/server.py` 已经能用），**不是直接 import 工具函数**——`docs/agent-spec.md:34` 要的是真实 MCP 路径。
3. **工具侧重试预算接进 run 预算**：`docs/agent-spec.md:40` 的"tool retries ≤2"目前**只在工具层内部**（`get_shipment_trace` 的分页预算、`catalog` 的错误分类），**没有与 run 的 16 次工具尝试预算打通**。
4. **run 级工具凭据**：`POST /internal/v1/runs/{run_id}/tool-credential`（契约已声明，route 表里有；**未实现**）。目前工具令牌来自环境变量 `RESOLVEFLOW_TOOL_SERVICE_TOKEN`，不是按 run 铸造。
5. **一次真实 Java↔Python 端到端**：`scripts/e2e_refund_chain.py` **已经会起 Python Agent**（`uvicorn resolveflow.api.app:app`，见该文件 290 行附近），但它现在**没有起工具 server、也没有让 run 真的走 Harness**。在这一步把它接上——这是"Java 与 Python 真的互通"的第一次真实证据，目前**所有工具测试打的是桩**。

## 3. 明确未做（不要以为已经有了）

- **错误响应体**：Python 侧仍是 FastAPI 的 `{"detail": …}`，**不是**契约的 `{code,message,retryable,trace_id}`
- **429 OVERLOADED** 无容量检查
- **`scripts/verify.ps1 -Suite all-offline` 从未运行过**（含真实服务 smoke，需要 Docker）
- **`READ_OBSERVATION`** 作为本地读取能力未实现
- **Observation 落库 / 原文受限持久化**未实现（`docs/agent-spec.md:36` 的 excerpt/raw 尺寸闸只在内存里）
- **strict replay**（不访问网络/业务写入口）属 C10，未做
- Java 有 4 个 skipped（`CoreEventTransportSystemTest` 等），**不是绿的，是没跑**

## 4. 门命令（照抄，注意目录）

```powershell
# Python
uv run --project agent --frozen pytest agent/tests -q          # 697 passed, 9 skipped
uv run --project agent --frozen ruff check agent/src agent/tests

# strict mypy —— 必须在 agent/ 目录里跑，见 §5 的陷阱
cd agent; uv run --project . --frozen mypy; cd ..

# Java
$env:JAVA_HOME = 'C:\Users\hjn\.jdks\jdk-21.0.12.1+1'
cd java; .\mvnw.cmd -B test; .\mvnw.cmd -B spotless:check; cd ..

# 聚焦（改哪跑哪）
uv run --project agent --frozen pytest agent/tests/integration/test_mcp_tools.py -q
cd java; .\mvnw.cmd -B -pl commerce-service -am test "-Dtest=OrderLineRefundStatusControllerTest" "-Dsurefire.failIfNoSpecifiedTests=false"; cd ..
```

新增/修改 Java 文件后**先 `spotless:apply` 再复跑**，否则 `spotless:check` 会红。

## 5. 已知陷阱（都是踩过的）

1. **strict mypy 的门命令**：`uv run --project agent --frozen mypy agent/src`（从仓库根执行）**不会**加载 `agent/pyproject.toml`，于是 `strict = true` / `warn_unreachable = true` **全部没生效**——它会报 "Success"，而那是**假的绿灯**。整条 C06 期间我一直在用这个错命令。正确做法是**在 `agent/` 目录里执行**。当前 strict 下有 **9 个既有错误**在 `contracts/core_corpus.py`×4、`provider_stub/__init__.py`×3、`contracts/_schemaio.py`×1、`contracts/fixtures.py`×1（与 C06.1a 记的同源，未修）。
2. **反斜杠+A 会被工具边界间歇改写成 `+`**：`E:\Code\Agent+Backend` 里的 `\A` 有时变成 `+`，写入落到 `E:\Code+Agent+Backend`。**所有路径用正斜杠书写**，写入后回读。
3. **`edit` 工具在带外写入后会拒绝**（"file changed since it was read"）：先重新 `read`，或用多替换脚本（本次交接用的脚本在 `C:/Users/hjn/ResolveFlow-c061-preserved/`）。
4. **测试库隔离**：per-test schema `t_<uuid16>`；Java commerce 测试用 `CommerceDatabaseTest`（单例 Testcontainers `mysql:8.4`），case 用 `CaseDatabaseTest`，但 **`CaseServiceApplicationTest` 需要真的 `resolveflow-mysql-1` 在 3306**。
5. **`agent/tests/integration/` 是包**：导入桩要写 `from tests.integration import stub_upstream`。
6. **mcp 2.2.0 与记忆不同**：`FastMCP` 已改名 `MCPServer`（`from mcp.server.mcpserver import MCPServer, Context`），**没有** `mcp.server.fastmcp`；结果是 snake_case（`is_error`/`structured_content`/`input_schema`）。**失败观察返回的是 `is_error=False`**（错误在 Observation 里），别把它当协议错误。
7. **`context.session` 每个请求都是新对象**（mcp 2.2.0）：**不能**把 run 级状态挂在 session 上（那会让计数器每次重置、上限形同不存在）。`tools/server.py` 现在挂在进程上（stdio 下成立），**将来多会话传输必须改成按会话的键**。
8. **容器不起，测试会 skip 而 `verify.ps1` 拒绝在 skip 上判过**：`docker start resolveflow-postgres-1`（DSN `postgresql://agent:agent@127.0.0.1:55432/agent_db`）。
9. **不要**为通过而删断言/清库/删卷/重写历史/推送。守卫类测试要**故意弄红**验证过才算数（本次交接做了两次：契约路由缺口的守卫、端口默认值）。

## 6. 端口（权威是 `scripts/e2e_refund_chain.py`）

| 服务 | 端口 |
| --- | --- |
| gateway | 8080 |
| **commerce-service** | **8081** |
| **case-service** | **8083** |
| Python Agent | 由 e2e 脚本动态取空闲端口 |
| RocketMQ | 9876 |
| Postgres / MySQL | 55432 / 3306 |

`tools/server.py` 的默认地址已订正为 `127.0.0.1:8083` / `:8081`，并由 `agent/tests/unit/test_tool_defaults.py` 从 e2e 脚本**读出来**钉住（不是再抄一份）。

## 7. 硬边界（`AGENTS.md`，别越）

单订单行全量模拟退款；同行最多一次成功退款；UNKNOWN 不释放、不换 ID 重付；Agent 无退款/审批/政策修改/跨主体读取权限；Java 拥有工单/授权/金额，Python 拥有 run；outbox 至少一次；外部网络调用不放长事务；迁移只追加。不提交密钥、不开未经确认的收费评测或公网部署。
