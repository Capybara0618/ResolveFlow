# C08 交接（2026-09-25，第二轮）· 从这里继续

给新会话读的一份自足交接。**C07 全部完成；C08.1 的"上下文与预算接点"完成，其余未做。**
本文件取代不了上一份：`tasks/handoff-c08.md` 仍要读（它有 C07 交付清单与 12 条坑），
本文件只讲**第一份之后发生的事**、现在的准确位置、以及下一个决策点。

## 0. 开工第一件事（状态一律以仓库为准）

```powershell
Set-Location 'E:\Code\Agent+Backend'
(Get-Location).Path              # 必须是 E:\Code\Agent+Backend（没有加号）
git log --oneline -1             # 应能看到标题含 "C08.1（第二部分）" 的那一条
git status --porcelain           # 应为空
git rev-list --left-right --count origin/main...HEAD   # 若为 "2  0"，说明本地领先、**尚未推送**
```

任一条不符 → 停下并报告。

**推送状态**：`39138d2`（C08 交接）已推送；`8160ce0`、`0cf689f` **在本地未推送**。推送前问用户。

## 1. 现在站在哪（准确的一句话）

**模型在测试里已经能收到 P0–P4 上下文报文，但生产默认路径上收的仍是 C06.4 证据包。**
也就是说：C07.2 交付的 ContextBuilder 现在**接进去了、被测过了**，但**默认没开**——
开关是 `AgentScopeRunner.use_context_builder`，默认 `False`。

所以今天**不能**说"模型看到的输入是 ContextPacket"。这是一个开了就成立的开关，不是一个已完成的状态。

## 2. 下一个决策点（新会话第一件事，需要用户点头）

**要不要把 `use_context_builder` 默认翻成 `True`。** 实测数据（两个数字都要看，否则会误判）：

| 时点 | 红掉的测试数 |
| --- | --- |
| 适配器**还没**转发 `context`/`sent_context` 时测 | **5** |
| 适配器修好之后重测 | **58** |

**为什么差这么多**：开关没真正生效时，`model.packets` 里仍有证据，老的断言照样通过；
一旦真走上下文报文，`model.packets` 不再承载证据，而 C06 的循环语义测试大量依赖它读观察与预算。
**教训写在这里：一个还没真正生效的开关，测出来的影响面必然偏小。** 我第一次就是拿 5 这个数字做的判断，
它在下一轮被推翻。

两条路，任选，**都要先问用户**：

- **A：这一次翻转默认**（推荐给"要让规范成为事实"的目标）。做法是把那约 58 处断言改读新输入形状。
  机械但量大，而且**必须逐条确认语义没变**——它们断言的是"非法动作不执行""无进展会停""预算被计"这类
  真正的语义，改的是读取路径而不是主张。`tests/conftest.py` 的 `input_text_of` 已经是为此准备的一个入口。
- **B：保持默认关闭**，在 C08.2 接 worker 时由 worker **显式**开启（`use_context_builder=True`）。
  好处是改动面小、可回退；代价是"默认路径"与"规范路径"继续分叉，而分叉本身是将来某次误判的来源。

不管选哪条，**都不要**在同一个改动里既翻默认又改 worker：那是两件事，混在一起会让回归互相掩盖。

## 3. C08.1 已经做掉的（可直接当前提）

- `AgentScopeRunner` 持有 run 自己的 `FactsView` 与 `ObservationStore`（调用方可传入以事后检查）；
  新增字段：`facts_view`、`use_context_builder`、`context_provider_capacity`、`context_output_reserve`、
  `last_client`。
- **run 记录每一个 observation**：`_GateAwareClient.note_evidence` → `extract_facts` + `ObservationStore.remember`。
  此前视图/store 只有 `PolicySearchBridge` 能碰到 → 五个 MCP 工具（金额、物流结论、退款状态都从这里来）
  一条事实都不贡献、原文也读不回来。这是 C07.2 留的真正口子。
- **报文在预算预占之前构建**：`_BudgetHook.on_model_call` → `client.begin_turn()` → `client.prepare_packet()`，
  adapter 复用同一对象。预占的输入规模与模型实收请求是**同一个数**（`docs/agent-harness.md:37`）。
- **超限**：`OverflowRefusedError` 在 `_drive` 被单独捕获 → run 以 `CONTEXT_REQUIRED_OVERFLOW` 停止，
  且请求根本不到 provider。
- **`ModelClient.decide` 有两个新参数**，分开是有原因的：
  `context` = 运行自己的结构化视图（observations/budget/step，**脚本用它**，例如翻页要上一次的 cursor）；
  `sent_context` = 这一次真正发出的 P0–P4 报文。合成一个就只能二选一。`MockModelClient` 分别记
  `contexts` / `sent_contexts`；`AgentScopeModelAdapter._call_api` 两者都转发。
- `sdk_adapter.raw_text_message`：P0–P4 报文按**文本**发。用 `messenger_message` 会把它序列化成
  `{"content": "..."}`，模型读到的是装着报文的 JSON 字符串。
- 测试：`tests/integration/test_context_wiring.py`（7 例）。`tests/conftest.py` 的 `input_text_of` 一个入口读两种输入形状。

## 4. C08 还剩什么

- **C08.1 未做**：真实模型适配（现在仍全 mock，`modes={'mock'}`）；候选引用验证；H1 自主性。
  另外默认开关见 §2。
- **C08.2 全部未做**：PG 待办调查 worker、与问题/方案/失败 callback_outbox 组合、补证新 run、
  旧结果 STALE、Java 复核后退款、单执行者闭环。
- **run 侧 worker 仍不存在**（C09 也依赖它）：`AgentScopeRunner` 是可被调用的类，没人从 PG 队列取 run。
  所以今天 C07/C08.1 的能力**都不会被自动跑起来**——验证靠测试与脚本。

## 5. 会误导判断的坑（这一轮真踩的，接在上一份的 12 条之后）

13. **turn 计数不要放在"重建报文"的分支里。** 曾写成 `if 需要重建: self.turns += 1`，
    于是第一次构建把 `turns` 锁在 1，`_packet_step != turns` 永远为假，**整轮 run 每一步都发第一份报文**，
    模型永远看不到它学到的事实（症状是 P2/P3 一直是空的）。诊断脚本抓到的。
    现在由 `begin_turn()` 在**模型调用边界**推进（`_BudgetHook` 调，decide 不调）。
14. **别把已渲染的报文再序列化一层。** `messenger_message` 是给"结构化 packet"用的；散文要走
    `raw_text_message`。错了不会报错，只会让模型读到 JSON 字符串——**静默错**。
15. **`conversations[turn]` 是消息列表，不是一条消息。** 测试 helper 里因此 `AttributeError` 红了两个测试。
    另外 `MockModelClient.conversations` 对两条路径含义不同：C06.4 路径下它是 SDK 的对话（含证据包），
    上下文路径下它是我们发出的 P0–P4 三/四条。`input_text_of` 因此先看 `packets` 再看 `conversations`。
16. **`context` 必须是映射（dict），不是消息列表。** 传 `_with_current_packet(...)` 会静默变成
    "一个 Msg 列表"，`ModelClient` 的 `context` 参数语义就废了。正确的是
    `_packet_of(self._runner, self._guard, self.observations, self.turns)`。
17. **改共享协议前先数影响面，但要知道这个数字可能偏小**（见 §2 的 5 vs 58）。
    实战做法：改协议 → 修好所有实现 → **再**测影响面；只测一半得到的数字不能用来做"要不要做"的决定。
18. **`use_context_builder=False` 的路径仍要是绿的**，因为它是默认。翻转前那条路必须一直有用例覆盖。

## 6. 命令（与上一份相同，路径已改 C08）

```powershell
Set-Location 'E:\Code\Agent+Backend'
$env:JAVA_HOME="C:\Users\hjn\.jdks\jdk-21.0.12.1+1"     # PATH 上的 java 是 17
$env:UV_CACHE_DIR='E:\Code\Agent+Backend\tmp\uv-cache'
$env:PYTHONIOENCODING='utf-8'

cd agent
uv run --project . --frozen pytest tests -q --basetemp='E:/Code/Agent+Backend/tmp/pytest-basetemp-c08'
uv run --project . --frozen ruff check src tests
uv run --project . --frozen mypy                        # 必须在 agent/ 下，strict，基线 9 个错误

cd ..\java ; .\mvnw.cmd -B test ; .\mvnw.cmd -B spotless:check
cd ..    ; pwsh -File scripts/verify.ps1 -Suite all-offline
```

**本次实测（C08.1 收口时）**：`pytest tests` → **910 passed, 9 skipped**；ruff All checks passed；
strict mypy **9 errors = 基线，零新增**；`all-offline` → **PASSED**
（`reports/verify/20260925-230443-all-offline.txt`）。**Java 全量本次未跑**——本轮只改了 Python，
Java 最后一次全量是 C07.1 收口时的 **BUILD SUCCESS**（385 例 0 失败、4 skipped，那 4 个是"没跑"）。
Java 未跑这件事在新会话里仍成立，除非它自己跑过。

## 7. 规矩（照旧）

**不擅自推送**、**不清库删卷**、迁移**只追加**、**不为通过而删断言**、**不提交密钥**、
真实记录**日期/文件/实际命令/结果/失败/未运行项**——不得只勾任务。
规范冲突要指出并解决，不任选方便版本。
