# C08 交接（2026-09-25）· 动态 Harness 与业务接入

给新会话读的一份自足交接。**C07 已完成**（C07.1 + C07.2，两个提交在本地：`3b71fba`、`9c84f14`；推送前问用户）。
本文件只讲"现在站在哪、下一步做什么、哪些前提可以信任、哪些坑会误导判断"。

## 0. 开工第一件事

```powershell
Set-Location 'E:\Code\Agent+Backend'
(Get-Location).Path              # 必须是 E:\Code\Agent+Backend（没有加号）
git log --oneline -1             # 应能看到标题含 "C07.2 完成" 的那一条
git status --porcelain           # 应为空
git rev-list --left-right --count origin/main...HEAD   # 若为 "2  0"，说明本地领先、尚未推送
Test-Path tasks/handoff-c07-2.md # True（C07.2 开工时的交接，含 10 条坑）
```

任一条不符 → 停下并报告。

## 1. 位置

**C00–C06、AS00–AS02.3、C07.1、C07.2 全部完成。** 门禁 `all-offline` PASSED
（`reports/verify/20260925-221721-all-offline.txt`）；Python **903 passed, 9 skipped**；Java **385 例 0 失败、4 skipped**。

**下一件事：C08 —— 动态 Harness 与业务接入。** 依赖 C05、C07（已满足）。

## 2. C08 的第一件事就是把 C07.2 留的那个口子接上（**这是本步最重要的待办**）

**`ContextBuilder` 是一个完整、被测的组件，但还没有接进循环的每一步报文。**
`AgentScopeRunner` 现在仍然用它自己的 `_packet_of`（证据形状，不是 P0–P4 上下文包）。

所以今天的事实是：**模型看到的输入不是 `ContextPacket`**。上下文能力存在、被测、可调用，但**没有被 run 使用**。
这正好是账本里 C08.1 写的"上下文与预算接点"。接的时候要注意：

- 循环里 `ActionGateMiddleware` 已经持有 `progress`；`FactsView` 与 `ObservationStore` **目前只有 bridge 在用**
  （`POLICY_SEARCH_TOOL_NAME` 的命中、`READ_OBSERVATION` 的 store）。要接上下文，**facts 视图与 store 必须由 run 持有**，
  在每次 observation（含 MCP 的五个工具）后 `extract_facts` + `remember`。
- `ContextBuilder.build()` 返回的 `input_tokens` 应该成为**模型调用预算的输入**（现在 `_BudgetHook` 用
  `_estimate_input_tokens` 自己估）。两处都算就会有两个"输入大小"，`docs/agent-harness.md:37` 要的是同一个。
- `CONTEXT_REQUIRED_OVERFLOW` 应作为 run 的停止原因（`OverflowRefusedError.reason_code` 已就位），
  与 `POLICY_INDEX_NOT_READY` 同样的落法。
- 快照（`context_id`/两个 hash/`selected_refs`/`omitted_refs`/`token_count_mode`）要进 C09 的 checkpoint 记录；
  C07.2 只做到"包里有这些字段"。

## 3. C07 交付了什么（可直接当前提）

| 位置 | 现状 |
| --- | --- |
| `harness/facts.py` | facts 视图：来源权威由 `source_type` 派生、无提升操作、同源新读标 STALE、同字段不同值标 CONFLICT 且都保留 |
| `harness/context.py` | P0–P4 组装、输入上限三项取最小、逐段裁剪（最旧优先、P3 先于 P4）、`protected_fact_hash`/`context_hash`、`CONTEXT_REQUIRED_OVERFLOW` |
| `harness/observation_read.py` | `ObservationStore`（按 run、无 case 索引）、offset/limit 拒绝而非截断、NOT_FOUND |
| `harness/local_reads.py` | `SEARCH_POLICY` 与 `READ_OBSERVATION` 共用基类；两者都接进 SDK 工具机制 |
| `policies/` | 索引/检索（C07.1）：从真 Java 拉正文、READY 门、商家/版本硬过滤、dense + BM25 |
| 测试 | `test_context_facts.py`、`test_context_builder.py`、`test_observation_read.py`、`test_context_scenarios.py`（七类 fixture）、`test_context_trimming_demo.py`、`test_observation_read_loop.py`、`test_policy_search_action.py` |

## 4. 会误导判断的坑（C07.2 真踩过，按"最容易误判"排）

1. **`Fact` 是可变的，而这不是偷懒。** 它是"状态会变"的记录：旧行变 STALE、冲突标 CONFLICT，都是**就地**改。
   曾经做成 frozen 并在视图里替换对象，于是 `note()` 返回的引用永远读到 `FRESH`——**身份就是语义**。
2. **P3 与 P4 必须真的不同。** 曾把每一条观察在两层各写一遍（同一个 ref），去重规则于是把 P4 整个删掉，
   而"按需读回"的索引从未发给模型。现在：P3 = 最近 `OBSERVATION_WINDOW`(=2) 条带内容，P4 = 更早那些的索引；
   **去重发生在渲染之前**（按 ref 丢渲染结果会留下后一份内容却挂前一份的 id，等于把证据张冠李戴）。
3. **8 KiB 要按字段有界，不要按字符切。** 按字符切会产生非法 provider 形状（半个 JSON），而且前面一个长 `raw`
   字段会把结构化字段挤出报文。现在是：超长字段换成"读 `<id>` 的 offset=N"的指针（offset 精确到值的第一个字符），
   整段 8 KiB 只作兜底。**offset 必须相对 `_render_observation` 的文本算**，不是相对裸 JSON——差一个 `"<tool>: "` 前缀。
4. **本地读被拒时也要记 `note_evidence(False)`。** 否则 `pending_repeat` 不清理，第三次相同拒绝不被计数，
   run 会一直烧到 `BUDGET_MODEL_CALLS`，把"被拒绝"报成"预算耗尽"。MCP 路径与两个本地读都要。
5. **gate 记了 `stop_reason` 之后，模型调用钩子不能再预占调用。** 它在 adapter 的 `decide` 之前跑，
   所以"已停止的 run"会报错的原因码。已修（钩子先看 stop reason 并具名抛出），新接点别绕过它。
6. **SDK 用工具的 `input_schema` 在执行前校验输入。** 所以 `limit=99999` 根本到不了 bridge：模型收到一条可纠正的
   错误，run 里 `local_reads` 不增长、也没有 observation。**工具边界上的界要在 schema 里写**（并从常量导入，
   别写第二份字面量），bridge 里的检查是第二道、不是唯一一道。
7. **测试里猜 cap 会连错。** `test_context_trimming_demo.py` 因为手写 cap 错了五次（framing allowance 256 在小 cap
   下占主导，必保层比看起来便宜）。现在用**二分搜索**求"刚好不丢东西"的 cap。给裁剪写测试时照抄这个做法，
   并且**断言两个包真的不同**——"tight cap 其实全放得下"会让演示比较两个相同的包，看起来还通过。
8. **`ObservationReadRefusedError` 的 `code` 与 `PolicyIndexNotReadyError` 的 `reason_code` 都要被 bridge 取到**，
   否则 trajectory 里的 reason 与 run 的 reason 会不一致（refusal 基类现在取 `reason_code or code`）。
9. **中文编码**：psycopg 连接要 `client_encoding="UTF8"`（`runtime/db.py` 已处理）；脚本打印前重配 stdout 为 UTF-8，
   否则 `UnicodeEncodeError` 会在**所有检查通过之后**抛出，读起来像失败。
10. **`CaseServiceApplicationTest` 连的是 compose MySQL，不是 Testcontainers**（其余测试是）。改坏 Java 迁移后
    那类测试会因为你留下的 failed 行而红。排查：`case_db.flyway_schema_history` + `information_schema` 逐项清。
11. **`uv run --frozen` 不带 extras**；dense 在缺栈时具名报 `EmbeddingUnavailableError`，不退回 BM25。
    装了 `retrieval` extra 时别把 `python-mypy` 的 override 加回来（见 `agent/pyproject.toml` 里的长注释）。
12. **跑绿门之后先提交**；**推送前问用户**；`git commit` 用 `-F <文件>`（PowerShell 会吃引号、把 `/` 当路径）。

## 5. 命令

```powershell
Set-Location 'E:\Code\Agent+Backend'
$env:JAVA_HOME="C:\Users\hjn\.jdks\jdk-21.0.12.1+1"     # PATH 上的 java 是 17
$env:UV_CACHE_DIR='E:\Code\Agent+Backend\tmp\uv-cache'
$env:PYTHONIOENCODING='utf-8'

cd agent
uv run --project . --frozen pytest tests -q --basetemp='E:/Code/Agent+Backend/tmp/pytest-basetemp-c08'
uv run --project . --frozen ruff check src tests
uv run --project . --frozen mypy                        # 必须在 agent/ 下，strict，基线 9 个错误

cd ..\java && .\mvnw.cmd -B test ; .\mvnw.cmd -B spotless:check
cd .. && pwsh -File scripts/verify.ps1 -Suite all-offline
```

## 6. 未清（不阻塞 C08 的第一步）

- **run 侧 worker 不存在**（属 C09）：`AgentScopeRunner` 可被调用，没人从 PG 队列取 run。
- **模型仍全为 mock**（`modes={'mock'}`），H1 未验证；`MODEL_INFERENCE` 权威枚举已就位但**没有生产者**
  （要等 C08 的真实模型适配）。
- **C07.2 的 `ContextBuilder` 未接进循环每步报文**（见 §2，这是 C08.1 的活）。
- Java 仍有 4 个 skipped（`CoreEventTransportSystemTest` 等），**是没跑不是绿的**。
- `all-offline` 不跑 `agent/tests/integration`、不跑真实 Java↔Python 联调；它的 `python-mypy` 用 `agent/src` 而非 strict 全量。

## 7. 规矩（照旧）

**不擅自推送**、**不清库删卷**、迁移**只追加**、**不为通过而删断言**、**不提交密钥**、
真实记录**日期/文件/实际命令/结果/失败/未运行项**。规范冲突要指出并解决，不任选方便版本。
