# C07.2 交接（2026-09-25）· ContextBuilder 与 READ_OBSERVATION

给新会话读的一份自足交接。C07.1（政策索引与检索）**已完成并提交**（`49febf4`）。本文件只讲
"现在站在哪、下一步做什么、哪些前提可以信任、哪些坑会误导判断"。

## 0. 开工第一件事（状态一律以仓库为准）

```powershell
Set-Location 'E:\Code\Agent+Backend'
(Get-Location).Path              # 必须是 E:\Code\Agent+Backend（没有加号）
git log --oneline -1             # 应能看到标题含 "C07.1 完成" 的那一条
git status --porcelain           # 应为空
git rev-list --left-right --count origin/main...HEAD   # 若为 "1  0" 说明本地领先，本步**尚未推送**
Test-Path tasks/handoff-c07.md   # True（C07.1 的第一份交接，仍应读）
```

任一条不符 → 停下并报告，不要在错的目录里改任何东西。

**本步未推送**：提交在本地（`49febf4`），按规矩**推送前需要用户点头**。

## 1. 一句话位置

**C00–C06、AS00–AS02.3、C07.1 全部完成。** 政策检索已经端到端跑通：真 Java 提供正文与 hash、
真 `BAAI/bge-small-zh-v1.5` 提供向量、READY 门与商家/版本过滤实测有效、40 条查询评测已出报告。
**下一件事：C07.2 —— ContextBuilder 与 `READ_OBSERVATION`**，依赖 C07.1（已满足）。

## 2. C07.1 留下了什么（可直接当前提，不必重新论证）

| 位置 | 现状 |
| --- | --- |
| `agent/src/resolveflow/policies/` | `chunking.py`（规则即块，不切例外；hash 与 Java 同构造）、`retrieval.py`（dense + BM25，模型常量已固定）、`index.py`（`PolicyIndex`：build/READY 门/硬过滤/引用） |
| `agent/src/resolveflow/runtime/migrations/004_policy_index.sql` | `policy_index_generation` + `policy_index_chunk`；**向量存 `real[]` 而不是 pgvector**——原因写在文件头（本机实测：schema 受限连接下 `vector` 类型与 `<=>` 都不可达） |
| `agent/src/resolveflow/harness/sdk_runner.py` | `PolicySearchBridge` 已接进 SDK 工具机制；`_outcome`/packet 的 tool_attempts 改为读 guard 计数 |
| `agent/src/resolveflow/harness/actions.py` | `POLICY_SEARCH_TOOL_NAME`/`OBSERVATION_READ_TOOL_NAME` 常量；`_check_policy_search` 原有校验 |
| `agent/src/resolveflow/harness/budget.py` | `reserve_local_read()` **现在真的被调用**（每次 SEARCH_POLICY 同时计 search attempt 与 local read） |
| Java | `merchant_id` 进 bundle 源与 `manifest_hash`、进 `case_policy_manifest`、选版本按商家；迁移 `V17__policy_bundle_merchant.sql` |
| 契约 | `openapi-agent.yaml` 的 `PolicyManifestRef`、`openapi-case.yaml` 的 `PolicyManifestResponse`/`PolicyBundle` 都已含 `merchant_id` |
| 语料 | `fixtures/policies/bundles/` 4 个 bundle / 2 商家 / 23 条规则；README 有成员表与导入命令 |
| 证据 | `reports/c071-policy-index/`：`e2e.txt`、`retrieval-eval-both.txt`、`embedding-probe.txt` |

## 3. C07.2 要做的事（规格：`docs/context-engineering.md`，必须整篇读）

**核对结果：`ContextPacket`/`protected_fact_hash`/`context_hash`/`omitted_refs` 在 `agent/src` 里仍然一个都没有**
（`harness/context*` 不存在）。C07.2 是从零做。规格要点见 `tasks/todo.md` 的 C07 段与
`docs/context-engineering.md`，其中与本步最相关的几条：

- 三层记录：原始留存 / facts 视图（值+来源+source_version/hash+FRESH·STALE·CONFLICT·UNVERIFIED）/ ContextPacket。
  来源分 AUTHORITY/USER_CLAIM/MODEL_INFERENCE，**不得因摘要或重复出现而升级权威**。
- P0 不可裁剪；输入上限 `min(8192, provider容量-输出预留-256, 累计剩余输入)`，**计入 system/tool schema/provider 包装**；
  超限先转索引，仍超限则 **`CONTEXT_REQUIRED_OVERFLOW` 转人工，不删约束**。
- `READ_OBSERVATION(offset>=0, limit<=4000)` **只访问当前 run**，不存在返回 `NOT_FOUND`，
  **总本地读取<=8 次**——那个计数器 C07.1 已经接好（`reserve_local_read`），执行体还没写。
- 快照保存 `context_id`/`run`/`step`/`manifest_id`/实际 messages 与 tool schema hash/`token_count_mode`/
  `selected_refs`/`omitted_refs`/`protected_fact_hash`/`context_hash`。
- **七类 fixture 必须覆盖**：长物流、矛盾来源、缺引用、超限、恶意正文、跨 scope 读回、合法 tool pair。

**可以复用的东西**（别重造）：

- `actions.OBSERVATION_READ_TOOL_NAME` 已定义；`ActionGateMiddleware` 的 `allowed_name` 分支已经认
  `READ_OBSERVATION`（C07.1 顺手接的），所以**执行体一写就能被 gate 放行**。
- `PolicySearchBridge` 是"本地读执行体"的现成样板：预算两次预占、失败记录自己的 stop reason、
  observation 带 `source_ref`/`content_hash`、`record_observation` 判新证据。照它写 `ObservationReadBridge`。
- `_policy_observation` 展示了一个 observation 该带哪些可引用成员。
- `PolicyIndex` 的 READY 门写法（"未就绪要报错而不是给旧版本"）在 ContextBuilder 里会再次用到——原文索引未就绪
  同样不能悄悄换一份内容。

## 4. 会误导判断的坑（C07.1 真的踩过，按严重程度排）

1. **`CaseServiceApplicationTest` 连的是 compose MySQL（localhost:3306），不是 Testcontainers。**
   其余测试用 Testcontainers。所以：**改坏一个 Java 迁移后，那个类会因为你留下的 failed 行而红**，看起来像
   被测代码坏了。排查顺序：`SELECT version, success FROM case_db.flyway_schema_history` +
   `information_schema.COLUMNS/STATISTICS`，把 V17 的列/索引/历史行**逐项**清干净再重跑（我在这上面花了三次红跑）。
2. **`PolicyImportCommand` 以 `System.exit` 结束**：把 `--resolveflow.policy.import-dir` 传给 **web 服务**，
   它会在 Tomcat 起来几秒后把自己关掉——看起来像"服务起不来"。必须两段式：一次性
   `--spring.main.web-application-type=none` 导入进程 + 独立 web 服务。fixtures README 已写明。
3. **PATH 上的 `java` 是 17**；跑 jar 会 `UnsupportedClassVersionError`（看起来像 jar 坏了）。
   `scripts/c071_policy_index_e2e.py` 里的 `resolve_java()` 按 `verify.ps1` 的顺序解析 JDK21，照抄即可。
4. **`~/.m2` 里的 `shared-kernel` 可能是陈旧的桩**（我遇到的是 3.7 KB、没有 `JwtCodec`），
   于是 fat jar 跑起来 `NoClassDefFoundError`。跑 `mvnw -B -DskipTests install` 装反应堆，
   或用 Maven 解析出的 classpath 直接跑主类（e2e 驱动就是这么做的）。
5. **中文编码两处**：psycopg 连接按服务端默认（SQL_ASCII）解码出乱码；控制台按 GBK 打印报告会
   `UnicodeEncodeError`（而且**发生在所有检查通过之后**，读起来像失败）。连接用
   `client_encoding="UTF8"`（`runtime/db.py` 已处理），脚本重配 stdout 为 UTF-8。
6. **装了 `retrieval` extra 会让门禁的 `python-mypy` 步骤变红**：那条命令从**仓库根**跑、
   **不加载 `agent/pyproject.toml`**，所以只有 config override 的 ignore 无效。C07.1 的处置是删掉
   `sentence_transformers/jieba/rank_bm25` 的 override、改用 import 处具名 `# type: ignore[import-untyped]`。
   **不要再加回 override**——那会让具名 ignore 变成 `unused-ignore`，两个检查无法同时绿。
7. **`uv run --frozen` 同步的是不带 extras 的环境**，而 e2e 往同一个 venv 装了 extras。所以"套件全绿"要
   额外核实"核心不依赖可选 extra"。做法（已验证）：把 `jieba`/`rank_bm25`/`sentence_transformers`/`torch`
   在 `sys.modules` 里置 `None` 后重跑 → 829 passed。**注意别把 `numpy` 也屏蔽**：AgentScope 自己要 numpy，
   封了它会在五个无关模块上 collection 失败（我踩过，那是 shim 的错，不是发现）。
8. **不要为了通过而放松断言**：C07.1 里有三处是我的断言过强而不是代码错——它们钉住了**桩**的排序
   （"某个 rule 必须排第一"），而 `jieba` 一装排序就变。检索质量由 `reports/` 里的评测报告负责，
   plumbing 测试只应断言"有命中、引用可核、过滤有效"。
9. **评测里的"家族分离"检查第一版太宽松**（剥掉 `_near_miss` 后比较），把 dev/test 共有的 4 个家族报成没问题；
   改成精确比较后警告是真的（按版本切分并不产生家族分离），于是重写了查询集
   （dev=LOGISTICS、test=DAMAGE，家族零重叠）。**警告本身是发现，不要改检查去迎合数据。**
10. **写进账本/提交信息前先查 `reports/` 有没有反例**；**`git commit` 用 `-F <文件>`**
    （PowerShell 会吃掉中文引号、把 `/` 当路径）；**跑绿门之后先提交**（本仓库被静默回退过两次）。

## 5. 命令（照抄，环境已配好）

```powershell
Set-Location 'E:\Code\Agent+Backend'
$env:JAVA_HOME="C:\Users\hjn\.jdks\jdk-21.0.12.1+1"     # PATH 上的 java 是 17
$env:UV_CACHE_DIR='E:\Code\Agent+Backend\tmp\uv-cache'
$env:PYTHONIOENCODING='utf-8'

# Python 门
cd agent
uv run --project . --frozen pytest tests -q --basetemp='E:/Code/Agent+Backend/tmp/pytest-basetemp-c07'
uv run --project . --frozen ruff check src tests
uv run --project . --frozen mypy                        # 必须在 agent/ 下跑，strict，基线 9 个错误
# retrieval extra（只做 dense 时需要；装了它会让 all-offline 的 python-mypy 那步变红，见坑 6）
uv sync --project . --extra retrieval

# Java 门（改了 Java 才需要）
cd ..\java
.\mvnw.cmd -B test
.\mvnw.cmd -B spotless:check        # 改过 Java 后先 spotless:apply，再重读文件

# 项目门禁（~4 分钟，边界见 C07.1 账本：不跑 integration、不跑真实联调）
cd ..
pwsh -File scripts/verify.ps1 -Suite all-offline

# C07.1 端到端（需要 compose 的 MySQL；脚本自己起 Java 并解析 JDK21）
& 'agent\.venv\Scripts\python.exe' 'scripts\c071_policy_index_e2e.py' --embed
```

- **`--basetemp` 不是可选项**：本机 `%TEMP%` 对 pytest 不可写（WinError 5）。
- 未装 `retrieval` 时：`tokenize` 退化为**按标点切分**（与 jieba 不同），BM25 仍能跑；
  dense 会具名报 `EmbeddingUnavailableError`，**不退回 BM25**（规格要求）。报告里的数字来自装了 jieba 的那次。

## 6. 未清（不阻塞 C07.2，别丢）

- **run 侧 worker 仍不存在**（属 C09）：`AgentScopeRunner` 是可被调用的类，没人从 PG 队列取 run。
  所以 C07.2 的上下文能力同样**不会**被自动跑起来，验证要靠自己的测试与脚本。
- **模型仍全为 mock**（`modes={'mock'}`）；H1 自主性未验证（C08/C12）。
- **`policy_bundle.merchant_id` 可以为 NULL**（迁移对"没有任何 case 钉过的 bundle"无法归属）。语义写在 V17
  注释里：NULL = 没人说过这套政策属于谁；run 走的是**工单钉子**（`case_policy_manifest.merchant_id`，NOT NULL），
  Agent 侧 `served_bundle_of` 也拒绝缺商家的响应。**不要**用哨兵值或编造商家"修"它。
- **AS02.3 遗留**：Python 侧现在有了一条真的提出 scope 要求的路由吗？——C07.1 的索引摄取脚本用的是
  独立服务令牌（`policy:read`，实测无该 scope 返回 403），**API 路由仍未加 scope 要求**，那随 C08 落地。
- **本步未推送**（见 §0）。C08–C13 未开始；C07 之后按 `tasks/plan.md:26-27`：C05+C07→C08→C09→C10/C11→C12→C13。

## 7. 规矩（`AGENTS.md` 摘要，照旧）

**不擅自推送**（推送前问用户）、**不清库删卷**、迁移**只追加**、**不为通过而删断言**、
**不提交密钥**、**不开未经确认的收费评测**、真实记录**日期/文件/实际命令/结果/失败/未运行项**——
不得只勾任务。规范冲突要**指出并解决**，不任选方便版本。
