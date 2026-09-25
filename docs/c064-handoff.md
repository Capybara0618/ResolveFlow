# C06.4 交接（2026-09-25）

给接续会话的交接说明。**先读 `AGENTS.md`**，再读本文件；规范权威仍是 `docs/core-scope.md` 等文档，本文件只负责"现场状态 + 下一步 + 门命令 + 已知陷阱"。

上一份是 `docs/c06-handoff.md`（C06 控制面与工具面，写于 C06.4 之前）。本文件只写 C06.4 这一段：**Harness 开始真的驱动那五个工具**。

## 0. 现场

| 项 | 值 |
| --- | --- |
| 工作副本 | `E:\Code\Agent+Backend`（**`Code` 与 `Agent` 之间是反斜杠**；书写路径时用正斜杠 `E:/Code/Agent+Backend`） |
| HEAD | `51666d2`（`main`，**= `origin/main`，已推送**） |
| 未提交改动 | **0**（工作树干净）。C06 整包（1a→C06.4④b）此前一直积攒在工作区、一次都没提交，已于 2026-09-25 作为 `51666d2` 一次提交并推送（150 文件 / +28460） |
| 容器 | `resolveflow-postgres-1`（`127.0.0.1:55432`）、`resolveflow-mysql-1`（`127.0.0.1:3306`）均 healthy |
| `JAVA_HOME` | `C:\Users\hjn\.jdks\jdk-21.0.12.1+1` |

**当前测试基线（已核验，2026-09-25，C06.4 之后）**：

- Python 全量 `pytest agent/tests` → **746 passed, 9 skipped**（C06.3 的 671 → C06.2c 的 694 → 697 → **746**，本段 +49）
- Java 全量 `.\java\mvnw.cmd -B test` → **BUILD SUCCESS**；case-service **209 tests, 0 failures, 4 skipped**（199→209，+10）
- `spotless:check` → **BUILD SUCCESS，150 文件 0 needs changes**
- `ruff check src tests`（在 `agent/` 里）→ **All checks passed**
- strict mypy（`cd agent; uv run --project . --frozen mypy`）→ **9 errors in 4 files (checked 36)**，**全是既有问题**，新增 5 个模块零错误
- 契约测试 → **207 passed**（契约追加未破坏跨语言加载器）

## 1. C06.4 已完成的部分

| 子步 | 内容 | 关键文件 | 测试 |
| --- | --- | --- | --- |
| ① | HarnessRunner 骨架 + mock ModelClient，按 `agent-spec.md:40` 的预算 | `harness/actions.py`、`budget.py`、`model.py`、`runner.py` | `tests/unit/test_harness_loop.py`（26） |
| ② | 五个工具走**真实 MCP 客户端子进程**（不 import 工具函数） | `harness/mcp_client.py` | `tests/integration/test_harness_mcp.py` |
| ③ | 翻页/重试预算接进 run 预算（跨进程计数） | `mcp_client.py`、`tools/server.py` | 同上新增 3 例 |
| ④ | Case 侧 `POST /internal/v1/runs/{run_id}/tool-credential` | `internal/ToolCredential*.java`、`JwtCodec.issueToolCredential` | `ToolCredentialApiTest`（10） |
| ④b | 工具改用 **run 级**凭据而不再用环境变量 | `tools/credential.py`、`mcp_client.py` | `tests/integration/test_tool_credential.py`（10） |

细节（含每一步的真实失败与修法）在 `tasks/todo.md:1046` 起，**那才是权威记录**。

## 2. 下一步：C06.4⑤ 真 Java↔Python 端到端

**这是 C06.4 唯一没做的子步，也是最该先做的。** 今天所有"Harness 打工具"的证据都是 **真 MCP 子进程 + HTTP 桩上游**：工具边界是真的，**Java 是桩**。`scripts/e2e_refund_chain.py` 没改到把 Harness 接上，也没起工具 server。

最小诚实做法（不要一次做太大）：

1. 让 `scripts/e2e_refund_chain.py`（或一个新脚本）在起完 case/commerce 之后，用 `McpToolExecutor` 构造一个 `HarnessRunner`，**把 `case_base_url`/`commerce_base_url` 指向真的 Java 端口**（8083 / 8081），并且**装上 `credential_source`**（否则工具只会用配置 token）。
2. 用 `MockModelClient` 跑一轮：读 `get_order_context` + `get_shipment_trace` + `get_refund_status`，再 PROPOSE。断言的是**工具真的读到 Java 的数据**（金额、物流事件、退款状态），而不是桩的固定值。
3. 把这一轮的观测落成报告（`reports/c06-runs/` 的既有约定）。

**注意**：这条脚本要证明的是"工具与 Harness 能读真的 Java"，**不是**"run 被自动跑起来"——后者需要一个消费 PG 队列的 worker，交接文件把它归 C09，现在没有。

## 3. 明确未做（不要以为已经有了）

- **⑤ 真端到端**：见上。
- **Agent 没有 run 侧 worker**：`HarnessRunner` 是可被调用的类，没人从 PG 队列里取 run 来跑。"派发 → run 被跑 → 回调"这条线断在 Agent 侧。
- **工具凭据的 scope 没有被强制**：`ToolCredentialService` 铸造了 `commerce:read policy:read`，但 Java 的 `ServiceTokenFilter` 只校验 aud/签名，**不校验 scope**；Python `ServiceTokenVerifier` 的 `required_scope` 默认 `run:dispatch`，会把工具凭据当"scope 不符"拒绝。所以凭据目前只对 Java 的 `/internal` 路由有意义，而 Java 侧没有逐路由 scope 检查。**"凭据已实现" ≠ "权限已执行"。**
- **`credential_source` 没有被生产代码组合**：只有测试显式装它。
- 错误响应体仍是 FastAPI 的 `{"detail": …}`；`429 OVERLOADED` 无容量检查；`READ_OBSERVATION` 只做"读回本 run 已持有的观测"，**原文受限持久化未做**；Observation 落库未做。
- strict replay 属 C10，未做。
- Java 4 个 skipped（`CoreEventTransportSystemTest` 等）**不是绿的，是没跑**。
- 文档未补：`RESOLVEFLOW_TOOL_TRACE_PAGES`、`McpToolExecutor` 每次调用一个子进程的取舍、工具凭据"铸造但未强制"的现状。
- `scripts/verify.ps1 -Suite all-offline` 本次未运行。

## 4. 门命令（照抄，注意目录）

```powershell
# Python
uv run --project agent --frozen pytest agent/tests -q --basetemp='E:/Code/Agent+Backend/.pytest-tmp'
uv run --project agent --frozen ruff check agent/src agent/tests

# strict mypy —— 必须在 agent/ 目录里跑，见 §5
cd agent; uv run --project . --frozen mypy; cd ..

# Java（改完先 spotless:apply）
$env:JAVA_HOME = 'C:\Users\hjn\.jdks\jdk-21.0.12.1+1'
cd java; .\mvnw.cmd -B test; .\mvnw.cmd -B spotless:check; cd ..

# 聚焦
uv run --project agent --frozen pytest agent/tests/unit/test_harness_loop.py agent/tests/integration/test_harness_mcp.py -q --basetemp='E:/Code/Agent+Backend/.pytest-tmp'
cd java; .\mvnw.cmd -B -pl case-service -am test "-Dtest=ToolCredentialApiTest" "-Dsurefire.failIfNoSpecifiedTests=false"; cd ..
```

## 5. 已知陷阱（C06.4 新增的三条 + 沿用）

0. **最重要的一条，不是技术陷阱而是流程陷阱：验证过的提交要提交并推送，推送前问一次。**
   `tasks/handoff-c06.md:23-24` 写的是"**验证过的提交要尽快推到远端**；但**不擅自推送**，推送前需要用户点头"，
   `tasks/handoff-c052b3b.md:93` 写的是"工作区不可靠（本轮发生过两次静默回退）→ 验证过的提交要推送"。
   **C06.4 会话把这两句读成了"不要推送"，结果连提交都没做**，把 79 项（52 个新源码文件）全留在工作区——
   而本仓库在 2026-09-22/23 两次被会话之外的进程静默回退过，未提交的内容会真的消失。正确做法是：
   **做完并跑绿门之后先提交，然后问用户是否可以推送**；不要停在"没提交"这一步。

1. **pytest 必须有可写的 basetemp。** 本机沙箱下 `C:\Users\hjn\AppData\Local\Temp\pytest-of-hjn` 可能不可写（`PermissionError: [WinError 5]`，55 个 error），加 `--basetemp='E:/Code/Agent+Backend/.pytest-tmp'` 即可（`.pytest-tmp/` 已进 `.gitignore`）。**这不是仓库问题，别去改 conftest。**
2. **新增：`mvnw` 要在 `java/` 里跑**（`cd java; .\mvnw.cmd …`）。从仓库根跑会找不到该文件。
3. **新增：改为每次 `call_tool` 起一个工具 server 子进程后，任何"per run"的计数都不能留在那个进程里。** `tools/server.py` 的翻页计数靠 `RESOLVEFLOW_TOOL_TRACE_PAGES` 由 `McpToolExecutor` 传进去；新增同类状态时要走同一条路。
4. **沿用：strict mypy 必须在 `agent/` 里跑**，从仓库根跑不加载 `agent/pyproject.toml`，会报假的 Success。（本次已复查：`cd agent` 下 9 个既有错误。）
5. **沿用：反斜杠+A 可能被工具边界改写成 `+`。** 所有路径用正斜杠书写，写入后回读。
6. **沿用：`edit` 工具在带外写入后会拒绝**（"file changed since it was read"）——先重新 `read`；`spotless:apply` 与 `tasks/todo.md` 的长行插入都触发过它。
7. **沿用：测试库隔离**：per-test schema `t_<uuid16>`；Java case 用 Testcontainers `CaseDatabaseTest`（**`CaseServiceApplicationTest` 例外，它要真的 `resolveflow-mysql-1` 在 3306**）。
8. **沿用：`agent/tests/integration/` 是包**，导入桩写 `from tests.integration import stub_upstream`。
9. **沿用：mcp 2.2.0 的 API 与记忆不同**（`MCPServer` 不是 `FastMCP`；snake_case；`context.session` 每个请求都是新对象）。
10. **沿用：守卫类测试要"故意弄红"验证过才算数。** 本次做了两次：身份/URL 守卫（去掉 → 4 failed，还原后 SHA256 逐字节相同）与翻页预算（把 `trace_pages` 改回常量 0 → 1 failed，还原后 SHA256 相同）。

## 6. 端口（权威是 `scripts/e2e_refund_chain.py`）

| 服务 | 端口 |
| --- | --- |
| gateway | 8080 |
| **commerce-service** | **8081** |
| **case-service** | **8083** |
| Python Agent | 由 e2e 脚本动态取空闲端口 |
| RocketMQ | 9876 |
| Postgres / MySQL | 55432 / 3306 |

`tools/server.py` 的默认地址由 `agent/tests/unit/test_tool_defaults.py` 从 e2e 脚本**读出来**钉住。

## 7. 硬边界（`AGENTS.md`，别越）

单订单行全量模拟退款；同行最多一次成功退款；UNKNOWN 不释放、不换 ID 重付；Agent 无退款/审批/政策修改/跨主体读取权限；Java 拥有工单/授权/金额，Python 拥有 run；outbox 至少一次；外部网络调用不放长事务；迁移只追加。不提交密钥、不开未经确认的收费评测或公网部署。
