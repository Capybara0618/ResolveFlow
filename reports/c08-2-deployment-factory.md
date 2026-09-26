# C08.2-2 部署装配缝：配置 → 可调查的 run

日期：2026-09-26｜状态：**已完成并实测**｜C08.2 的 Java 半段（复核→模拟退款）与补证/STALE 仍未做

## 1. 补的缺口

C08.2-1 的 worker 把调查作为**注入的可调用对象**接收，但没有任何东西从部署配置构造它——即"现有模型/工具"还没有接线，
worker 因此不可部署。本步补上这条缝。

## 2. 改动

| 文件 | 改动 |
| --- | --- |
| `agent/src/resolveflow/runtime/factory.py` | **新增**：`DeploymentConfig.from_environ`、`build_investigation(...)`、`DeploymentRefusedError` |
| `agent/tests/integration/test_deployment_factory.py` | **新增** 7 例（含**整条管线**端到端一例） |

`build_investigation(*, database, config, model=None, tools=None, policy_embedder=None, budget=None)` 返回
`Callable[[RunFacts], RunResult]`：每次调查新建模型客户端与 MCP 执行器、跑 `AgentScopeRunner`、退出时关闭执行器。
政策索引建一次（数据库对象），嵌入器只在提供检索时才需要。

## 3. 三处刻意拒绝（本模块自带测试的理由）

1. **模式必须被指名**：`RESOLVEFLOW_MODEL_MODE` 未设或不是 `mock|live` 即拒绝，**没有默认值**。
   给默认就是在猜：默认 mock 会产出并非模型产出的方案，默认 live 会在没人写过的配置上开始花钱。
   （mock run 事后仍可辨认——`RunResult.modes` 带 `"mock"`——但那是"发生了什么"的记录，不是事先替它选的许可。）
2. **mock 模式不会自己编脚本**：`mode=mock` 必须传入脚本化客户端；工厂替它写脚本就等于替它写决定。
3. **live 模式在能发出请求之前就拒绝**：缺 endpoint 或 model_id 在**构造调查时**即失败——配错的部署不会先发出请求再发现问题。
   `policy_index=1` 而嵌入快照不可用时同理：`embedder()` 在构造期抛错，部署拒绝，而不是静默地"没有检索"地跑完。

## 4. 其它刻意选择

- **客户端每 run 一个**：`LiveModelClient` 会记录它发出的每个请求，跨 run 共用一个客户端会把一个 run 的审计痕迹混进另一个；
  同时 `calls` 保持按 run 计数，正是预算所数的。
- **执行器每 run 一个**：`line_id`/`run_id`/`case_id` 是 run 级状态，工具服务器每次调用都要被告知读哪一行。
- **退出时关闭执行器**，但用 `getattr` 探测：`ToolExecutor` 协议要求 `close`，注入的测试替身未必有，
  而"调查已完成却在返回路上崩掉"会丢掉结果。
- **密钥只有一个去处**：`LiveModelClient` 的 `Authorization` 头。有测试钉住客户端自己的请求记录里不含凭据（C08.1b-2 在下一层钉过同一件事）。

## 5. 命令与结果

工作目录 `E:\Code\Agent+Backend\agent`：

```
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=line
  → 994 passed, 9 skipped, 1 warning in 127.96s
.\.venv\Scripts\python.exe -m ruff check src tests      → All checks passed!
.\.venv\Scripts\python.exe -m mypy                      → Found 9 errors in 4 files (checked 52)  # =既有基线
```

C08.2-1 结束时 987 passed → 本步 **+7例**。

**端到端证据（本步最重要的一例）**：
`test_the_whole_pipeline_files_a_proposal_from_a_real_investigation` 让
派发（`RunStore.queue`）→ worker 领取 → 工厂构造 → **真实 AgentScope 生产循环** → 工具真的被执行
（`tools.calls == [("get_shipment_trace", {})]`）→ 出箱里 `["STARTED", "PROPOSAL"]` 且 run 为 `CALLBACK_PENDING`，
`result.modes == ("mock","mock")` 证明回答者是 mock 且记录如实。
即：**Python 侧的"派发→调查→回调"闭环已通**，模型是脚本化的、工具是替身（无 provider、无 MCP 子进程）。

live 路径也走通了真实客户端：注入 transport（不出进程）驱动 `LiveModelClient`，钉住模型 id 进了请求体、
`Authorization: Bearer …` 进了头、而客户端的 `requests` 记录里没有密钥。

## 6. 未完成（下一步）

- **Java 半段**：`proposal` 回调之后 Java 的复核/必要审批→**模拟退款**（本步只到回调落箱；Python 不退款、不审批）。
- **补证新run / 旧结果STALE**：`STALE` 状态与 `parent_run_id` 列已在，仍无人使用。
- **`verify_proposal()` 接入 run 路径**：整份 v2 proposal 的组装与校验。
- **`case_type` 契约缺口（需决策）**：v2 proposal 要求 `case_type`，`agent_run`/`RunRequest` 均无此列；**未编造取值**。
- `result_summary` 仍留 NULL（脱敏规则未定前不写原始模型文本）。
- 无常驻调度：worker 的 `drain` 是单次扫描（C09 的恢复/竞争保护之外，部署侧还需一个循环入口）。