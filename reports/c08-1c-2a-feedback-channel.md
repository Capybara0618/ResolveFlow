# C08.1c-2a 反馈通道：harness 要告诉模型的话必须真的发出去

日期：2026-09-26｜状态：**已完成并实测**｜本步是 C08.1c-2「可修复一次」的前置，不是替代

## 1. 发现的缺口：通知被记录，但从未送达

准备实现 `docs/agent-spec.md:52`「模型输出 Schema/引用可修复一次」时，先去看"拒绝原因怎么回到模型"——因为
修复的前提是模型知道要修什么。结果发现通道根本不存在：

`ActionGateMiddleware.notices` 只在 `RunResult.notices` 里被读出来（`sdk_runner.py` 一行构造），
`sdk_adapter.py:118` 声明了一个 `self.notices` **没有任何使用者**，`grep` 全仓确认没有第三处。

也就是说，`docs/agent-spec.md:44`「前两次重复会被**回传**」这条**没有真正满足**：
`test_harness_loop.py` 那条断言的注释写着"the model was told, twice, before it was stopped"，
但它断言的是 `result.notices`——**harness 记下来了**，不是**模型被告知了**。
这与 C08.1c-1 的引用缺口是同一类错误：模型无法依据它从未收到的信息行动。

（第二次重复本身是被接受并执行的，所以模型能看到同一份工具结果；但通知文本是写给模型看的一句话
——"Read something else or decide with what you have"——它从未出现。判为缺口，不判为"等价"。）

## 2. 改动

| 文件 | 改动 |
| --- | --- |
| `agent/src/resolveflow/harness/context.py` | `ContextBuilder.build(..., notices=[...])` → P1 新增 `notice_N` 段，渲染为 `【P1·notice_0】[harness] …`，排在 history **之后** |
| `agent/src/resolveflow/harness/sdk_runner.py` | `_build_packet` 传 `notices=list(self._gate.notices)`；`_packet_of` 增 `packet["notices"]`；`_BudgetHook` 增公开别名 `self.gate`（与既有 `budget_guard` 同一理由：模块级函数不该跨模块读下划线字段） |
| `agent/tests/unit/test_harness_loop.py` | +1 例：正式路径下通知**出现在发出的 messages 里** |
| `agent/tests/integration/test_context_wiring.py` | +1 例：legacy（C06.4）路径的 JSON packet 同样带上通知 |

**为什么放在 P1 而不是新加一层**：P1 是强制层、不可裁剪（C08.1a 的不变量）。通知若可被裁剪，就会出现
"模型欠一个它从未看到的更正"——正是本步要修的错。数量有界（无进展 ≤2，将来的修复 ≤1），所以不会把
P0+P1+P2 顶爆；真的顶爆时按既有规则 `OverflowRefusedError` 停止，不静默丢弃。

**为什么两条路径都测**：两条路径的请求构造方式不同（P0–P4 多层 turn vs 单条 JSON message），
"模型被告知"必须逐路径成立，不能从默认路径推断另一条。修改前**两条都没有**。

## 3. 命令与结果

工作目录 `E:\Code\Agent+Backend\agent`：

```
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=short
  → 972 passed, 9 skipped, 1 warning in 129.95s
.\.venv\Scripts\python.exe -m ruff check src tests
  → All checks passed!
.\.venv\Scripts\python.exe -m mypy
  → Found 9 errors in 4 files (checked 50 source files)   # =既有基线，非全绿
```

C08.1c-1 结束时 970 passed → 本步 **+2 例**。

**归属证据**（避免"测试恰好在别处已被满足"）：`grep` 全仓 `notice_\{|\[harness\]` 只有**一处**产出者
——本步新增的 `context.py:382-383`。测试读的是 `conversations`（真正发出的 messages，
`input_text_of` 优先读它），不是结构化 packet 兜底。

## 4. 为 C08.1c-2「可修复一次」确定的机制（本轮只查证，未实现）

读 AgentScope 2.0.8 源码确认了修复轮**可达**，两条路径都会把工具结果喂回模型并**继续循环**：

- 权限拒绝：`_agent.py:2582-2590` → `_handle_error_tool_call(tool_call, decision.message, state=DENIED)`
  ——拒绝时带回的是 **`decision.message`**，也就是 harness 自己写的拒绝原因，而且循环继续；
- 未知/不可用工具：`_agent.py:2509-2517` → 同样走 `_handle_error_tool_call(state=ERROR)` 并继续。

所以计划是：**第一次**Schema/引用拒绝时不要像现在这样把回复改成终止性 ESCALATE，而是让 SDK 照常发出
该动作 → `on_check_permission` 因 `accepted` 未设置而拒绝 → 拒绝原因作为工具结果回到模型 → 下一轮即修复；
**第二次**拒绝才设 `stop_reason` 停止。注意终止性决策（PROPOSE/ESCALATE）在 `_as_chat_response` 里是
**文本块**、会直接结束循环，所以引用类拒绝要额外发一个"会被拒绝的工具调用"才能换来修复轮
——这条**尚未验证**，属于 C08.1c-2 的第一步（先写失败测试）。

结论：**`docs/agent-spec.md:52` 目前仍未满足**（仍是不可修复的硬停止），本步只把它的前置通道做实并查证了机制。

## 5. 未完成

- C08.1c-2：可修复一次（见 §4）。
- 端到端"通过型退款"用例（需要"真实工具 observation + 真实政策命中"双来源 fixture）。
- `verify_proposal()` 接入 run 路径（`proposal_id`/`case_type` 由 C08.2 组装 callback 时补）。
- 下一步：C08.2 单执行者业务闭环。

## 6. 顺带说明

`sdk_adapter.py:118` 那个未使用的 `self.notices` 字段仍在。它不参与请求构造（请求由 packet 决定），
删除它会动到适配器的公开形状，属独立的清理，故本轮保留并在此记录，不顺手删。