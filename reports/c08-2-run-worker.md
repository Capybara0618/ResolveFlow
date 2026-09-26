# C08.2-1 单执行者 worker：待办run真的被消费

日期：2026-09-26｜状态：**已完成并实测**｜C08.2 的其余部分（派发→Java复核→退款、补证新run/旧结果STALE、mock/live工厂）未做

## 1. 补的缺口

在此之前 `agent_run` 里有 `QUEUED` 行、`agent_callback_outbox` 也有投递循环，但**没有任何东西把 run 变成调查**——
`tasks/handoff-current.md` 明确不把"根本没人消费run"推迟到 C09。本步补上这个消费者。

## 2. 改动

| 文件 | 改动 |
| --- | --- |
| `agent/src/resolveflow/runtime/worker.py` | **新增**：`RunWorker`（`claim_one`/`finish`/`run_once`/`drain`）、`ClaimedRun`、`RunOutcome` |
| `agent/src/resolveflow/runtime/callbacks.py` | `enqueue_for_run(..., connection=)` **追加式**可选连接；原实现拆为 `_enqueue(connection, ...)`，不传连接时行为不变 |
| `agent/tests/integration/test_run_worker.py` | **新增** 11 例（真实 PG schema，`investigate` 为桩） |

三步，各有其规则：

1. **领取**：`SELECT … WHERE status='QUEUED' AND cancelled_at IS NULL ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED`
   → `UPDATE … SET status='RUNNING', active_deadline_at=…, version=version+1`，并在**同一事务**内写入 `STARTED` 回调
   （`AGENTS.md`：业务结果与本地事件同事务）。两个 worker 竞争既不会重复领取，也不会出现"run 已 RUNNING 而 case-service 从未被告知"。
2. **调查**：在事务**之外**调用注入的 `investigate(facts)`——模型调用是外部网络调用，`AGENTS.md` 禁止跨长事务。
3. **收尾**：`UPDATE … WHERE run_id=… AND status='RUNNING'` **条件更新**；为 0 行说明 run 已被取消，则**拒绝写入**、
   不落回调（单执行者能做的唯一诚实处理；真正的 fence 属 C09）。成功时回调与终态状态在**同一事务**内落库。

**授权窗口** `min(deadline_at, started + 120s)`（`MAX_ACTIVE_DEADLINE_SECONDS`）：`docs/agent-spec.md:42` 限定单次持有上限，
且 `RunFacts.active_deadline_at` 的文档本来就写明由"启动它的人"解析好——在别处再算一遍等于对同一事实给两个答案。

**回调映射**：`PROPOSE`→`PROPOSAL`+`CALLBACK_PENDING`（等 Java 复核）；`ASK_CUSTOMER`→`QUESTION`+`WAITING_INPUT`；
其余（拒绝/预算耗尽/循环停止）→`FAILED`+`FAILED`，带 run 自己的 reason code 且 `retryable=False`
（harness 停止是对这份输入的判断，不是瞬时故障）。id 由 run 派生（`proposal-<run_id>`/`question-<run_id>`），
所以重复处理同一 run 得到同一个 id，出箱的 `callback_id` 幂等之外再叠一层载荷幂等。

**状态常量** 不在本模块重抄：`_status(name)` 从 `RunStore` 的 `RUN_STATUSES` 取，取不到就在 **import 时**失败
——词表变更应该在建表处被注意到，而不是写进一行数据库。

## 3. 命令与结果

工作目录 `E:\Code\Agent+Backend\agent`：

```
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=line
  → 987 passed, 9 skipped, 1 warning in 125.29s
.\.venv\Scripts\python.exe -m ruff check src tests      → All checks passed!
.\.venv\Scripts\python.exe -m mypy                      → Found 9 errors in 4 files (checked 51)  # =既有基线
```

C08.1c-2 结束时 976 passed → 本步 **+11例**（真实 PG，走 `agent_db` fixture 与 `RunStore.queue`）。

值得单独指出的一例：`test_an_unexpected_failure_is_not_dressed_up_as_a_decision` —— 调查抛异常时**不**捕获、
run 留在 `RUNNING`。写一个 catch-all 把崩溃变成 `FAILED` 回调会让缺陷看起来像"调查得出了结论"，
而 run 记录会声称 harness 做了它从未做的决定。留在 RUNNING 的恢复是 C09 的，这里具名而不近似。

## 4. 未完成（下一步）

- **派发→调查→回调→Java复核/必要审批→模拟退款**的后半段（Java 侧复核与模拟退款，本步只到 callback 落箱）。
- **补证新run / 旧结果STALE**：`STALE` 状态已在 `RUN_STATUSES` 中，但没有任何东西把旧 revision 的结果标为 STALE 或开子 run
  （schema 已有 `parent_run_id`，未使用）。
- **mock/live 客户端工厂**：`investigate` 是可注入的缝，但还没有从配置构造 runner（模型/工具/政策索引/预算）的工厂，
  即还没有一个可部署的入口。
- **`verify_proposal()` 接入 run 路径**：整份 v2 proposal 的组装与校验仍缺（`proposal_id` 已由本步派生，
  `case_type` 在派发体中**不存在**——见下）。
- **`case_type` 缺口（新发现，需决策）**：`agent-proposal.schema.json` 的 v2 要求 `case_type`，而 `agent_run`/`RunRequest`
  都没有该列。本步**没有**编造一个值（例如照抄 LOGISTICS）：那是在伪造案件状态。修法是派发协议带上它并同步 Java 消费者，
  或由 case-service 在复核时补——属需确认的契约变更，不在本轮擅自改。
- `result_summary` 仍留 NULL：列注释写明"只能是脱敏摘要，绝不写原始模型文本"，而模型摘要正是原始文本；脱敏规则未定前不写。
- 无 lease/fence/恢复/重试排程（C09）；`drain` 是单次扫描而非常驻循环调度。