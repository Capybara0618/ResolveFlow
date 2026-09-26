# C08.1c-2 可修复一次（`docs/agent-spec.md:52`）

日期：2026-09-26｜状态：**已完成并实测（Python侧，mock驱动）**

## 1. 规格要求与旧行为

`docs/agent-spec.md:52`：「模型输出 Schema/引用**可修复一次**；ref必须实际可见…」
旧行为是**不可修复的硬停止**：`_GateAwareClient.decide` 一旦 `gate.check()` 返回 `None`，就把回复改写成终止性
ESCALATE，SDK 随即结束循环——模型连"哪里错了"都收不到。C08.1c-2a 已把反馈通道（P1 notice）做实，本步用它接上修复轮。

## 2. 机制（读 AgentScope 2.0.8 源码确定，不是猜）

- 结束循环的是「这一轮**没有工具调用**」；`ChatResponse.is_last` 只是**流式分片**标志（`_agent.py:1741`），不控制循环。
- 因此要让模型再被问一次，必须给出一个工具调用。两条被源码确认的路径都会**把结果喂回并继续循环**：
  - 权限拒绝 `_agent.py:2582-2590` → `_handle_error_tool_call(..., decision.message, state=DENIED)`
    ——回传的正是 harness 自己写的 `decision.message`；
  - 未知/不可用工具 `_agent.py:2509-2517` → 同样回传并继续。

## 3. 改动（先写4例失败测试，确认RED后再实现）

| 文件 | 改动 |
| --- | --- |
| `agent/src/resolveflow/harness/sdk_runner.py` | `MAX_REPAIRS=1`、`_TOOL_CALL_KINDS`、`_repair_probe()`；gate 增 `repairs_used`/`repair_message` 与 `_refuse(reason, detail, repairable=)`；`check()` 三类拒绝全部走 `_refuse`；`on_check_permission` 增**修复分支**（带拒绝原因 DENY 且**不**记为第二次拒绝、**不**设 stop_reason）；`decide()` 在 `repair_message` 存在时返回 `_repair_probe(...)` 而非终止 ESCALATE |
| `agent/tests/integration/test_context_wiring.py` | +4例；1例既有的"缺证即停"改为"缺证两次才停"（见§4） |
| `agent/tests/unit/test_harness_loop.py` | 2例随语义更新（见§4） |

**为什么"第一次拒绝不终止"只能这样做**：非终止决策（READ_TOOL/SEARCH_POLICY/READ_OBSERVATION）在适配器里本来就是
工具调用，原样交还即可——SDK 去执行它、`on_check_permission` 因 `accepted is None` 拒绝、原因回到模型。
但**终止决策**（PROPOSE，引用拒绝就属此类）在适配器里是**文本块**，原样交还等于结束循环、白白花掉唯一一次修复；
故替换为一次白名单工具的探测调用：五个 bridge 的 `input_schema.required` 为空，空参数可通过 SDK 校验，
而执行只发生在权限 ALLOW 之后，`accepted` 未设置时不可能 ALLOW —— **探测调用不可能真的执行**。

`_refuse(repairable=False)` 用于无进展停止：那是循环自身的界，不是模型输出错误，且 `docs/agent-spec.md:44`
本来就已经反馈了前两轮。

## 4. 语义变更与随之更新的断言（未删断言）

1. `test_a_refund_that_cites_nothing_never_becomes_the_run_s_decision`：仍断言"未引用的退款**永远不成为 run 的决策**"，
   但现在模型发两次（第二次才停），并新增断言 gate 记了**两条**同码拒绝 + `repairs_used == 1`
   ——一条错误 + 一次修复 + 再犯，与"只拒一次"可区分。
2. `test_a_refused_action_ends_the_run_instead_of_being_executed`：核心断言 `tools.calls == []` **保留**，
   改为 `always(...)` 驱动并断言"两轮后停止"（一次拒绝 + 一次修复轮）。
3. `test_the_observation_reaches_the_next_model_call`：终局提议由 REFUND 改 `MANUAL_REVIEW`（该测试讲的是
   observation 是否进入下一次请求，与引用无关）。

## 5. 命令与结果

工作目录 `E:\Code\Agent+Backend\agent`：

```
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=line
  → 976 passed, 9 skipped, 1 warning in 123.22s
.\.venv\Scripts\python.exe -m ruff check src tests      → All checks passed!
.\.venv\Scripts\python.exe -m mypy                      → Found 9 errors in 4 files (checked 50)  # =既有基线
```

C08.1c-2a 结束时 972 passed → 本步 **+4例**。新测试覆盖：首次拒绝被回喂且 run 恢复并完成；
**只给一次**修复、第二次拒绝即停（`repairs_used == 1`、`model.calls == 2`）；引用拒绝被修复成可提交决策；
修复轮**计入模型预算**（`result.spend.model_calls == model.calls == 3`，`docs/agent-spec.md:40`）。

## 6. 边界与未完成（不夸大）

- 本步验证全部由 **mock 驱动**：证明的是"harness 在模型输出不合法时的行为"，**不是**真实模型会自我修正。
  H1（≥6组真实模型配对证据）仍未做，需用户确认付费小样本，**不因本步变绿而勾选**。
- `verify_proposal()`（整份 v2 Schema）仍未接入 run 路径（`proposal_id`/`case_type` 属 C08.2 组装 callback）。
- 仍缺"真实工具 observation + 真实政策命中"双来源 fixture 下的端到端**通过型**退款用例。
- 修复次数按 **run 全局**计（一次），未按"每类错误各一次"——这是对"可修复一次"的保守读法，已在此记录。
- 下一步：C08.2 单执行者业务闭环（PG 待办 worker + `callback_outbox` + Java 复核后退款 + 补证新run/旧结果STALE）。