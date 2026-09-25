# AgentScope 迁移兼容报告 · AS01 全部（AS01.1 / AS01.2 / AS01.3）

2026-09-25。本报告是 `docs/agentscope-migration.md:97` 要求的**技术门禁审阅材料**。**AS01.1、AS01.2（含真实 PG 关卡）、AS01.3 均已完成**，技术门禁请见 §8；AS02 的开工前提是用户审阅本报告。

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

## 6quinquies. AS01.3 禁网络 strict 回放探针（已完成）

实现：`spikes/agentscope/src/resolveflow_spike/replay.py`（`ReplayPack` + `ReplayModel` + `block_network`）；测试 `tests/test_replay.py`（8 例）。**未改 `agent/` 生产代码或依赖锁。**

| 要求（`agent-migration.md:78`） | 探针 | 结果 |
| --- | --- | --- |
| **同一** AgentScope+Harness 执行逻辑 | `test_a_recorded_trajectory_replays_with_the_same_actions`、`test_the_replay_uses_the_same_guards_as_the_live_loop` | 通过：回放跑的是**同一个 `Agent` 与同样两个中间件**，只有模型与工具被记录替换；断言的是**动作序列**（`replay_actions == recorded_actions`）而不是终态字符串。守卫在回放中照样生效：非法工具 `issue_refund` 仍被拒（工具执行 0 次），模型调用照样计入预算 |
| **缺记录明确失败** | `test_a_missing_record_fails_explicitly`、`test_an_unknown_block_type_is_refused_rather_than_skipped` | 通过：空 pack 触发 `ReplayExhaustedError`（`holds 0 model responses`），且**没有任何工具被**执行；未知 block 类型**拒绝而不是跳过**（跳过会让回放悄悄丢掉轨迹的一段却仍报"一致"） |
| **网络被真实阻止** | `test_the_network_is_blocked_at_the_process_level`、`test_a_replay_runs_with_the_network_blocked` | 通过：`socket.create_connection` 被替换为抛 `OSError`，**回放全程 attempts == []**（不只是"没连上"，而是**根本没尝试**） |
| **业务写被真实阻止** | `test_a_replay_opens_no_database_and_writes_nothing` | 通过：回放模块**不 import** psycopg/urllib/httpx/requests/recovery_store（按 import 语句检查，不是子串——第一版用子串时被自己的 docstring 里的 "requests" 误伤）；pack 是唯一产物且在 `tmp_path` 内 |
| 稳定 `call_id` 可配对 | `test_the_tool_call_ids_in_the_pack_are_the_ones_the_loop_used` | 通过：pack 按**工具调用 id** 键控观察结果，而不是位置（位置键是更弱的身份，增删/重排后会"配错答案"） |

**过程中真实的失败**：① 我把 `socket.socket.connect` 也替换了，结果**把 asyncio 自己搞坏**——Windows 的 proactor 事件循环启动时要建 socket pair，回放还没开始就 `AttributeError: 'ProactorEventLoop' object has no attribute '_ssock'`。改为只封 `socket.create_connection`（客户端真正调用的那个）后正常，理由写进了函数注释。② 用子串检查"回放不许碰网络/数据库"时，被模块 docstring 里的 "the requests it was given" 误判；改为按 **import 语句**检查。③ 守卫测试的模型调用预算给了 1，而拒绝会被回喂给模型多走一轮（AS01.1 已记录的行为），导致该测试因预算而非因守卫失败；改为 2 并把原因写进注释。

**命令与结果（都真跑）**：`uv run --project spikes/agentscope --frozen pytest spikes/agentscope/tests -q` → **36 passed**；`ruff check src tests` → **All checks passed**；`mypy`（strict，**14 源文件**）→ **Success: no issues found**。

**仍然未做**：5 个 golden packs 与全部 H5 属 **C10**（本步只验证一条完整顺序轨迹 + 缺记录反例可行，正如 `agent-migration.md:79` 所限定）；未据此勾 C10/H5；生产 `RunStore`/worker 接入属 C09。

## 7. 未验证 / 未运行（不得读成通过）

- **AS01.2、AS01.3 未执行**：无真实 PG 恢复探针、无禁网络回放探针。
- **未用 live 模型**：全部为 mock。H1 自主性未验证，`docs/agentscope-migration.md:62` 要求不得把 mock 通过写成 live。
- **终止语义（PROPOSE/ASK_CUSTOMER/ESCALATE）未映射**：本子步只覆盖预算与权限两个硬拦截；`docs/agentscope-migration.md:37` 要求的六动作映射测试属 AS02。
- **自动上下文压缩、tool_retries_limit、max_retries 未做处置**：只记录默认值与风险（§4）。
- **telemetry/OTLP 未验证**：基础依赖含 OTLP exporter，未测是否外发。
- **`mcp` 4 处缺口只验证了 3 处的修正效果**，#4（`McpError`）未验证。
- **`agentscope.mcp` 的 `enable_tools`/`disable_tools` 未使用**：它是"SDK 侧也不放宽白名单"的可选加固点。
- 本报告未运行 `scripts/verify.ps1`、未跑 Java 门；AS01.1 不改 Java 与生产依赖，无此需要。
- ~~C06.4⑤ 真实 Java 工具联调仍是**未提交、未跑**状态~~：**已过时**。C06.4⑤ 已于 AS00 接管并跑通（`reports/c064-e2e/20260925-155214-e2e-harness-java-tools.txt`），AS02.3 重跑于 `reports/c064-e2e/20260925-161114-e2e-harness-java-tools.txt`。保留此条只为不改写历史判断。

## 8bis. AS02.3 安全子步：Java 侧强制 scope（2026-09-25，已完成）

**这条不是 AS01 的一部分**，记在这里是因为它关闭的正是 §7 里那条"凭据已实现 ≠ 权限已执行"的欠账，而那条欠账最初就是在这份文档所描述的迁移过程中被发现的。

| 项 | 内容 |
| --- | --- |
| 缺口 | `ToolCredentialService` 铸造 `commerce:read policy:read`，`docs/core-contracts.md:74` 把 scope 写进凭据绑定，而 Java 的 `ServiceTokenFilter` **只校验 aud/签名**、不读该 claim |
| 危害（为什么值得单独一步） | 不是"少一个检查"，是**命名与事实错位**：任何读到"凭据已实现"的人都会合理地推断权限已执行 |
| 处置 | 词汇提到 `shared-kernel` 的 `ServiceScopes`（跨进程词汇，先例 `CoreTopicNames`）；`ServiceIdentity` 真正带 `scope`（逐 scope **精确相等**，防 `commerce:read:all` 满足 `commerce:read`）；Commerce 内部读要 `commerce:read`；Case 的 `policy-manifest` 与 `/internal/v1/policies` 要 `policy:read`；403 `FORBIDDEN_SCOPE`，错误体**只报所需 scope、不回显已持有 scope** |
| 为什么 Case 侧"按路径段"而不是前缀 | 三个 controller 同挂 `/internal/v1/cases`；前缀规则会把"读钉住的策略"和"读工单证据"变成同一权限。另三条路（取凭据、回调、证据读）**显式不加**并写明理由——取凭据是 run 获取权限的路，对它要求 scope 等于要求它还没有的东西 |
| 强制力的证明 | 反例而不是正例：8 个 Commerce 例中有 `policy:read` 单持被拒、`commerce:read` 单独被拒、用户令牌被拒、伪造签名 401；Case 侧 7 例同构。**变异验证**：把 `requiredScope` 改成不匹配后 `CaseScopeEnforcementTest` 立刻 2 例转红（`expected 403 but was 200`），证明护栏可红而非恒绿 |
| 第一版测试的 bug（值得记住） | `@AutoConfigureRestTestClient` 单独使用**不换掉** `@SpringBootTest` 的 MOCK 环境，而 MOCK **不建容器、不跑 servlet filter**，请求直接进 controller。首轮 4 个反例（含**伪造签名**）全部返回 `200`，即当时根本没在测 scope。加 `webEnvironment = RANDOM_PORT` 后才真的在测。**若只写正例，这个错误会以全绿交付。** |
| 真实端到端 | `20260925-161114-e2e-harness-java-tools.txt`：凭据读到 manifest（200），同路由只带 `commerce:read` 的同形令牌拿到 `403 FORBIDDEN_SCOPE`，`message='this route requires the policy:read scope'`（未回显已持有 scope）；五个工具在强制开启后仍全部成功。**原 driver 用无 scope 的部署令牌读 manifest —— 它本身就在依赖这个缺口**，已改为"先取凭据、再用凭据读" |
| 仍未关闭 | **无**（两侧均已关闭）。**但 Python 侧目前还没有任何路由要求这两个 scope**——本步修的是"当路由提出要求时判定是否正确"，不是"已经有一条这样的路由"；真实消费方随 C07/C08 落地，届时按路由传 `required_scope` 即可 |

### 8ter. AS02.3 安全子步 · Python 侧：scope 是集合，按路由提问（已完成）

Java 的过滤器强制路由的 scope；`ServiceTokenVerifier` 是这条规则在 Python 的一端，而它错在**没有任何东西会发现**的地方：`scope != self._required_scope` 把**整个 claim 串**与一个 scope 做相等比较。工具凭据的 claim 是 `commerce:read policy:read`（RFC 6749 的空格分隔），所以 Python 侧一旦有路由要求其中任一 scope，这个凭据**永远不可能满足任何要求**——多带一个 scope 反而让 token 对所有单 scope 要求失效。

| 项 | 内容 |
| --- | --- |
| 判定 | `required_scope in scope.split()`：空格分隔后的**逐 scope 精确成员**判定（与 Java `ServiceIdentity.hasScope` 同规则，`commerce:read:all` 不满足 `commerce:read`）；present-but-empty 的 claim 仍按畸形拒绝，不读成"没声明 scope" |
| 接口 | scope 从**构造期属性**改为**按调用的参数**。原先 `app.state.token_verifier` 是全 app 共享的一个实例，却带着"某一个路由的要求"，其余路由的要求**无法从路由本身读出**。构造期参数**删除**而非保留——留着会让人以为它还在生效 |
| 省略与显式 | 省略 `required_scope` = `run:dispatch`（保持原常用语义）；`None` = 该路由**有意**不要求 scope（回调路由） |
| 先写失败测试 | 12 例，其中 9 例在接口存在前以 `TypeError` 失败，确认裂缝真实存在 |
| 强制力的证明 | 变异：把判定改回 `scope != required_scope` → **恰好 3 例转红**；改回即绿 |
| 顺带清掉的两处遗留 | ① `runtime/runs.py` 的 `VerifiedCaller.require_run_scope` 用**一模一样**的错误比较，且**零调用**、其 `RunScopeError` **从未被 raise**——不与它修成第二份实现，而是删除并写明"检查属于 token 验证处"；② `runtime/delivery.py` 注释称"Case 的过滤器不校验 scope（`verifyAsService` 只读 `sub`）"——本轮之后**这句是假的**，连同零引用的 `CALLBACK_SCOPE = ""` 一并改掉 |
| 结果 | `pytest tests` → **791 passed, 9 skipped**（基线 779，+12 例，无退化）；ruff clean；strict mypy 仍是既有 9 个错误；`-Suite all-offline` PASSED |

## 8. 给审阅者的建议

1. **可以进 AS01.2**：预算与权限两个硬拦截已可用，且复用的是项目自己的守卫；MCP 的缺口有明确的两条出路，不阻塞恢复/回放探针（那两步不依赖 AgentScope 的 MCP 客户端）。
2. **AS02 需要先定两件事**：(a) MCP 走"自带客户端 + 普通函数工具"（推荐）还是等上游修 4 处；(b) 显式关闭 `max_retries`、自动压缩、并把 `tool_retries_limit` 改成本项目的 2。
3. **不要把本报告读成"框架已可用"**：唯一循环的替换（AS02.2）还没做，终止语义没映射，恢复与回放没验证。
