# C08.2-4 答复决定run状态（并纠正QUESTION语义）

日期：2026-09-26｜状态：**已完成并实测**｜修的是上一轮自己发现的缺口（[C08.2-3 §5](../reports/c08-2-3-supersede-stale.md)）

## 1. 缺口

`docs/agent-spec.md:9`：**COMPLETED表示方案回调被Case接收**、**QUESTION接收后WAITING_INPUT**——这两个状态由
**Case服务的接收**决定。但在此之前 `delivery.py` 只 `record_delivery(..., disposition=...)` 记下答复，
**没有任何东西把答复回写到run状态**（全仓 `UPDATE agent_run` 只在 `worker.py`/`runs.py`）：
方案被 `ACCEPTED` 后run永远停在 `CALLBACK_PENDING`，永远到不了 `COMPLETED`。

而 C08.2-1 里 `ASK_CUSTOMER → WAITING_INPUT`（`finish()` 时直接置位）与规范相反：按规范它应先 `CALLBACK_PENDING`，
**接收后**才是 `WAITING_INPUT`。只改后者会让QUESTION永远停在 `CALLBACK_PENDING`（比现状更差），故两件同一步改。

## 2. 改动

| 文件 | 改动 |
| --- | --- |
| `db.py` | 新增 `reuse_or_open(database, connection)`：调用方有事务就用它，否则新开一个 |
| `callbacks.py` | 新增 `CallbackStore.transaction()`；`record_delivery` 增 `connection=` 缝；三处缝（`enqueue_for_run`/`void_pending_for_run`/`record_delivery`）统一改用 `reuse_or_open` |
| `runs.py` | 新增 `RunStore.apply_callback_disposition(...)` + `_status_for_answer(kind, disposition)` |
| `delivery.py` | `deliver_one` 在**同一事务**内先 `record_delivery` 再 `apply_callback_disposition` |
| `worker.py` | `ASK_CUSTOMER` 的终态由 `WAITING_INPUT` 改为 `CALLBACK_PENDING` |
| `tests/integration/test_callback_delivery.py` | +9例（7例参数化 + 2例） |
| `tests/integration/test_run_worker.py` | 一处断言**按规范改写**（见 §4，非删除） |

**映射**（`_status_for_answer`）：

| callback | 答复 | run状态 |
| --- | --- | --- |
| PROPOSAL | ACCEPTED / DUPLICATE | `COMPLETED` |
| QUESTION | ACCEPTED / DUPLICATE | `WAITING_INPUT` |
| FAILED | ACCEPTED / DUPLICATE | `FAILED` |
| 任意 | STALE | `STALE` |
| STARTED | ACCEPTED / DUPLICATE | 不变（`RUNNING`，由领取它的claim写下） |

`DUPLICATE` 与 `ACCEPTED` 同义：Case服务已应用过一次并持有它（`contracts.md:80`），
run状态不该取决于网络需要被告知几次。`STALE` 是Case在说这条消息属于已过期的revision、或已人工接管
（`core-contracts.md:62`）——与"被新派发supersede"同一个理由，故同样落 `STALE`。

**同事务**（`AGENTS.md`：业务结果和本地事件同事务）：出箱行标成 `DELIVERED` 而run还说 `CALLBACK_PENDING`，
就是一个在等已经到达的答复的run。因此 `deliver_one` 自己开事务、把同一个连接交给两个store；
`reuse_or_open` 是这条缝的统一写法（传连接始终是显式选择，不传则行为与从前完全一致）。

**守卫**：条件更新 `WHERE status <> ALL(terminal) AND status <> STALE`——已取消的run不会被答复复活，
重投也不会改写已经到达过的状态。取消是真的发生过的事实，一次投递不是对它的撤销。

## 3. 命令与结果

工作目录 `E:\Code\Agent+Backend\agent`：

```
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=line
  → 1010 passed, 9 skipped, 1 warning in 130.22s
.\.venv\Scripts\python.exe -m ruff check src tests      → All checks passed!
.\.venv\Scripts\python.exe -m mypy                      → Found 9 errors in 4 files (checked 52)  # =既有基线
```

C08.2-3 结束时 1001 passed → 本步 **+9例**。关键三例：
- 参数化的 `test_a_delivery_moves_the_run_to_the_status_its_answer_implies`（7种组合）。
- `test_an_answer_cannot_resurrect_a_cancelled_run`：出箱行仍记下Case说了什么（那次答复确实发生了），
  但run状态不被改写。
- `test_a_started_acknowledgement_changes_no_status`：`STARTED` 是run在自报家门，Case的确认不决定新东西。

## 4. 一处断言改写（已披露，非删除）

`test_run_worker.py::test_a_question_moves_the_run_to_waiting_input` **钉住的是与规范相反的行为**
（`ASK_CUSTOMER` 在 `finish()` 时直接 `WAITING_INPUT`）。按"不为变绿删断言"的界线，这不是为了变绿而改：
它改为 `test_a_question_is_filed_and_leaves_the_run_awaiting_receipt`，断言**更多**——
run为 `CALLBACK_PENDING` **且**那条QUESTION回调仍是 `PENDING`（旧断言没有这一条），
并在docstring里指向 `test_callback_delivery.py` 中钉住"接收后 `WAITING_INPUT`"的那一例。
即：错的断言被换成规范的断言，并且补上了原先缺失的接收侧覆盖，而不是删掉一个碍事的判断。

## 5. C08.2 剩余

- **Java半段（未由我在本轮验证）**：`docs/implementation-handoff.md:27` 记 Case 的 `POST /api/v1/cases/{case_id}/evidence`
  （revision由服务端决定、已终结409）与回调收件箱（`callback_id`主键、逐字重投DUPLICATE、旧revision/人工接管STALE、
  同id换内容409、STARTED/QUESTION/FAILED各自状态与轨迹后果）**已实现**，PROPOSAL 也能按钉住的政策版本核对引用并重算金额。
  Python侧本轮做的是"答复回写run"；尚未打通的是 **Java `PENDING_REVIEW` → 审批 → 执行派发 → 模拟退款**
  （`ExecutionDispatchLoop` 默认关闭），且 **Java 侧本轮未运行**（沿用 C07.1 的 BUILD SUCCESS，非本轮证据）。
- `verify_proposal()` 接入run路径；`result_summary` 脱敏规则；常驻调度循环入口。
- `case_type` 契约缺口（**需决策**，未编造）；`parent_run_id` 仍无人写（新run与旧run的血缘未记）。