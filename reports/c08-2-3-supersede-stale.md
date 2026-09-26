# C08.2-3 补证：新revision使旧run STALE

日期：2026-09-26｜状态：**已完成并实测**｜顺带发现一处状态语义缺口（见 §5，未擅自改）

## 1. 规范依据

- `docs/agent-spec.md:9`：run状态含 `STALE`；**补证创建新revision/new run，旧run STALE**；新run可继承用户问答，
  但**重新取得物流/退款/政策有效事实**。
- `docs/agentscope-migration.md:68`：终局方案、run状态和callback_outbox**在同一事务提交**；**补证new revision/new run
  与同run故障恢复严格分开**。
- `docs/product-spec.md:31`（US-C3）：用户回答问题，input_revision递增并启动新run，**旧结果不会覆盖**。
- `docs/contracts.md:80` / `docs/core-contracts.md:62`：**Case侧**对旧revision/人工接管后的投递答 `STALE` 且不再重试。

## 2. 改动

| 文件 | 改动 |
| --- | --- |
| `agent/src/resolveflow/runtime/runs.py` | 新增 `STALE` 常量 + `RunStore._supersede_older_revisions(...)`；`queue()` 在**同一事务**内、插入新run之后调用 |
| `agent/src/resolveflow/runtime/callbacks.py` | 新增 `CallbackStore.void_pending_for_run(run_id, *, reason, connection=None)` |
| `agent/tests/integration/test_supersede_on_new_revision.py` | **新增** 7 例 |
| `agent/tests/integration/test_run_worker.py` | 修一处**不现实的fixture**（见 §4） |

**为什么在 `queue()` 里**：新run就是这次派发，而"一个case最多只有一个还能产出结果的run"这条不变量若在别处维护，
就会留下两个run都自认current的窗口。因此旧run的 `STALE` 与新run的插入**同一事务**。

**只supersede非终态run**（排除 `COMPLETED`/`FAILED`/`CANCELLED`，且已是 `STALE` 的不动）：
`COMPLETED` 的含义是"方案回调被Case接收"（`agent-spec.md:9`，**不表示退款成功**）——那次接收已经发生，
改成 `STALE` 会抹掉事实；"这份方案不再适用"属于Case服务自己的 `case_proposal` 行（`domain-model.md:57`）。
`CANCELLED` 是因自身原因被撤回的，也不该被改写成"被新输入取代"。

**同一事务里关掉旧run未投递的回调**：一个关于case已经走过的revision的问题/方案，根本不应交给Case服务。
`void_pending_for_run` 只动 `PENDING` 行，**不累加 `attempts`**——`attempts` 是"Case服务被调用了几次"，
而这次投递从未发生；把它记成一次尝试，会让从未被问过的Case服务看起来像拒绝过的。
已投递的行保留Case服务给出的答案（ACCEPTED/DUPLICATE/STALE），那是历史。

## 3. 命令与结果

工作目录 `E:\Code\Agent+Backend\agent`：

```
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=line
  → 1001 passed, 9 skipped, 1 warning in 128.41s
.\.venv\Scripts\python.exe -m ruff check src tests      → All checks passed!
.\.venv\Scripts\python.exe -m mypy                      → Found 9 errors in 4 files (checked 52)  # =既有基线
```

C08.2-2 结束时 994 passed → 本步 **+7例**。

关键两例：
- `test_a_superseded_run_is_never_investigated`：被supersede的run不会被领取，**不会为一个无法应用的结果花预算**，
  也不会为它落下 `STARTED`。
- `test_a_run_superseded_mid_investigation_cannot_file_its_result`：**US-C3 的"旧结果不会覆盖"**——
  客户在调查进行中补证，该调查正要提交的结果属于case已经走过的revision，`finish()` 的条件更新因此拒绝，
  run留在 `STALE`，出箱里没有 `PROPOSAL`。补证与"同run故障恢复"严格分开，这条路径**不涉及任何恢复机制**。

## 4. 一处必须说明的测试改动（不是为变绿删断言）

新逻辑使 `test_run_worker.py::test_drain_investigates_every_queued_run_at_most_once` **失败**：
它的fixture把第二个run写成**同一case的revision 2**，于是第一个run现在被正确地supersede，只剩一个可领取。

判断：**实现是对的，fixture不现实**——同一case的revision 2 与revision 1 并存且都被调查，正是规范要禁止的状态。
改法是把第二个run换到**另一个case**（保留该测试的原意：drain的顺序与limit），断言一条未删；
同case换revision的行为改由新增的 `test_supersede_on_new_revision.py` 正面覆盖。
该测试的docstring里写明了为什么是"两个不同case"。

## 5. 顺带发现的缺口（**未擅自改**，下一子步）

`agent-spec.md:9` 说 **`COMPLETED`表示方案回调被Case接收**、**`QUESTION接收后WAITING_INPUT`**——即这两个状态由
**Case服务的接收**决定。但现在：

- 投递循环 `runtime/delivery.py:192` 只 `record_delivery(..., disposition=...)` 记下Case的答复，
  **没有任何东西把答复回写到run状态**（全仓 `UPDATE agent_run` 只出现在 `worker.py` 与 `runs.py`）。
  于是方案被 `ACCEPTED` 后，run永远停在 `CALLBACK_PENDING`，永远不会成为 `COMPLETED`。
- 因此 C08.2-1 里 `ASK_CUSTOMER → WAITING_INPUT`（在 `finish()` 时直接置位）与规范不符：按规范它应先
  `CALLBACK_PENDING`，**接收后**才是 `WAITING_INPUT`。

这两件必须**一起改**（只改后者会让QUESTION永远停在 `CALLBACK_PENDING`，比现状更差），所以本步不动它。
下一子步的设计：`RunStore` 增加"按答复落run状态"的方法（`ACCEPTED`/`DUPLICATE`：PROPOSAL→`COMPLETED`、
QUESTION→`WAITING_INPUT`、FAILED→`FAILED`；`STALE`→`STALE`），并由 `deliver_one` 在**与出箱记录同一事务**内调用
（需要一个 `connection=` 缝，与 `enqueue_for_run`/`void_pending_for_run` 同一做法）。
现有 `test_run_worker.py::test_a_question_moves_the_run_to_waiting_input` 钉住的是**当前（待纠正的）**行为，
改那一步时它必须随规范改写，而不是被删掉。

## 6. C08.2 剩余

- **答复回写run状态 + QUESTION状态纠正**（上节，二者一起）。
- **Java半段**：复核/必要审批→模拟退款。Java侧 `docs/implementation-handoff.md:27` 记 `POST /evidence`（revision由服务端决定）
  与回调收件箱（含 STALE 语义）**已实现**、PROPOSAL 已可按钉住政策版本核对引用并重算金额；Python只到"回调落箱"，
  未验证 Java 的 `PENDING_REVIEW` → 审批 → 执行派发（`ExecutionDispatchLoop` 默认关闭）。
- `verify_proposal()` 接入run路径；`result_summary` 脱敏规则；常驻调度循环入口。
- `case_type` 契约缺口（**需决策**，未编造）；`parent_run_id` 列仍无人写（新run与旧run的血缘未记）。