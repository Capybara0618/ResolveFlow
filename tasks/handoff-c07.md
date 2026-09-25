# C07 交接（2026-09-25）· 政策检索与上下文

给新会话读的一份自足交接。**先读 `tasks/todo.md` 的 C07 段（`:1242-1249`）与 AS00–AS02.3 各条**（那里有逐条命令/
结果/欠账）；C07 的两份规格是 **`docs/policy-rag.md`（C07.1）** 与 **`docs/context-engineering.md`（C07.2）**，
必须整篇读。本文件只讲"现在站在哪、下一步做什么、哪些前提可以信任、哪些坑会误导判断"。

---

## 0. 交接时的仓库状态（已推送）

```
家：E:\Code\Agent+Backend        ← 就是本文件所在（E:\Code\ 里面，名字是 "Agent+Backend"，中间是反斜杠）
交接快照：4ac5e71（AS02.3 安全子步 · Python 侧）
```

**开工第一件事（状态一律以仓库为准，不要以本文件写的 sha 为准）**：

```powershell
Set-Location 'E:\Code\Agent+Backend'
(Get-Location).Path              # 必须是 E:\Code\Agent+Backend（没有加号）
git log --oneline -1             # 应不早于 4ac5e71
git status --porcelain           # 应为空
git rev-list --left-right --count origin/main...HEAD   # 应为 "0	0"
Test-Path tasks\handoff-c07.md   # 必须是 True
```

任一条不符 → **停下并报告，不要在错的目录里改任何东西**。

**这个仓库在同一台机器上被会话之外的进程静默回退/删除过两次**（2026-09-22、2026-09-23）。规矩：
**验证过的提交要尽快推到远端**；但**不擅自推送**，推送前需要用户点头（用户这几轮都是逐轮点头的）。

### 本会话（交接前的这一段）的提交轨迹

```
4ac5e71  AS02.3 安全子步 · Python 侧：scope 是集合，且按路由提问
675ec11  账本更正：all-offline 门一直在跑，并刷新顶部状态
96a4200  AS02.3 安全子步：Java 逐路由强制工具凭据的 scope（缺口关闭）
69ea09c  AS02.3 完成：新循环经真实 MCP stdio 读取运行中的 Java（端到端 PASSED）
59e9625  AS02.2 收尾：生产只剩一套循环（AgentScope），旧测试改跑新循环
7576223  AS02.2（大部分）：SDK 循环装配 + 同一套语义断言在两个循环上双跑
7125701  AS02.1 锁定正式依赖与薄 SDK 边界适配
b9bb611  AS01.3 完成：禁网络 strict 回放探针
96eda18  AS01.2 完成：用户两条决定落地 + 真实 PG 恢复关卡全绿
b70ed7e  AS01.2 能力探针：恢复路径存在（ExternalExecutionResultEvent）
3786620  AS00/AS01.1 账本同步
2ae463e  v1.3 文档 + AS00 基线 + AS01.1 spike
092e1f9  C06.4⑤ 收口（接管）
```

## 1. 一句话位置

**C00–C06 全部完成，AS00–AS02.3（AgentScope 迁移插入段）全部完成并已推送**。生产只有**一套** Agent 循环
（AgentScope 2.0.8 驱动的 `AgentScopeRunner`），五个 MCP 工具经**真 stdio** 读**真 Java**，工具凭据的
scope 在 **Java 与 Python 两侧都已强制**。项目门禁 `all-offline` PASSED。

**下一件事：C07 —— 政策检索与上下文**，依赖 C03/C06 核心前置与 AS02.3，**全部已满足，无阻塞**。

## 2. 已验证的事实（可以当前提，不必重新论证）

- **门禁基线（本会话实测，2026-09-25）**：
  - Java 全量 `mvnw -B test` → **382 例 0 失败**（shared-kernel 59 / gateway 5 / commerce 93 / fulfillment 2 /
    case-service 223 + **4 skipped**）。那 4 个 skipped 是**没跑**，不是绿的。
  - Python `pytest agent/tests` → **791 passed, 9 skipped**。
  - `ruff check src tests`（在 `agent/` 下）→ **All checks passed**。
  - **strict `mypy`（必须在 `agent/` 下跑）→ 9 errors in 4 files (checked 40)**，全部**既有**、与新代码无关：
    `core_corpus.py`×4、`provider_stub/__init__.py`×3、`_schemaio.py`×1、`fixtures.py`×1。
    **新增模块必须零新增错误**——这 9 个是基线噪音，不是让你修的任务。
  - `spotless:check` → BUILD SUCCESS。
  - `pwsh -File scripts/verify.ps1 -Suite all-offline` → **PASSED**
    （`reports/verify/20260925-163004-all-offline.txt`）。
- **真实 Java↔Python 工具 e2e 跑得通**：`& 'agent\.venv\Scripts\python.exe' 'scripts\e2e_harness_java_tools.py'`
  → **RESULT: PASSED (35.6s)**（`reports/c064-e2e/20260925-161114-e2e-harness-java-tools.txt`）。它自己起
  case-service(8083)+commerce-service(8081)、自己铸订单行、自己取 run 凭据，**不需要手动造数据**。
  它并不启动 MySQL —— **MySQL 必须先由 compose 起着**（`docker ps` 里应有 `resolveflow-mysql-1`）。
- **pgvector 已经真的可用**（C07.1 直接吃这个，不必再论证）：compose 用的是 `pgvector/pgvector:pg16`，
  运行中的 PG 是 **16.15**，扩展 **vector 0.8.6 已安装**，`agent` 用户**是 superuser**（所以测试用的临时
  schema 里也能 `CREATE EXTENSION IF NOT EXISTS vector`），`SELECT '[1,2,3]'::vector` 可解析。
- **网络可达**（C07.1 要下真模型）：`pypi.org` / `huggingface.co` / `modelscope.cn` 均返回 200。
- **C07.1 的"权威政策正文"目前 Python 侧读不到，这是一个真实的设计决定，不是现成能力**（**我第一版交接写错过这里，
  核对源码后改正**）：Python 的工具目录只有**五个**工具
  （`get_order_context`/`get_shipment_trace`/`get_refund_status`/`get_case_evidence`/`get_policy_manifest`，见
  `tools/catalog.py:37-47`），**没有 `get_policy_bundle` 这种东西**。`get_policy_manifest` 读的是
  `case:/internal/v1/cases/{case_id}/policy-manifest`，它只给出 `bundles[0].manifest_hash`
  （`catalog.py:398-406`，且那里写明"只有这个成员能说明是哪套政策决定了本工单"）——**拿到的是 hash，不是规则正文**。
  规则正文在 Java 的 `GET /internal/v1/policies/{bundle_id}`（`PolicyController`，需要 `policy:read` scope，
  已强制），**Python 侧今天没有任何代码去读它**。
  **所以 C07.1 第一步要先定：索引的规则正文从哪里来**（受控导入脚本？给 Harness 加一条不暴露给模型的内部读？
  两者都要把 `manifest_hash` 与正文对上，否则"引用校验"会变成自证）。这是 C07.1 的**核心设计点**，
  不要当成已经有的能力。

## 3. C07 的起点：代码现在到底是什么

| 位置 | 现状（已核对） |
| --- | --- |
| `agent/src/resolveflow/policies/` | **只有 1 行 `__init__.py`，完全空包。C07 从这里开始。** |
| `agent/src/resolveflow/harness/` | 已实打实：`sdk_runner.py`（唯一循环）、`sdk_adapter.py`、`vocabulary.py`、`actions.py`、`budget.py`、`control.py`、`model.py`、`mcp_client.py`、`runner.py`（**只是再导出 shim，没有 `while`**） |
| `harness/actions.py` | 六动作 ABI 已定义并校验（`READ_TOOL`/`SEARCH_POLICY`/`READ_OBSERVATION`/`ASK_CUSTOMER`/`PROPOSE`/`ESCALATE`），**`SEARCH_POLICY` 连参数校验都写好了**（`_check_policy_search`：必须带 `query`、`top_k <= MAX_POLICY_TOP_K`，`actions.py:222/308-313`）。**但 sdk_runner 里对 `SEARCH_POLICY`/`READ_OBSERVATION` 没有任何处理分支**——校验通过的动作没有执行者，`reserve_local_read` 也**无人调用**。C07 要做的是**给这两个已定义的动作接上执行体**，不是新造动作 |
| `harness/budget.py` | `reserve_local_read()` 已存在且已实现（注释就写着"policy search 和 READ_OBSERVATION，不是 MCP 调用"）：**本地读取预算 8 次**的接口已经备好，**目前零调用**，C07 来接 |
| `runtime/migrations/` | `001_agent_run.sql`、`002_agent_callback_outbox.sql`、`003_agent_callback_dead.sql`。**迁移是 append-only**，每个文件在每次启动时按文件名顺序跑（`runtime/db.py:6`）。政策索引需要**新增 `004_...sql`，不要改已有文件** |
| `runtime/db.py` | `apply_migrations` 在每个测试 schema 里跑（`--basetemp` + 独立 schema）；`DEFAULT_SCHEMA="public"` |
| **上下文侧** | **`ContextPacket`/`protected_fact_hash`/`context_hash`/`omitted_refs` 在 `agent/src` 里一个都没有**（只有 `actions.py` 的动作名和 `budget.py` 的注释提到）。C07.2 是从零做 |
| `agent/pyproject.toml` | `[project.optional-dependencies]` 里有 **空的 `retrieval = []` 与 `eval = []`**，注释明写"Retrieval stack lands with T19 (policy index)"、"pulling sentence-transformers now would add roughly 2 GB of transitive torch" —— **C07.1 就是来填这个坑的** |

### 政策语料现状（**C07.1 的主要工作量在这里，不在算法**）

- 仓库里只有 **2 个 bundle、共 8 条规则**（`fixtures/policies/bundles/`：2026.08 有 3 条、2026.09 有 5 条），
  而且**只有 1 个商家**（`policy-logistics`）。
- **`docs/policy-rag.md:29` 要求"至少 20 个规则段落、2 商家、2 历史版本"** → **语料必须扩写**，这是硬缺口。
- Python 侧目前**完全不读**这些 YAML（grep `fixtures/policies` 在 `agent/` 下零命中）。Java 侧读它们做
  `PolicyImportService` 的受控导入。**别把"Java 那边有政策 fixture"误当成"C07.1 的检索语料已经有了"**。
- 导入校验的规则（`fixtures/policies/README.md` 有全文）会拒绝：同一 `effective_from` 出现两次；起点早于
  已装版本的；跨越显式结束窗口的。**新增 bundle 前先读那份 README**，否则会被导入校验拒掉而看起来像 bug。

### C07 两片（原文取自 `tasks/todo.md:1244-1248`）

1. **C07.1**：固定 bundle 索引、**真实** dense 与 BM25 基线、版本/商家过滤、引用。
2. **C07.2**：ContextBuilder 关键事实/来源/冲突保真、token 上限、原文索引及 scope 读回。

- **验收（账本原文）**：索引未就绪**不搜旧版本**；关键字段**不被摘要改写**；超限**明确终止**，原文可按 ref 读回。
- **C07.1 规格要点**（`docs/policy-rag.md`）：规则小节分块且**禁止把例外切掉**，块上保留
  `rule_id`/`bundle`/`version`/`hash`；**先硬过滤**（merchant/category/manifest/bundle/version）**再做** dense cosine，`top_k<=5`；
  **PG/pgvector 精确扫描足够，不启用 HNSW**；**BM25 是离线基线而非默认第二路在线召回**；
  hybrid/RRF/rerank **退出必做**。embedding 必须**实测可用**并**固定 revision/维度/许可与资源开销**，**不伪造**；
  资源/下载受限时**先用 fixture 测流程，但真实检索结果仍需实际 embedding 实验**。40 条查询（20 dev/20 冻结 test，
  按语义家族分离），报告 **Recall@5、版本/商家正确性、查询耗时与错误**；**dense 不优于 BM25 也要如实报告**。
- **C07.2 规格要点**（`docs/context-engineering.md`）：三层记录（原文 / facts 视图带
  FRESH/STALE/CONFLICT/UNVERIFIED / ContextPacket）；来源分 AUTHORITY/USER_CLAIM/MODEL_INFERENCE 且
  **不得因摘要或重复出现而升级权威**；P0–P4 分层，**P0 不可裁剪**；输入上限
  `min(8192, provider容量-输出预留-256, 累计剩余输入)` 且**计入 system/tool schema/provider 包装**；
  超限先转索引，仍超限则 **`CONTEXT_REQUIRED_OVERFLOW` 转人工，不删约束**；`READ_OBSERVATION(offset>=0,
  limit<=4000)` **只访问当前 run**，不存在返回 `NOT_FOUND`，**总本地读取<=8 次**；快照保存
  `context_id`/`run`/`step`/`manifest_id`/实际 messages 与 tool schema hash/`token_count_mode`/
  `selected_refs`/`omitted_refs`/`protected_fact_hash`/`context_hash`。
  **七类 fixture 必须覆盖**：长物流、矛盾来源、缺引用、超限、恶意正文、跨 scope 读回、合法 tool pair。

## 4. 现在最该先做的判断（C07.1 第一步，别跳过）

**embedding 模型选型是一次真实取舍，必须先做一次小规模实测再写进任何代码。** 项目现有的
`docs/stack-and-sources.md:24` 只锁定"jieba、rank-bm25、sentence-transformers"这条技术路线，**没有指定具体模型**；
`docs/policy-rag.md:19` 要求"沿用原选择的本地中文 embedding 候选及 T00 已锁 Python 依赖，C07 实测可用模型并固定
revision/维度/许可与资源开销"。

- 语料是**中文**，所以 `sentence-transformers` 的英文默认模型（如 `all-MiniLM-L6-v2`）**不适合**，别默认它。
- 加 `sentence-transformers` 会拉进 **~2 GB 的 torch**。**这是需要用户点头的取舍**（`AGENTS.md` 要求不擅自扩大
  依赖/资源）。可行的退路是：**先只加 `jieba` + `rank-bm25`（纯 Python、无 torch）把语料、硬过滤、BM25 基线与
  评测框架做完，把 dense 那一路留成一个显式的、被记录的阻塞项**——这符合 `docs/policy-rag.md:19`"资源受限时先用
  fixture 测流程"，但**不能把 dense 写成已完成**。
- 无论选哪条，**模型 revision/维度/许可/资源开销都要写进记录**，并落进 `[project.optional-dependencies].retrieval`。

## 5. 命令（照抄，环境已配好）

```powershell
Set-Location 'E:\Code\Agent+Backend'
$env:JAVA_HOME="C:\Users\hjn\.jdks\jdk-21.0.12.1+1"     # PATH 上的 java 是 17，跑 Maven 必须显式给

# Python 门（agent/.venv 已存在，锁已冻结；一律 --frozen）
$env:UV_CACHE_DIR='E:\Code\Agent+Backend\tmp\uv-cache'
cd agent
uv run --project . --frozen pytest tests -q --basetemp='E:/Code/Agent+Backend/tmp/pytest-basetemp-c07'
uv run --project . --frozen ruff check src tests
uv run --project . --frozen mypy                        # 必须在 agent/ 下跑，strict，基线 9 个错误

# Java 门（只在改了 Java 时才需要；C07 大概率不需要）
cd ..\java
.\mvnw.cmd -B test
.\mvnw.cmd -B spotless:check

# 项目门禁（~4 分钟；注意它不跑 python 集成测试，见陷阱 2）
cd ..
pwsh -File scripts/verify.ps1 -Suite all-offline

# 真实 Java↔Python 工具 e2e（需要 compose 的 MySQL 已在跑）
& 'agent\.venv\Scripts\python.exe' 'scripts\e2e_harness_java_tools.py'
```

- **`--basetemp` 不是可选项**：本机 `%TEMP%` 对 pytest 不可写（WinError 5），不用它测试直接崩。
- 单测选择器要加 `"-Dsurefire.failIfNoSpecifiedTests=false"`，**引号必需**。
- **日志一律重定向到文件再读**——管道退出码不可信；红跑与绿跑用**不同文件名**（踩过坑）。

## 6. 会误导判断的坑（**本会话真的踩过前三个**）

1. **写进账本/提交信息前，先查 `reports/` 里有没有反例。** 本会话我说过
   "`-Suite all-offline` 是**本项目第一次**真的运行"——**完全错了**，`reports/verify/` 下有约 30 份历史报告，
   最近一份 `20260923-183411-all-offline.txt` 就是 PASSED。**"我这次没做"不等于"从来没人做"**。
   同类错误还有一次：`@AutoConfigureRestTestClient` 单独使用**不换掉** `@SpringBootTest` 的 MOCK 环境，
   MOCK **不建容器、不跑 servlet filter**，于是 4 个反例（含伪造签名）全返回 200，**当时根本没在测**。
   **若只写正例，这个错误会以全绿交付。**
2. **`all-offline` 的真实覆盖边界**（比"跑没跑"更重要）：`format`（java-spotless / python-ruff /
   python-mypy / web-typecheck）、`unit`（java **全量** / python **仅 `agent/tests/unit`** / web-test）、
   `contracts`、`smoke`（起 gateway/case/commerce/agent 探活）。
   它**不跑 `agent/tests/integration`**，也**不跑**真实 Java↔Python e2e；`python-mypy` 用的是 `agent/src`
   而非 strict 全量，**和上面那条 strict `mypy` 不是同一个检查**。所以 "all-offline PASSED" **不能**读成
   "集成与真实联调也通过"。
3. **`fixtures/policies/bundles/` 那 2 个文件不是 C07.1 的检索语料，也不是 Python 能直接读的东西。** 它们是 Java
   受控导入的不可变政策版本，共 **8 条规则、1 个商家**，而规格要 **≥20 段落、2 商家、2 版本**。同时（见 §2 最后一条）
   **Python 侧今天读不到规则正文**。这两件事合起来的结论是：C07.1 要**先决定正文来源**，再**扩语料**；
   把"解析仓库里的 YAML 建索引"和"用 Java 的 hash 校验引用"混为一谈，会让引用校验变成对自己写的 fixture 自证。
4. **`rg`/`grep` 的 `-l` 与 PowerShell 管道**：本会话 `Select-String -Pattern ... -List` 一次只给首个匹配文件，
   差点让我误判"只有一处"。**在文件清单上做结论前，用能列出全部命中的方式复核。**
5. **`git commit -m` 里避免中文引号/正斜杠**（PowerShell 会把 `/` 解释成路径、把引号吃掉）。**用 `-F <文件>`**
   提交（`tmp/` 已 gitignore，提交信息文件放那里最省事）。
6. **`spotless:apply` 会重排代码**：刚跑过 spotless 后再编辑**必须先重读文件**。
7. 推送偶发 `schannel: failed to receive handshake, SSL/TLS connection failed`，**重试即可成功**。
8. **账本教训**：**摘要行不是状态**——状态要看该工作包内**最后一条完成记录**。`tasks/todo.md` 里 C06.1/C06.2/C06.3
   的复选框仍是 `[ ]`，但下面有很长的完成记录；**别据`[ ]` 判未完成**，也别据旧摘要判已完成。
9. 可能仍有并行客户端在改同一仓库（`AGENTS.md` 开头警告）→ 发现同文件并行编辑先确认交接，**不覆盖别人的改动**。

## 7. 未清（不阻塞 C07，别丢）

- **run 侧 worker 不存在**：`AgentScopeRunner` 是可被调用的类，**没人从 PG 队列里取 run 来跑**。
  "派发 → run 被跑 → 回调"这条线**断在 Agent 侧**（属 **C09**，不是 C07）。所以 C07 的检索/上下文**不会**被
  自动跑起来，验证要走 C07 自己的测试与脚本。
- **模型仍全为 mock**：`modes={'mock'}`。**H1 自主性未验证**（属 C08/C12）。C07 的检索评测不需要 live 模型，
  但**不要**把 mock 通过写成 live。
- **Python 侧目前没有任何路由要求 `commerce:read`/`policy:read`**：scope 强制已两侧就绪（`ServiceTokenVerifier`
  已按"scope 是集合、按路由提问"实现），但 Python 侧**还没有一条路由真的提出要求**。C07.1 若给 Python 自己加
  读策略的内部路由，**那就是第一个消费方**，记得按路由传 `required_scope`。
- **`policy:read` 只覆盖工具用到的那两条路由**（`policy-manifest` 与 `/internal/v1/policies`），**不覆盖**
  "读工单材料原文"的公共路由；回调与证据读两条内部路由**故意无 scope**（决定写在
  `caseservice/internal/ServiceTokenFilter.requiredScope` 的 javadoc 里）。
- **AS01.2 的恢复探针只做在独立 spike 里**（`spikes/agentscope/`，36 例全绿）。C09 的"持久恢复"风险已被提前
  验证过，**不是从零开始**——那份 spike 是 C09 的起点，别重做。
- **C08–C13 未开始**。C07 之后按 `tasks/plan.md:26-27`：C05+C07→C08→C09；C09→C10；C08→C11；
  C09+C10+C11→C12→C13。

## 8. 规矩（`AGENTS.md` 摘要，照旧）

**不擅自推送**（推送前问用户）、**不清库删卷**、迁移**只追加**、**不为通过而删断言**、
**不提交密钥**、**不开未经确认的收费评测**、真实记录**日期/文件/实际命令/结果/失败/未运行项**——
不得只勾任务。规范冲突要**指出并解决**，不任选方便版本。
