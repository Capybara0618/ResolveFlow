# 模拟资金通道（退款 provider stub）

本目录是退款 provider 的协议与故障样例所在处。provider 由 **C04 建立**（T12 的占位说明已被取代），是"外部世界"的持久模拟器：它不在核心微服务集合里（`docs/core-scope.md:30`），不共享任何业务库，也不实现物流写协议。它的存在只为一件事——让退款链路遇到一个**会丢响应、会超时、会重启**的对端，而不是一个永远配合的假函数（`docs/architecture.md:13`）。

## 1. 两个操作

模拟器同时以两种方式暴露同一个内核：**进程内适配器**（`resolveflow.provider_stub.RefundProviderStub`，供 Commerce 的集成测试与 lab 直接调用）与**持久化状态文件**（SQLite，见下）。协议本身只有两个操作：

| 操作 | 输入 | 输出 |
| --- | --- | --- |
| `request_refund` | `operation_id`（即幂等键）、`line_id`、`amount_minor`、`currency`、可选的 `requested_at` | 一条 `RefundResult` |
| `query_refund` | `operation_id` 或 provider 发出的 `provider_ref`；可选 `at` 观察时刻 | 一条 `RefundResult`，键不存在时 `state=NOT_FOUND` |

`RefundResult` 的成员：`operation_id`、`state`、`provider_ref`、`amount_minor`、`currency`、`reason_code`、`settled_at`、`visible_after`、`responded`。**`responded` 与 `state` 是两件事**：前者说的是"这次调用有没有拿到回答"，后者说的是"provider 认为这笔钱现在是什么状态"。丢响应与超时都会让调用方拿不到回答，但只有前者背后有一个 provider 已知的结果——把两者混为一谈，正是"重试变成重复付款"的起点。

## 2. 状态：UNKNOWN 不是 FAILED，NOT_FOUND 也不是

| state | 含义 | 上游该怎么做 |
| --- | --- | --- |
| `SUCCEEDED` | 钱已派出，`provider_ref` 是凭据 | 记账为成功，`aggregate_version` 前进 |
| `FAILED` | 确定被拒（`reason_code` 说明为什么） | 释放预留；**该键此后不再复活** |
| `UNKNOWN` | 没有拿到结果（超时，或响应丢失） | **不释放预留**，不换 ID，沿原键查询/重试（`docs/domain-model.md:15`） |
| `NOT_FOUND` | 这个 provider 现在看不到这笔（可能还没到可见窗口） | 同样不释放；"查不到"不是"没发生" |

三条不变式在这里落地：

1. **同键同载荷返回原结果**；同键换了载荷（金额、行、币种任一不同）**拒绝**（`ProviderConflictError`）。允许覆盖就等于让"到底付了多少"取决于最后一次写入，而 `operation_id` 唯一性存在的意义正是防这个（`docs/domain-model.md:11`）。
2. **幂等键由上游给，不由 provider 生成**：`provider_key = operation_id`（`docs/domain-model.md:51`），`provider_ref` 只是 provider 自己的凭据，供查询与展示。重试不得换键。
3. **FAILED 是墓碑**：确定失败后上游已经释放金额，所以同一个键**永远不会**再被这个模拟器执行成功。后来的请求得到那条失败记录本身，`attempts` 也不再增长。

## 3. 故障注入

`inject(fault, operation_id=…, reason_code=…, visible_after=…)`；省略 `operation_id` 表示对该 provider 的所有请求生效。`clear_faults()` 清空。

| fault | provider 实际做了什么 | 调用方看到什么 |
| --- | --- | --- |
| `REQUEST_TIMEOUT` | 什么都没结算 | `state=UNKNOWN`、`responded=false`；此后查询仍是 `UNKNOWN`，直到 `settle()` |
| `LOST_RESPONSE` | **已结算并落库**（成功或拒绝） | `responded=false`；用同一个键重试会拿到**原来那条结果**（`responded=true`），且 `attempts` 不增长 |
| `DELAYED_VISIBILITY` | 已结算并落库 | `request_refund` 正常回答；`query_refund` 在 `visible_after` 之前一律 `NOT_FOUND`，之后才返回真实状态 |
| `DECLINE` | 结算为 `FAILED` | `state=FAILED` + `reason_code`（默认 `DECLINED`） |

`settle(operation_id, state=SUCCEEDED|FAILED)` 用来手工了结一个 `UNKNOWN`，模拟 provider 侧的对账窗口；它只对 `UNKNOWN` 生效，已经终结的键返回原记录而不改写。

## 4. 持久化

状态只在一个 SQLite 文件里，三张表：`refund_request`（每个键一行，含状态、凭据、金额快照与可见时刻）、`request_attempt`（每次呈递一行，`REPEAT` 表示"返回已有收据"而非新的付款尝试）、`injected_fault`（注入的故障）。

**没有进程内缓存**：一个把状态放在内存里的模拟器无法用来测它存在的理由（重启）。重启后 `SUCCEEDED` 仍在、`UNKNOWN` 仍是 `UNKNOWN`、`attempts` 不从零开始。测试用 `test_the_outcome_survives_a_reopen_of_the_same_file` 与 `test_the_database_is_the_only_state` 钉住这一点。

金额一律是整数分（`amount_minor > 0`，非正数在碰到 provider 之前就被拒绝），不用浮点。

## 5. 与上游的边界

- provider 的密钥/凭据**不对 Agent 可见**（`docs/contracts.md:96`），本模拟器也不持有真实凭据。
- 只有 Commerce 的派发路径调用它；结果由 Commerce 落库后再以 `RefundSucceeded`/`RefundFailed`/`RefundUnknown` 事件投影给 Case（`docs/core-contracts.md:86`）。模拟器自己不产生业务事件。
- provider 网络调用必须在事务外（`docs/engineering.md:23`）：本模拟器只负责"对端"，事务边界是 C04.2/C04.3 的事。

## 6. 目录

| 路径 | 内容 |
| --- | --- |
| `agent/src/resolveflow/provider_stub/` | 模拟器实现（协议、故障注入、SQLite 持久化） |
| `agent/tests/unit/test_provider_stub.py` | 幂等/查询/丢响应/超时/延迟可见/重启/墓碑 |
| `fixtures/provider/README.md` | 本文件：协议与故障语义 |

`fixtures/` 下的样例数据文件在需要时由 C04.2/C04.3 追加；目前只有本协议说明，不放假样例。
