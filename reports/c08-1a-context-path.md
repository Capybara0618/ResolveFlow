# C08.1a 正式上下文路径收口（2026-09-26）

范围：`handoff-current.md` §2 的 C08.1a。承接[本轮审查修复](c08-review-fixes.md)的未提交工作树，
不重做其中任何修复。**C08.1 未勾完成**：live 模型适配、完整 manifest、候选引用验证、H1 均未做。

## 1. 起始事实（先量再改）

- 起始工作树：`reports/c08-review-fixes.md` 的未提交修复集（28 个已跟踪文件 + 若干未跟踪报告），全部保留未覆盖。
- 起始基线实测：`pytest tests` → **923 passed, 9 skipped**；`ruff check src tests` → 通过；
  `mypy`（strict，`agent/`）→ **9 errors / 4 files = 既有基线**。与修复报告一致，说明该修复集完整可用。
- `AgentScopeRunner.use_context_builder` 仍为 `False`，即"模型看到的输入"在生产路径上仍不是 `ContextPacket`。

## 2. 第 1 步：区分两种输入通道（handoff §2 C08.1a-1）

用只读探针（`tmp/probe-c08-1a-messages.py`，未纳入版本控制）对同一场景分别打印三条通道：

| 通道 | 含义 | 关闭开关 | 打开开关 |
| --- | --- | --- | --- |
| `conversations[turn]` | **模型实际收到的 messages** | C06.4 证据包（JSON 一坨） | 【P1·…】【P2·…】【P3·…】【P4·…】两层（system + user） |
| `sent_contexts[turn]` | 真正发出的 `ContextPacket` | `None` | `ContextPacket` |
| `packets[turn]` | **脚本读的结构化 view**（`context`） | 由 messages 反解的 JSON | run 的 `context`，**模型看不到** |

结论（回答"58 个红"那个悬案）：**翻默认今天一个测试都不红**。
先用"只翻开关"实测 → **928 passed, 9 skipped, 0 failed**（新增 5 例后）；迁移读取方式后再实测 → **930 passed**。
旧交接 §2 表中"适配器修好后 58 个红"在**当前工作树不再复现**：当时真正依赖 `packets` 的语义断言只有 2 处用
`input_text_of`，其余读 `packets` 的断言读的是两种形状**都**会填充的结构化 view，因此翻开关并不动摇它们。

同时确认 item 3 的内容在**显式开启**的正式路径上早已到达真实 messages：工具结果、`next_cursor`、
`NOT_FOUND` 错误、`READ_OBSERVATION` 回读窗口与 `next_offset` 均出现在 `conversations[1]`。

## 3. 第 2 步：正式路径收口（RED → GREEN）

按"先失败测试、再切正式路径、再迁移读取方式"执行。

1. **RED**：新增 `test_the_formal_runner_defaults_to_the_bounded_builder`（不传开关构造 run，断言默认即 P0–P4）
   → `pytest tests/integration/test_context_wiring.py` = **1 failed, 23 passed**，失败原因正是 `use_context_builder=False`。
2. **切换正式路径**：`AgentScopeRunner.use_context_builder` 默认 `False → True`；C06.4 证据包保留为
   **显式兼容路径**（调用方必须自己传 `False`），并把原来只读开关、从不跑循环的"默认未变"测试改为
   **真的跑一遍**旧路径（`test_the_legacy_evidence_packet_is_still_an_explicit_compatibility_path`）。
3. **迁移测试读取方式**：
   - `tests/conftest.py::input_text_of` 改为**读模型实际收到的 messages**（`conversations`），
     `packets` 仅作无会话时的兜底；`packet_of` 的文档改为"脚本视图"，因为它现在确实不是模型输入。
   - `test_harness_loop.py` 的注释纠正：翻开关**没有**让该测试变红，"读 `packets` 会红"的说法不成立。
   - `test_observation_read_loop.py`：回读断言从 `model.packets[1]["observations"]` 改为
     读 request（`read_observation` + 窗口文本 `LOST` 必须出现在模型收到的 messages 里）。
   - `test_harness_mcp.py` 两处：工具观察与 `NOT_FOUND` 错误改为在 request 中断言；哈希改为断言 run 自己的记录。
   - `test_policy_search_action.py`：引用成员（`rule_id`/`content_hash`）改为在 request 中断言。

**语义断言一处未删**：预算耗尽零新增调用、超额零工具执行、UNKNOWN 不返还预占、无进展、工具批次、
权限拒绝、错误 Observation 回传全部保留；改动只是读取路径与被主张的通道。

## 4. 第 3 步：补 P1「已确认动作」（C08.1a-3）

`docs/context-engineering.md:18` 规定 P1 = 当前诉求、**已确认动作**、最近问答；`ContextBuilder` 早已有 `history`
参数并被 builder 单测覆盖，但 **runner 从不传**。C06.4 下模型靠 SDK transcript 知道自己的动作，而该 transcript
已被本轮修复按规格移除（"不得在裁剪后追加 SDK hints/完整工具历史"），于是正式路径上模型**看不到自己做过什么**。

实现（有界，因为 P1 不可裁剪——`TRIMMABLE_LAYERS` 只有 P3/P4）：

- `context.py`：`CONFIRMED_ACTION_WINDOW = 4`、`MAX_ACTION_ARGUMENT_CHARS = 64`，附"为什么 P1 的窗口必须按构造有界"的说明。
- `sdk_runner.py`：`_GateAwareClient.note_confirmed_action()` 在 `gate.check()` **确认之后**记录（被拒的动作不算发生过）；
  `_confirmed_action_line()` 生成确定性行（kind + 工具/observation_id + 标量参数），**排除 `reasoning`/`summary`**：
  P1 永不被裁剪，模型自由文本既无界也不是证据（`:11` 不允许 MODEL_INFERENCE 因重复而升格）。
- 报文侧只传最后 4 条；完整序列仍在 outcome 的 `trajectory`。

测试：`test_a_confirmed_action_is_named_in_p1_of_the_next_request`（同时断言模型 reasoning **不**进 P1）、
`test_the_confirmed_action_window_keeps_an_untrimmable_layer_bounded`（6 次不同读 → P1 恰好 4 行，最旧的离开）。

## 5. 两处被重新划定边界的旧主张（**不是**删断言，是把通道说准）

1. **MCP 观察的"version and hash included"**：正式报文的 P2 行是 `[AUTHORITY source@version]`，P4 索引只有
   tool/observation_id/source_ref —— **渲染后的报文不含 `content_hash`**。因此把"模型看到了 hash"改为
   "request 里有内容与可引用来源/版本；hash 保留在 run 自己的 observation 记录里"（64 位断言）。
   **待决**：若 ProposalVerifier 或模型输入确需 hash，属 C08.1b 的协议决定，本轮不擅自改规格。
2. **本地读预算的位置**：`test_the_packet_tells_the_model_how_many_local_reads_it_has_left` 原读
   `model.packets[1]["budget"]`。正式路径下报文层次只有 P0–P4、**没有预算层**，所以"报文告诉模型剩余几次本地读"
   在正式路径上不成立。改为
   `test_the_budget_position_reaches_the_client_but_not_the_provider_request`：预算位置在交给 ModelClient 的
   **结构化 `context`** 里（有），**不在 provider request 里**（并断言不在），边界写明。
   **诚实记录**：这相对 C06.4 是一处行为变化——旧证据包把 `budget` 发给了模型，正式路径不发；依据是
   `docs/context-engineering.md:15-21` 的层次表与"Harness 负责预算/终止"的固定范围。

## 6. 最终验证（实际执行，工作目录 `agent/`）

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider` | **930 passed, 9 skipped, 1 warning，125.35 秒** |
| `.\.venv\Scripts\python.exe -m ruff check src tests` | **All checks passed** |
| `.\.venv\Scripts\python.exe -m mypy` | **9 errors / 4 files = 基线，零新增**（provider_stub 3、`_schemaio` 1、`fixtures` 1、`core_corpus` 4，均 no-any-return） |

测试数变化：923 → 930（**+7 例**：默认 1、旧路径显式跑 1、两个 message 断言各 2 参数、P1 动作 1、窗口上界 1）；
另有 1 例改名强化、1 例从"只读开关"改为"真的跑循环"。

改动文件（叠加在本轮未提交修复集之上，未提交、未推送）：

- `agent/src/resolveflow/harness/sdk_runner.py`（默认翻转；确认动作记录/渲染/有界 history）
- `agent/src/resolveflow/harness/context.py`（两个有界常量）
- `agent/tests/conftest.py`、`agent/tests/unit/test_harness_loop.py`
- `agent/tests/integration/test_context_wiring.py`、`test_observation_read_loop.py`、`test_harness_mcp.py`、`test_policy_search_action.py`

## 7. 未运行 / 未完成（不得据此宣称）

- **未跑**：Java 全量、`all-offline`、`spikes/agentscope` 测试、任何 live 模型调用。本轮只动 Python harness 与 agent 测试。
- **未完成**：C08.1b（冻结 HarnessManifest 落实、live ModelClient + `max_output_tokens` + usage 标 ESTIMATED、
  候选引用验证、H1 的 6 组配对真实模型证据）、C08.2（PG 待办 worker、callback_outbox、单执行者闭环）。
- **不得宣称**：真实模型自主性、C09 持久恢复、C10 严格隔离、"模型输入已由 HTTP 层验证"
  （本轮证明的是 ModelClient 收到的 messages，**不是**供应商 HTTP 包体；`context-engineering.md:41` 的
  provider 侧最终载荷/hash/供应商计数仍属 C08 适配）。

## 8. 下一步

C08.1b：先落实冻结的 `HarnessManifest`（当前 `manifest_id` 仍是政策派生标识），再做 live ModelClient 适配
（明确供应商/参数、强制 `max_output_tokens`、usage 未知标 ESTIMATED/UNKNOWN），随后候选引用验证。
`handoff-current.md` §2 C08.1b/c 的顺序不变。