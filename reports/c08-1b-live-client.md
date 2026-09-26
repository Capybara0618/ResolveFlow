# C08.1b-2 live ModelClient（离线请求捕获）（2026-09-26）

范围：`handoff-current.md` §2 C08.1b 第二条。承接 [C08.1b-1 冻结 manifest](c08-1b-frozen-manifest.md)。
**未联网、未调用任何付费 provider**；H1 未勾。

## 1. 起点

仓库里没有 live 模型客户端：`provider_stub` 是 C05 的退款业务 provider（SQLite），不是模型 provider。
`harness/model.py` 只有 `MockModelClient` 与 `ModelClient` Protocol（其 docstring 已写明 live 客户端的三条义务：
强制 ceiling、无隐藏重试、缺 usage 标 estimated）。`MODEL_MODE_LIVE = "live"` 已存在但从未被生产使用。

规格约束（照抄进实现注释）：

- `docs/agent-spec.md:40`：默认12次模型调用**含修复/网络重试**，工具额外重试2次、**模型1次**，**只有一层负责重试，所有attempt计预算**。
- `docs/agent-harness.md:39`：调用前预占 `min(单步输出上限, 累计剩余输出)` 并**传给 ModelClient**；额度为0不得调用；
  已知usage退回未用部分，**未知/估算usage不得把预占退为0**。
- `docs/agent-spec.md:44`：**缺provider准确计数时标ESTIMATED**。
- `docs/agent-harness.md:33`：**参数只记录实际发送值，不存密钥**。

## 2. 实现：`agent/src/resolveflow/harness/live_model.py`

一个 provider 请求做一次决策，**没有重试循环**——内部重试就是一次没人预占的 provider 调用，会让
`调用前预占` 不再描述真实花费；`agent-spec.md:40` 允许的那 1 次模型重试由**计费的那一层**发起。四条规则在客户端内强制：

1. **ceiling 必填**：`decide(max_output_tokens=None)` 直接 `ValueError`，**不发请求**（未预占的输出不能计费，也就是 `额度为0不得调用` 的另一面）。
   ceiling 在 body 里**最后写入**，所以配置里若混进 `max_tokens` 参数也**不能**放宽预占。
2. **恰好一次**：4xx = `ModelRefusedError`（run 停止，`agent-spec.md:36` 的 FORBIDDEN 纪律），5xx/timeout/连不上 = `ModelUnavailableError`；
   两者都在**一次发送之后**抛出，且失败尝试也**记账**（`requests` 记录带 `status`/`failure`，`calls == len(requests)` 可审计）。
3. **缺 usage 标 ESTIMATED 且非零**：没有 `usage` 块时按实际收发的文本用**与 manifest 同一个计数器**估算，
   `estimated=True`——静默的 0 会把输出预占退掉。
4. **不存密钥**：key 只进 `Authorization` 头，记录只存 body、body 的 canonical hash、status、usage、mode；
   **不存任何 header**，所以记录天然无凭据，不需要一个可能漏掉分支的"脱敏"过程。

另有：空 `system` 不注入第二条 system 消息（`ModelClient` 规定空表示 P0 已带 prompt）；
`model_alias` 取响应里的 `model` 字段（`agent-harness.md:35` 要求别名漂移可记录）；
答案提取**对包装宽松、对内容严格**（容忍 ```json 围栏与夹在散文中的 JSON，正文不是 JSON 对象则拒绝）。

顺带收敛一处重复：`canonical_json`/`hash_document` 提为 `harness/context.py` 的公开助手，
`manifest.py` 与 `live_model.py` 复用，删掉我在 C08.1b-1 里复制的那份 `_json`（三份同样的 hash 约定就是两份记录开始不一致的方式）。

## 3. 明确记录、**故意不擅自补**的缺口

冻结的 system prompt 与 ABI **都没有说答案必须是 JSON**。live 客户端因此只能宽松提取、否则拒绝。
真正的修法在 prompt/ABI（属 harness 决定，会改变 `prompt_hash`），不在传输层偷偷追加一条 manifest 看不见的指令——
所以这里**报告而不发明**。影响：真实 provider 用散文回答时 run 会停。列入下一步（C08.1c 前）处理。

## 4. 测试

`agent/tests/unit/test_live_model_client.py`（13 例，全部离线，transport 注入，**不开 socket**）：

- ceiling 进入**实际请求体**（`max_tokens == 1024`），声明参数按时发送；
- 无 ceiling → `ValueError` 且 `transport.calls == []`（**一个字节都不发**）；
- 503 → 不可用且**只调用 1 次**；400 → 拒绝、500 → 不可用，各 1 次；transport 抛 `TimeoutError` → 不可用、1 次；
- 失败尝试也入账：`calls == 1 == len(requests)`，记录含 503 与 body_hash；
- 记录**无凭据**（`SECRET not in json.dumps(record)`、不含 `authorization`）且 `body_hash` 等于按项目 canonical 方式重算的 body hash；
- key **只**出现在 `Authorization` 头里；
- 缺 usage → `estimated is True` 且入/出均 > 0，`mode == "live"` ≠ `"mock"`；有 usage → 精确值且 `estimated is False`；
- 散文答案 → `ModelRefusedError`；```json 围栏 → 正常解析出 PROPOSE；
- 空 `system` 不产生第二条 system 消息。

`test_context_wiring.py` 新增 1 例集成：**live 客户端跑完同一条循环**（transport 注入）——`result.modes == ("live",)`、
`completed is True`、解析出的 PROPOSE **过了动作闸门**（`result.decision.kind == "PROPOSE"`）、
**实际发往 provider 的 body 带 `max_tokens == runner.budget.step_output_tokens`**、一次决策一次调用。
为此把测试助手 `run()` 的形参类型从 `MockModelClient` 放宽为 `ModelClient`（两种客户端同一条循环）。

## 5. 实测（工作目录 `agent/`）

| 命令 | 结果 |
| --- | --- |
| `pytest tests` | **953 passed, 9 skipped, 1 warning**（C08.1b-1 后 939 → +14 例） |
| `ruff check src tests` | All checks passed（过程修掉：S310 在 `Request` 构造处也触发、E501 一条） |
| `mypy` | **9 errors / 4 files = 基线**（49 个源文件；中途因 `int(Any \| None)` 多出 1 条，用 `TypeGuard[int]` 收窄后归零） |

改动：新增 `harness/live_model.py`、`tests/unit/test_live_model_client.py`；
修改 `harness/context.py`（公开 `canonical_json`/`hash_document`）、`harness/manifest.py`（复用并删除本地副本）、
`tests/integration/test_context_wiring.py`。

## 6. 未做 / 未运行

- **未联网**：没有任何真实 provider 调用；live 小样本需付费与用户确认，H1 配对证据未做（mock 不勾 H1）。
- **未接线**：还没有从环境/配置构造 live 客户端的工厂，也没有 worker 选择 mock/live 的入口（属 C08.2 worker）。
- **未做**：候选引用验证（C08.1c）、答案格式的 prompt/ABI 约定（见 §3）。
- **未跑**：Java 全量、`all-offline`、spikes。
- **不得宣称**：真实模型自主性、供应商 HTTP 层最终载荷/hash 已校验（本次证明的是**本客户端发出的 body**）、C09/C10。

## 7. 下一步

C08.1c 候选引用验证：可见来源、版本/hash、缺证、跨 scope 与政策固定版本；Python 校验不等于 Java 授权。
附带处理 §3 的答案格式缺口（prompt/ABI 层面，需同步 `prompt_hash` 与 packet）。