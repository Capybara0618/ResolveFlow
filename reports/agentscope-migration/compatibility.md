# AgentScope 迁移兼容报告 · AS01.1

2026-09-25。本报告是 `docs/agentscope-migration.md:97` 要求的**技术门禁审阅材料**的 AS01.1 部分：版本与来源、实际 API 拦截表、动作映射依据、失败窗口，以及真实执行过的命令与结果。**AS01.2（真实 PG 恢复）与 AS01.3（禁网络回放）尚未执行**，因此本报告不是 AS01 全部通过的结论，AS02 不得据此开工。

代码位置：`spikes/agentscope/`（独立锁与独立 venv，未改 `agent/pyproject.toml`、未改 `agent/uv.lock`）。

## 1. 版本与来源（已核实）

| 项 | 值 | 依据 |
| --- | --- | --- |
| SDK | `agentscope==2.0.8` | PyPI JSON API：`info.version = 2.0.8`，`requires_python >= 3.11` |
| 2.x 已发布版本共 11 个 | `2.0.0 … 2.0.7.post1, 2.0.8` | 同上；未使用任何 dev/1.x |
| Python | 3.12.13 | `spikes/agentscope/uv.lock` 实解 |
| 与现有锁的交集 | `pydantic 2.13.5`、`httpx 0.28.1`、`fastapi 0.141.1`、`psycopg 3.3.5` 均按 `agent/uv.lock` 的版本解析成功 | 见 §2 |

`agentscope` 的**基础依赖**里包含 `opentelemetry-api/sdk/exporter-otlp/semantic-conventions`（非可选 extra）。`docs/agentscope-migration.md:78` 要求 strict 回放禁用 telemetry，因此 **AS01.3/AS02 必须显式关闭 OTLP 导出并用进程级断网证明**；本子步未验证 telemetry 是否会自动外发，列为未验证项。

## 2. 依赖冲突：`mcp`（**已确认，非猜测**）

`agentscope==2.0.8` 声明 `mcp<2.0.0`；本项目 `agent/uv.lock` 锁 `mcp==2.2.0`，且五个工具是真实 2.2.0 stdio server（C06.2b）。

不加处理时 `uv lock --project spikes/agentscope` **直接失败**：

```
× No solution found when resolving dependencies:
╰─▶ Because agentscope==2.0.8 depends on mcp<2.0.0 and your project depends on
    agentscope==2.0.8, we can conclude that your project depends on mcp<2.0.0.
    And because your project depends on mcp==2.2.0, we can conclude that your
    project's requirements are unsatisfiable.
```

处置（`docs/agentscope-migration.md:89` 允许的"不改变 stdio 线协议的隔离适配"）：spike 的 `pyproject.toml` 用 **`[tool.uv] override-dependencies = ["mcp==2.2.0"]`**，只作用于 spike 自己的锁。没有降级 `mcp`：降级会让工具跑在本项目任何部分都不使用的主版本上，而 `agent/` 无法跟随（C06.2b 的 server 写的就是 2.2.0 的 `MCPServer` API）。

**override 只改解析结果，不改库在运行时的行为**，所以下面用真实探针测它到底能不能用。

## 3. mcp 1.x / 2.x 不兼容：4 处，已定位到行（**最小复现**）

用 AgentScope 自己的 `MCPClient` 连**本项目真实的** `python -m resolveflow.tools.server`（mcp 2.2.0）时逐个暴露：

| # | 位置 | 读的字段 | mcp 2.2.0 的实际字段 | 后果 |
| --- | --- | --- | --- | --- |
| 1 | `agentscope/tool/_adapters.py:261` | `tool.inputSchema` | `input_schema` | **崩溃**：`AttributeError: 'Tool' object has no attribute 'inputSchema'`（握手已成功，适配第一个工具时炸） |
| 2 | `agentscope/tool/_adapters.py:273-274` | `tool.annotations.readOnlyHint` | `read_only_hint` | **静默错误**：`hasattr` 为假，每个工具都被当成"非只读"，权限判断失去依据 |
| 3 | `agentscope/tool/_adapters.py:354` | `result.isError` | `is_error` | **崩溃**：只在真正调用工具时才触发（修复 #1 后才暴露）。注意 `isError` 在 mcp 2.x 里只是 pydantic 的**校验别名**（`CallToolResult.model_config` 用 `alias_generator=to_camel`），不是属性，无法通过给它赋值来补 |
| 4 | `agentscope/tool/_toolkit.py:343` | `mcp.shared.exceptions.McpError` | `MCPError` | **崩溃**：`AttributeError: module 'mcp.shared.exceptions' has no attribute 'McpError'`（在工具调用的异常兜底路径上） |

另有 `agentscope/workspace/_gateway_client.py:105,115-116` 是 #1/#2 的同源副本（AgentScope 的 workspace gateway，本项目不用）。`agentscope/app/channel/_dingtalk/_openapi.py:251` 的 `isError` 是阿里钉钉集成的自有 JSON key，与本议题无关。

### 证据与结论边界

- `tests/test_mcp_compat.py::test_agentscope_mcp_handshake_succeeds_but_tool_adaptation_breaks` **断言这个失败**（`pytest.raises(AttributeError, match="inputSchema")`）。红着记录，是为了让"pin 的实际代价"可复查，而不是日后重新当谜题发现。
- `tests/test_mcp_compat.py::test_a_two_attribute_fix_makes_agentscope_see_the_whitelist` 用 `monkeypatch`（进程内，**不改 site-packages**）修正 #1/#2/#3 后跑通：握手成功、看到五个工具（AgentScope 命名空间为 `mcp__resolveflow-tools__<工具名>`）、`call()` 返回本项目的 Observation，且桩上游确实收到了 `/context` 读取。
- 因此结论是**"字段名层面的适配缺口"**，不是协议或架构不兼容：`mcp__` 命名空间、schema、`call()`、结构化结果在改对字段名后都工作。
- **但这不是"AgentScope 可以按原样使用 `mcp` 2.2.0"的证据。** 4 处里 #1/#3/#4 会让 MCP 工具路径直接抛错，只有 2 处（#1/#2）在探针里被证明可修，#4 未验证修复效果。**AS02 的二选一**：(a) 上游修这 4 处或用带该补丁的 pin 版本；(b) 继续用本项目自己的 mcp 2.2.0 客户端（`harness/mcp_client.py`，已有真 MCP 测试），AgentScope 只拿到"已经是普通 Python 函数"的工具。**推荐 (b)**，因为它不依赖第三方修复进度，且 `docs/agentscope-migration.md:30` 本来就要求 MCP 适配保留官方 stdio 路径。

## 4. 实际 API → 拦截点 → 测试（`docs/agentscope-migration.md:47` 要求的表）

| 我的约束 | AgentScope 拦截点（已从 2.0.8 源码核实） | 测试 | 结论 |
| --- | --- | --- | --- |
| 每次模型请求前检查 run/fence/deadline 并计 attempt | `MiddlewareBase.on_model_call(agent, input_kwargs, next_handler)` | `test_the_model_budget_stops_the_loop_and_the_provider_is_not_called_again` | **可用**：预算耗尽后 provider 调用次数=2（预算值），第三次被拒且 `guard.spend.model_calls==2` |
| 输入计数覆盖 system+messages+**工具Schema** | `ChatModelBase.count_tokens(messages, tools)` —— 源码末段会把 `json.dumps(tools)` 计入 | `test_the_budget_counts_the_tool_schemas_and_prompt_not_only_the_new_packet` | **可用**：60 字段 schema 下计入 >1000 token |
| 单步上限，且拒绝发生在网络调用之前 | 同上 `on_model_call` | `test_a_single_oversized_request_is_refused_before_the_provider_sees_it` | **可用**：`step_input_tokens=1` 时 `model.calls==0` 且未计账 |
| 动作白名单/写工具/未知工具拒绝，非法动作⇒**工具执行次数为 0** | `MiddlewareBase.on_check_permission(agent, input_kwargs, next_handler)`，`input_kwargs` 含 `tool_call`/`tool`/`tool_input`（`_agent.py:2393`） | `test_an_illegal_tool_action_never_reaches_the_tool_body`、`test_a_legal_read_still_runs_and_the_illegal_one_in_the_same_batch_does_not`、`test_an_unknown_tool_name_is_refused_the_same_way` | **可用**：工具自计数为 0；白名单从项目 `actions.py` 解析（`test_the_whitelist_came_from_the_projects_own_abi_module` 防止白名单读空导致断言空转） |
| 拒绝后不得继续执行同批后续工具 | 同上 | 同上（合法读在前、写工具在后，写工具未执行） | **可用** |
| 终止后不得自动补一次模型调用 | `ReActConfig.stop_on_reject`（默认 `False`） | **未测** | **未验证**：探针显示拒绝会被回喂给模型并多走一轮（2 次调用）。"终止"语义（PROPOSE/ASK/ESCALATE）属 AS02 的动作适配 |
| 只允许一层重试 | `ChatModelBase.__init__(max_retries=3)` **默认 3** | 未直接测；`ScriptedModel` 显式设 0 | **必须显式设 0**：默认会让 SDK 在预算钩子**之下**重试，一次预占对应三次 provider 请求，直接违反 `docs/agent-spec.md:40` |
| 预算不足不得发起网络调用 | 同 `on_model_call` | 同上 | **可用** |
| 上下文不得被自动摘要改写 | `ContextConfig.trigger_ratio=0.8`、`compression_prompt`/`summary_template`、`compression_tool_enabled=False`、`tool_result_limit=50000` | **未测** | **未验证且必须处理**：`docs/agentscope-migration.md:52` 禁止生成式改写关键事实。AS02 必须关闭压缩或证明它在 `trigger_ratio` 内不触发 |
| 工具重试上限（本项目 ≤2） | `InjectionConfig.tool_retries_limit=3` **默认 3** | 未测 | **必须显式改**为本项目的 2，否则 SDK 自带的"同参数重试提示"会超出项目上限 |

## 5. 真实执行过的命令与结果

```powershell
# 独立锁（不改生产锁）
uv lock --project spikes/agentscope                        # 无 override 时失败（见 §2）；加 override 后 Resolved 108 packages
uv sync --project spikes/agentscope --frozen               # exit 0；agentscope 2.0.8 / pydantic 2.13.5 / httpx 0.28.1 / Python 3.12.13
uv run --project spikes/agentscope --frozen pytest spikes/agentscope/tests -q --basetemp=E:/Code/Agent+Backend/tmp/pytest-basetemp-as01
# -> 9 passed
```

| 文件 | 作用 |
| --- | --- |
| `spikes/agentscope/tests/test_mcp_compat.py`（2 例） | §3：红着的失败复现 + 修正后跑通 |
| `spikes/agentscope/tests/test_control.py`（7 例） | §4：预算硬拦截与权限硬拦截，走真实 SDK 循环 |
| `spikes/agentscope/src/resolveflow_spike/adapter.py` | 两个中间件：`BudgetMiddleware`、`RefusingPermissionMiddleware` |
| `spikes/agentscope/src/resolveflow_spike/stub_upstream.py` | spike 自带的 Case/Commerce 桩 |

**复用而非重写**：中间件调用的是项目自己的 `resolveflow.harness.budget`（`BudgetGuard`/`RunBudget`/`BudgetExhaustedError`），白名单从项目自己的 `harness/actions.py` 解析。`tests/conftest.py` 把 `agent/src` 放进 `sys.path`，因此本报告的结果**依赖当时的工作树**（`agent/src` 修订见 §7）。

## 6. 失败窗口与快照形状（供 AS01.2 使用，本子步未验证）

- AgentScope 的循环是**异步**的，`Agent.reply()` 是协程且自己消费事件流；本项目的 `HarnessRunner`/`McpToolExecutor` 是同步的（后者用私有事件循环+工作线程桥接）。AS02 必须明确"哪一侧拥有事件循环"，否则会得到两个循环或死锁。
- `AgentState` 是可传入的对象，`ContextConfig` 有 `summary_schema`，说明 SDK 侧确实有可序列化状态；但**"能存"不等于"受 fence 保护的恢复"**（`docs/agentscope-migration.md:58`）。AS01.2 要证明的是：响应已落库而快照未推进时按原 `call_id` 复用、未落库窗口记 UNKNOWN、旧 fence 写快照被拒、预算/deadline 不重置。**本报告不对这些作任何结论。**

## 7. 未验证 / 未运行（不得读成通过）

- **AS01.2、AS01.3 未执行**：无真实 PG 恢复探针、无禁网络回放探针。
- **未用 live 模型**：全部为 mock。H1 自主性未验证，`docs/agentscope-migration.md:62` 要求不得把 mock 通过写成 live。
- **终止语义（PROPOSE/ASK_CUSTOMER/ESCALATE）未映射**：本子步只覆盖预算与权限两个硬拦截；`docs/agentscope-migration.md:37` 要求的六动作映射测试属 AS02。
- **自动上下文压缩、tool_retries_limit、max_retries 未做处置**：只记录默认值与风险（§4）。
- **telemetry/OTLP 未验证**：基础依赖含 OTLP exporter，未测是否外发。
- **`mcp` 4 处缺口只验证了 3 处的修正效果**，#4（`McpError`）未验证。
- **`agentscope.mcp` 的 `enable_tools`/`disable_tools` 未使用**：它是"SDK 侧也不放宽白名单"的可选加固点。
- 本报告未运行 `scripts/verify.ps1`、未跑 Java 门；AS01.1 不改 Java 与生产依赖，无此需要。
- C06.4⑤ 真实 Java 工具联调仍是**未提交、未跑**状态（见 `tasks/todo.md` AS00 记录），与本 spike 相互独立。

## 8. 给审阅者的建议

1. **可以进 AS01.2**：预算与权限两个硬拦截已可用，且复用的是项目自己的守卫；MCP 的缺口有明确的两条出路，不阻塞恢复/回放探针（那两步不依赖 AgentScope 的 MCP 客户端）。
2. **AS02 需要先定两件事**：(a) MCP 走"自带客户端 + 普通函数工具"（推荐）还是等上游修 4 处；(b) 显式关闭 `max_retries`、自动压缩、并把 `tool_retries_limit` 改成本项目的 2。
3. **不要把本报告读成"框架已可用"**：唯一循环的替换（AS02.2）还没做，终止语义没映射，恢复与回放没验证。
