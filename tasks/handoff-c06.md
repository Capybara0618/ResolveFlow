# C06 交接（2026-09-23）

给新会话读的一份自足交接。**先读 `tasks/todo.md` 的 C06 段（`:923-931`）与 C05.4 各条**（那里有逐条
命令/结果/欠账），本文件只讲"现在站在哪、下一步做什么、哪些前提可以信任、哪些坑会误导判断"。

---

## 0. 交接时的仓库状态（已推送）

```
家：E:\Code\Agent+Backend   ← 就是本文件所在（E:\Code\ 里面，名字是 "Agent+Backend"）
2026-09-23：b814463（C05.2b-3b）→ C05.2c 之后的全部工作已推送到 origin/main → 本地与远端一致、工作树干净
精确数量以 git 为准：git rev-list --count b814463..HEAD   /   git log --oneline -1
```

**C05.2c 之后的全部工作已经在 `origin/main` 上**：真实链路的系统级 e2e、C05.3 的复审收口、C05.4 的债务清理
与三处真 bug 修复，以及两份交接文件（本文件与 `tasks/handoff-c052b3b.md`）。

**开工第一件事：`git log -1` 与 `git status`——状态以仓库为准，不要以本文件写的 sha 为准**（文档里的 sha
一定会比仓库旧）。

**这个仓库在同一台机器上被会话之外的进程静默回退/删除过两次**（2026-09-22、2026-09-23；第二次把 HEAD
退回 `7aad127`，未推送的提交与文件全部消失，C05.1b 的代码只能靠回放会话记录重建）。所以规矩是：
**验证过的提交要尽快推到远端**；但**不擅自推送**，推送前需要用户点头。

若开工后发现 HEAD 明显落后于 `origin/main`、或文件在批量消失：立刻停掉自己起的后台作业与进程 → 把残留状态
保全到仓库外 → 从远端恢复 → **先对齐 `core.autocrlf=false`/`core.eol=lf` 再签出**（否则冻结类测试会用
"内容不一致"的样子报告一个纯行尾差异）。完整处置见 `docs/implementation-handoff.md` 的"开始步骤"第 5 条与
`tasks/todo.md` 的 C03.3c-2 / C05.1b / C05.5 三条记录（最后一条是工作区归一化）。

### 开工自检：确认你在对的目录（**孪生路径问题已于 2026-09-23 彻底解决**）

```
家（唯一，本文件所在）：E:\Code\Agent+Backend        ← 在这里干活
```

**这台机器上与本项目相关的目录现在只有上面这一个**（2026-09-23 清理后）。以前有过两个只差一个字符的
`Agent+Backend`，都已删除：旧工作副本 `E:\Code+Agent+Backend`（停在 `d85b7b7`）与事故残骸
`E:\Code\Agent+Backend-PRE-B-MOVE-20260923`（停在 C05.1a）——**它们连同各自的 bundle 都没了**，
现在如果还看到这些路径，只可能出现在历史日志（`reports/c051c-transport/*.log`）与账本叙述里。

**为什么会冒出两个目录**（查清并记录在 `tasks/todo.md` 的 C05.5）：项目最初就在 `E:\Code\Agent+Backend`；
2026-09-22 第一次事故把原目录毁掉后，为了不丢东西从 GitHub 重新克隆，克隆落在了 `E:\Code+Agent+Backend`
（只多一个 `+`），此后所有工作都在里面做。于是同一台机器上有两个只差一个字符的仓库——**2026-09-23 有一个
新会话开错到旧的那个，白问了三个早就做完的问题**。当天把工作副本搬回最初的位置（完整历史、`origin`
远端、行尾配置一致），随后删掉两个旧目录。

**唯一留在项目外的相关文件**：`E:\ResolveFlow-archaeology-20260923.zip`（0.23 MB，清理时留下的工作树
快照与说明；删了也不影响项目）。**项目之外的还有两处不是文件但要知道**：数据库数据在 Docker 命名卷
（`mysql-data`/`postgres-data`）里，JDK 21 在 `C:\Users\hjn\.jdks\jdk-21.0.12.1+1`（PATH 上的 `java`
是 17，跑 Maven 必须显式给 `JAVA_HOME`）。

**开工第一条命令（离线可自证，不需要网络）**：

```powershell
Set-Location 'E:\Code\Agent+Backend'
(Get-Location).Path                 # 必须是 E:\Code\Agent+Backend（E:\Code\ 里面、没有加号）
git log --oneline -1                # 不早于 C05.5，且应与 origin/main 相同
Test-Path tasks\handoff-c06.md      # 必须是 True
```

任一条不符 → **停下并报告，不要在错的目录里改任何东西**。（`git ls-remote` 可能因沙箱无网络而失败，
那不是判断依据。）

## 1. 一句话位置

**C05 全部完成**（C05.1 消息与 outbox、C05.2 端到端、C05.3 复审收口、C05.4 债务清理），**已全部推送到 `origin/main`**，
工作树干净，`spotless:check` 干净，项目门禁 `all-offline` PASSED。下一件事：**C06 —— Agent 控制面、MCP 与
能力冒烟**。C06 依赖 **C02，早已满足**，**无阻塞**。

## 2. 已验证的事实（可以当前提，不必重新论证）

- **套件**：shared-kernel **59** / commerce **72** / case **187（4 skipped）**（另两个模块 5 与 2）；
  `java\mvnw.cmd -f java/pom.xml -B -ntp -q spotless:check` → exit 0；契约 pytest **548 passed**；
  项目门禁 `pwsh -File scripts/verify.ps1 -Suite all-offline` → **PASSED**
  （`reports/verify/20260923-181119-all-offline.txt`）。
- **真实链路仍然跑得通**，方式是照抄一条命令：`scripts/e2e_refund_chain.py`（真 MySQL + 真 RocketMQ +
  自己起 provider），三条链测试 `RESULT: PASSED (111.5s)`。它每轮自己 mint 三条订单行，**不需要手动造数据**；
  它还会启动自己的 provider（所以不要指望复用你手开的 8090）。
- **Case 的 Agent 回调面已经实现并有测试**：`POST /internal/v1/cases/{case_id}/agent-callbacks`
  （`callback_id` 主键即"最多应用一次"、逐字重投 DUPLICATE、旧 revision 或人工接管后 STALE、同 id 换内容 409、
  STARTED/QUESTION/FAILED 各自的状态与轨迹后果；PROPOSAL 会被 Java 按**钉住的政策版本**核对引用并**重算金额**）。
  → **C06 的 Agent 可以直接用这个面**，不用先造协议。
- C03.3c-2（新输入使活授权失效）与授权的**消费边界**都已实现（C05.2a）；工单状态机、轨迹、inbox/outbox、
  结果投影（含按 `aggregate_version` 定序与并发安全）都有测试。

## 3. C06 的起点：Python 侧现在到底是什么

| 包 | 现状（已核对文件行数） |
| --- | --- |
| `agent/src/resolveflow/api/app.py` | **166 行，就是 provider stub 的 HTTP 面**：`/health`、`/provider/v1/refunds`、`/provider/v1/refunds/{key}`、`/provider/v1/_lab/faults`（故障注入） |
| `agent/src/resolveflow/provider_stub/__init__.py` | 363 行，C04.1 的持久 SQLite 退款 stub（真实现，`test_provider_stub*.py` 14+ 条） |
| `tools/` `runtime/` `harness/` `callbacks/` `policies/` | **只有 1 行的 `__init__.py`** —— 空包。**C06 从这里开始** |
| `contracts/` | 实打实：`canonical.py`/`core_models.py`/`core_profile.py`/`fixtures.py`/`corpus.py` 等，Python 侧契约与字节级一致测试 |

**所以今天 8090 上的"agent"不是 Agent Harness，是 provider stub。** 别把它误当成已有 harness；`tools/`、
`runtime/` 是空的，MCP 工具一个都还不存在。

## 4. C06 三片（原文取自 `tasks/todo.md:923-931`）

1. **C06.1**：PG 持久 run 入口、Case HTTP outbox 与绑定，尚无模型也能可靠排队。
2. **C06.2**：Commerce 模拟物流只读适配、**5 个 stdio MCP 工具**、scope 与错误 Observation。
3. **C06.3**：mock ModelClient 和经预算确认的 live 小样本结构化调用；提前核验工具能力，不预跑固定业务链。

- **验收**：202 在落库后、真实 MCP list/call、模型无法改 line/身份；mock/live 记录分开。
- **验证**：PG 重复提交、MCP 协议/越权、工具失败；live 不可用要写成明确阻塞项，**不伪造**。
- **要读的规范**：`docs/agent-harness.md`、`docs/agent-spec.md`（C06）；`docs/context-engineering.md`（C07 才用）；
  `docs/trajectory-replay.md`（C10）；身份/权限边界见 `docs/core-contracts.md` 与 AGENTS.md 的不变量。
- **环境**：`infra/compose.yaml` 里有 `postgres`（C06.1 用）与 `redis`；`agent/.venv` 已存在；
  `agent/pyproject.toml` 已冻结依赖（用 `--frozen` 跑测试）。
- **"绑定"指 run→case 绑定**：这是账本里明确记在 C06 名下的已知缺口（`:318`/`:330` 的"Case 无 run→case 绑定（C06）"）。

## 5. 本会话的改动会直接影响 C06（新坑，务必先看）

1. **服务令牌现在必须带 `iss`**（C05.4c）。`JwtCodec.verifiedClaims` 要求 `iss == resolveflow-demo-identity`，
   用户路径与服务路径**共用**这道闸（契约 `openapi-case.yaml:607` 早就写了 issuer 与 audience 都校验，
   此前只有 audience 那一半）。**任何手写或 Python 侧新造的 JWT 若不带 `iss`，现在会 401。**
2. **证据引用必须四件齐全**（C05.4d）：`observation_id`/`source_ref`/`source_version`/`content_hash`，
   且 `content_hash` 必须是 64 位小写 hex；缺一个就是 **422**。C06/C08 的 harness 造 proposal 时**必须**给全，
   否则方案再合理也进不来。（`source_ref` 必须是 `kind:rest` 形式的受控引用，URL 仍被拒。）
3. **结果金额必须等于本工单授权金额**（C05.3d）：不等 → `AMOUNT_MISMATCH` 拒签、不落事实行。
4. **坏游标是 400 不是 503**（C05.4a）：`GET /api/v1/orders` 现在声明并返回 `400 INVALID_ARGUMENT`
   （游标不透明、Commerce 拥有，本服务只透传）。
5. **仍然没做**：证据引用**不解析、不做权威核对**（需要每种 `source_ref` 都有权威读取；今天只有订单行上下文，
   **C06.2 的运单读取正是最缺的那一种**）。这条不要写成"已核对"。

## 6. 命令（照抄，环境已配好）

```powershell
Set-Location "E:\Code+Agent+Backend"          # 注意：目录名里是加号，别写成 E:\Code\Agent+Backend
$env:JAVA_HOME="C:\Users\hjn\.jdks\jdk-21.0.12.1+1"

java\mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am test      # case 全量（187 条，4 skipped）
java\mvnw.cmd -f java/pom.xml -B -ntp -q spotless:check              # 必须 exit 0
& 'agent\.venv\Scripts\python.exe' -m pytest agent/tests/unit -q -p no:cacheprovider
pwsh -File scripts/verify.ps1 -Suite all-offline                     # 项目门禁（~3 分钟）
& 'agent\.venv\Scripts\python.exe' 'scripts\e2e_refund_chain.py'     # 真实链路（~110s，自起 provider）
```

- 单测：`"...-Dtest=类名#方法名" "-Dsurefire.failIfNoSpecifiedTests=false"`（**引号必需**）。
- `-am` 必需。**日志一律重定向到文件再读**——管道退出码不可信；红跑与绿跑用**不同文件名**（踩过坑）。

## 7. 会误导判断的环境事实

- **`smoke-agent-service` 每轮 0.1s PASS 不是证据**：8090 长期被会话之外的进程占用（PID 会变）。
  这一项不能当"agent 服务可启动"，报告里要注明。
- `tmp/` 被 gitignore → 证据一律放 `reports/`。`git commit -m` 里避免中文引号（PowerShell 会当引号解析）。
- `spotless:apply` 会重排代码：刚跑过 spotless 后再编辑**必须先重读文件**，否则报 "file changed since it was read"。
- 可能仍有并行客户端在改同一仓库（AGENTS.md 开头的警告）→ 发现同文件并行编辑先确认交接，不覆盖别人的改动。
- 推送偶发 `schannel: failed to receive handshake, SSL/TLS connection failed`，**重试即可成功**。
- **账本教训（C05.4）**：**摘要行不是状态**——状态要看该工作包内**最后一条完成记录**。本会话因为读了
  `tasks/todo.md:193` 那句过时摘要，把早已完成的 C03.3c-2 当成"唯一真缺口"，差点重做一遍。
  开工前对**代码**核一遍你要改的东西，不要只信账本摘要。

## 8. 提交轨迹（`b814463` 之后的实现提交，**已全部推送**）

```
3a498cf  新增 C05.2b-3b 交接文件
50dae7e  C05.2c-1  case 侧结果监听器接线
68484d2  C05.2c-2  Commerce 退款推进入口（dispatch/reconcile 两个开关）
0bc6590  C05.2c-2b 派发/对账一趟不再被单行拖死
70ea5cb  C05.2c-3  真实链路系统级 e2e 跑通；修 commerce 从未 @EnableScheduling
0e6a91c  C05.2c-4  CF3 定点（响应丢失→UNKNOWN→对账收敛→关单）
cf692c8  C05.2c 收尾：项目门禁 PASSED 归档
6f30f9a  C05.3a 复审（发现 domain 拒绝只剩一行 WARN、Case 静默 EXECUTING）
601a8d1  C05.3b Commerce 半程（拒绝回传 Case，REQUIRES_NEW）
73c698c  C05.3b e2e 半程（拒绝链真 broker 跑通）
64ce614  C05.3b 归档
84732e2  C05.3c amount_minor 前置校验 + 未知 state 拒绝路径测试
64d7abb  C05.3 收口验证：门禁 PASSED 归档
ea16e69  C05.3d 拒绝分类类型化 Reason + Case 侧金额=授权金额
7974c43  C05.3d 验证归档
f47843e  C05.4 债务核对 + 坏游标 400/503 修复
b36f1c1  C05.4b 债务②③核对（只核不改）
9127f9b  C05.4c JWT iss 校验（契约违规）
fd936f3  C05.4d 证据引用四件齐（契约 required）
0ab7ce7  C05.4e 债务⑤⑥核对（乱序/多实例的实际情况）
88f5ab2  C05.4 债务清理收尾验证：门禁 PASSED 归档
```

清单到此为止；其后是 **C06 交接文档自身**的几次提交（新增 `tasks/handoff-c06.md`、同步推送后的真实状态、
去掉写死的 sha 与数字、修掉本文件里剩下的旧数字）。**最新的提交数与 sha 一律以 `git log` 为准。**

## 9. 未清（不阻塞 C06，别丢）

- **证据引用解析**：需要每种 `source_ref` 的权威读取；**C06.2 的运单只读适配是触发点**。写在
  `ProposalReCheck.requireEvidenceRefs` 的 javadoc 里（已订正过时的 "until C04"）。
- **真实 broker 重排 + 两个消费者进程争抢同一队列**：乱序与并发的**逻辑**已实现且已被测试
  （`CaseResultConsumerApiTest` 19 条，含"迟到的低版本不动工单、也不被静默丢弃"与并发那条）；
  没被证明的是运输层与两进程。**收口配方在 `tasks/todo.md` 的 C05.4e 条**（起两个 case-service 实例，
  再用小脚本把一条更旧的事实以**新 event_id**在关单后重发到真实 topic）。
- 契约里的 maxLength（`observation_id`/`source_version` 64、`source_ref` 200）没有在 Java 那一层复验。
- 命令只带一个 `policy_version` 是**契约形状**，但"这次执行由哪一套政策支持"在命令上是**有损**的——
  要改必须同时动契约与两个服务。
- C06 之后的大模块：**C07–C13**（见 `tasks/plan.md` 的阶段表与 `tasks/todo.md` 各段）。

AGENTS.md 的规矩照旧：**不擅自推送**、不清库删卷、迁移只追加、不为通过而删断言、真实记录日期/文件/命令/
结果/失败与**未运行项**。
