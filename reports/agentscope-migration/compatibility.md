# AgentScope 迁移兼容报告 · AS01.1 + AS01.2（部分）

2026-09-25。本报告是 `docs/agentscope-migration.md:97` 要求的**技术门禁审阅材料**。**AS01.2 只完成了能力探针，未完成真实 PG 恢复关卡；AS01.3 未开始**，因此本报告不是 AS01 全部通过的结论，AS02 不得据此开工。

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

## 6. 失败窗口与快照形状（AS01.2 能力探针结果）

`docs/agentscope-migration.md:71` 把这一步的底线写得很清楚：未完成的 reply 必须能用**稳定调用账 + 已记录的模型/工具结果重建**，且"不能退化成从头重新调模型"；做不到就报最小复现，不许降低 H4。探针（`spikes/agentscope/tests/test_recovery_capability.py`，3 例）给出的结论是**混合的**：

### 6.1 可用的部分

| 能力 | 证据 |
| --- | --- |
| `AgentState` 可 JSON 往返 | `test_the_reply_state_is_serialisable_and_round_trips`：`model_dump_json()` → `model_validate` 后 `session_id`/`context`/`reply_context.cur_iter` 一致 |
| 快照可交给**另一个** Agent 继续 | `test_a_saved_state_can_be_handed_to_a_fresh_agent`：新 Agent 用同一 state 构建，`model.calls == 0`，上下文长度一致 |
| SDK 能识别"有未完成工具调用"的窗口 | `get_unfinished_tool_calls` / `get_awaiting_tool_calls` 在 `SUBMITTED` 无结果时返回该调用（探针断言非空） |
| 工具**不会**被重复执行 | 恢复时写回的是**已记录**的结果，`executions == ["get_order_context"]` 不增 |
| 工具结果存放在**助手消息内部** | `get_unfinished_tool_calls` 按 block id 在 `context[-1]` 内匹配，不是独立消息 |

### 6.2 恢复的代价：一次**恢复推理轮**，而不是重发被中断的调用（**我先前判断错了一次，此处更正**）

`test_resuming_an_interrupted_reply_costs_another_model_call` 断言的是**实际行为**：把已记录的工具结果写回 context 再 `reply(None)`，会多一次模型调用（2 → 3），且那第三次调用的输入里已含工具结果。

我最初把这条读成"恢复退化成从头重新调模型"并写成阻塞点——**这个结论是错的**，探针自己的 docstring 也提示了要复验 API。复验结果：

- `Agent.reply` 的文档说明输入可以是 `UserConfirmResultEvent` / `ExternalExecutionResultEvent`，语义是 *"continue from the outside interaction required by the previous reply"*；`None` 是 *"nothing new to feed in"*。所以**正确用法是传 `ExternalExecutionResultEvent`，不是 `None`**。
- 用 `ExternalExecutionResultEvent(reply_id=…, execution_results=[已记录结果])` 复验：**仍然会多一次模型调用**（`RECOVERY-DIAG calls: first reply=2, after continuation=3`）。

**为什么这不构成 6.2 原先声称的阻塞**：一次工具调用在 ReAct 里逻辑上就是"reason → act → reason"。工具结果回来之后那一轮推理**是循环的下一步**，不是重发被中断的那次调用。`docs/agentscope-migration.md:71` 禁止的是"从头重新调模型"（重发整个步骤），而探针显示：**工具没有被重新执行**，**已记录的结果被原样采用**，被中断的那次模型调用**没有被重发**。

### 6.3 真正剩下的风险（比 6.2 原判断小，但不是没有）

1. **恢复要花一次推理轮 = 一次计费调用**。若 run 已经用尽 12 次模型预算，恢复就无法完成——而崩溃前后正是预算最容易用尽的时刻。`docs/agentscope-migration.md:50` 要求每次调用先计费，所以这笔必须显式记账（例如标成 `RECOVERY_TURN`），而不是假装免费。**这是需要用户决定的取舍**：是否为恢复预留预算、或允许一次豁免（后者会轻微放宽 H4，我不建议擅自做）。
2. **未验证**：`ExternalExecutionResultEvent` 的 `reply_id` 与快照里 `reply_context.reply_id` 不一致时 SDK 的行为；跨进程（真 PG、新连接）恢复；旧 fence 写快照/终局被拒；UNKNOWN 成本记账；`call_id` 复用不重复结算。**这些都没有探针，因此本子步只回答了"恢复路径存在且语义正确"，没有完成 AS01.2 的验收。**

## 6bis. AS01.2 未完成的部分（不得读成通过）

真实 PG 关卡**没有做完**：schema/跨进程与跨连接恢复、旧 fence 写快照与终局被拒、预算与 deadline 不重置、UNKNOWN 成本记账、`call_id` 复用不重复结算——**都还没有探针**。也没有据任何一条勾 C09/H4。

## 6ter. 给审阅者的处置建议

1. **接受"恢复 = 一次恢复推理轮"，并显式记账**（建议）：由调用账把该次标为恢复轮、照常预占预算；再决定是否为恢复预留额度，或让 AS01.2 证明"预算耗尽时仍能恢复"另有出路。
2. **继续 AS01.2 的真实 PG 部分**：把上面 6.3 第 2 条的五项做成真 PG/跨进程探针。这是规格原文要求的收尾，也是进入 AS02 的前置。
3. **向上游确认**（可选）：`ExternalExecutionResultEvent` 是否是官方推荐的恢复入口，以及是否支持"零额外推理调用"的续接。若不是，第 1 条就是最终形态。

## 6bis. 用户决定（2026-09-25）与实现

两条决定已落进 spike 代码并有测试，不再是建议：

**决定 1：恢复预留额度，并把恢复轮**显式记 `RECOVERY_TURN` 照常预占**。** 实现 `spikes/agentscope/src/resolveflow_spike/adapter.py::RecoveryAllowance`，测试 `tests/test_recovery_budget.py`（6 例）。

- 语义：run 保留 `recovery_model_calls`（默认 2）的额度。普通预算**不增长**；恢复轮**跳过 model-call 上限**（因为 run 到恢复时按定义已在该上限上），但**仍然强制**单步 token 上限、累计 token 上限与 deadline，**并且计入 run 自己的 spend**——所以台账与 provider 实际被请求的次数一致（`agent-spec.md:40`）。
- **实现时被自己的测试抓到一个设计错误**：第一版让 `note_recovery_turn` 直接调 `reserve_model_call`，于是它**永远不可能成功**——普通预算已耗尽正是需要恢复的前提。测试 `test_a_recovery_turn_is_allowed_after_the_ordinary_budget_is_spent` 立刻红了。改为"跳过 model-call 上限、其余照查"后转绿。
- 额度**有限且不是重置**：用完即拒并记录原因，是否 fail/escalate 由 run 的属主决定（`agent-migration.md:69` 禁止静默续期）。

**决定 2：MCP 走本项目自带的 mcp 2.2.0 客户端。** 测试 `test_the_projects_own_mcp_client_is_the_path_agentscope_uses` 钉住这个边界：AgentScope 只拿"已经是普通 Python 对象"的工具，spike 的适配层源码里**不出现 `agentscope.mcp`**。理由见 §3 的 4 处 camelCase 缺口 + `agent-migration.md:30` 要求保留官方 stdio 路径（`harness/mcp_client.py` 本就是那条路，且有真 MCP 测试）。AS02 因此不需要等上游修复。

## 6quater. AS01.2 真实 PG 关卡结果（已完成）

实现：`spikes/agentscope/src/resolveflow_spike/recovery_store.py`（fence 保护的 run 快照 + 稳定调用账，真 PostgreSQL，spike 自己的临时 schema）；测试 `tests/test_recovery.py`（8 例）。**未改 `agent/` 生产代码或依赖锁。**

| 要求 | 探针 | 结果 |
| --- | --- | --- |
| 结果已落库而快照未推进 → 复用且不重复计费 | `test_a_saved_response_is_reused_and_not_charged_twice` | 通过：`record_response` 后不 `advance_snapshot`，新 worker 读回**逐字相同**的响应；恢复前后 `spend` 不变 |
| 未落库窗口记 UNKNOWN、可重试、成本保留 | `test_a_call_without_a_saved_response_is_unknown_and_retryable` | 通过：`record_request` 落 `UNKNOWN` 且 `response IS NULL`；`recorded_response` 返回 `None`（**不伪造答案**）；重试**复用同一 `call_id`**（行数仍为 1）后转 `SAVED` |
| 旧 fence 写快照/终局被拒 | `test_a_superseded_worker_cannot_advance_the_run` | 通过：旧的 fence 写 snapshot / spend / response **三者都抛 `StaleFenceError`**，且什么都没落；当前 fence 仍可推进（证明拒绝的是"所有权"而非"run 坏了"） |
| 预算/deadline 不重置 | `test_a_resume_does_not_reset_the_budget_or_the_deadline`、`test_the_run_budget_still_bounds_the_model_calls_after_a_resume` | 通过：新 claim 即使传不同 budget 与 `None` deadline，读回仍是**原 deadline 与原 budget**，`spend` 保持；用记录的 budget 重建 guard 恰好允许 12 次 |
| **跨连接/跨进程**恢复 | `test_the_snapshot_is_readable_from_a_separate_process` | 通过：**子进程**用自己的连接读同一 schema 的快照，`AgentState.model_validate` 成功且上下文长度一致 |
| 从持久状态重建 Agent | `test_a_rebuilt_agent_continues_from_the_persisted_state` | 通过：重建**不调用模型**（`model.calls == 0`），上下文与服务端一致 |

**一处我自己写错并当场修掉的实现缺陷**：第一版 `_require_fence` 自己开一个连接查 fence，然后**另一个连接**写快照——这正是 `agent-migration.md:66` 点名的禁止做法（"不能先查fence再另开连接写"）。已改为把 fence 检查放进**每个写事务内部**、作为第一条语句，并 `SELECT … FOR UPDATE` 取行锁。

**仍然未做**：AS01.3 禁网络回放；`ExternalExecutionResultEvent` 的 `reply_id` 与快照不一致时的行为；放弃/取消后迟到结果的隔离（属 C09）；生产 `RunStore`/worker 接入（属 C09，本步只证明形状与要求可满足）。

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
