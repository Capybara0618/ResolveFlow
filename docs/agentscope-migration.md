# AgentScope 迁移规格与 DSH 交接 · v1.3

2026-09-26状态校正：AgentScope 2.0.8已完成生产循环接入，非Agent框架锁不变。本文保留框架约束与迁移历史，不作为当前开工清单；从[当前交接](../tasks/handoff-current.md)接续C08。生产恢复/strict仍归C09/C10，AS01的Python网络入口探针不等于OS级禁网；更正证据见[审查修复报告](../reports/c08-review-fixes.md)。

## 1. 目标与不做项

目标：让 AgentScope 真正承担模型驱动的推理—行动主循环，以现有领域 Harness 控制权限、预算、上下文和终止；保留 PostgreSQL 持久恢复、真实 MCP、Java 权威执行与 strict 回放。框架名称不是完成证据。

- 不改 Gateway/Case/Commerce 的拆分、退款/审批/UNKNOWN/Outbox/inbox 语义、对外 API、核心动作 ABI 与预算上限。
- 保留 Python 3.12、FastAPI、PG/pgvector、官方 MCP stdio 和已有模型供应商边界；DSH 使用 DeepSeek 写代码不等于应用必须使用同一模型。
- 只引入 SDK 必需能力，不部署 AgentScope Agent Service/Studio，不加多 Agent、Agent Team、A2A、Skills 市场、长期记忆、通用插件平台或第二种消息中间件。
- 不为换框架增加 Temporal/Celery/Redis 队列或自研通用图引擎。兼容性若只能靠大规模重写/私有 API monkey patch，先报告阻塞。
- 不开放框架示例里的 shell、文件写入、浏览器、任意 URL 工具。框架内置自动压缩、自动总结和额外模型调用默认不启用；有无法关闭的路径须统一拦截计费，否则关卡失败。

## 2. 迁移前开工事实与接管（2026-09-25历史）

本轮核对：C00–C05已有完成记录；C06已有PG run入口、回调outbox/投递、真实MCP、run级凭据、`HarnessRunner`和`MockModelClient`。LangGraph已锁定且T00有兼容性试验，但正式Harness仍为自写循环；没有据此证明真实模型自主调查、完整run执行worker或持久恢复完成。

2026-09-25文档修订前，工作区有8个未提交代码/测试/脚本改动，涉及 `tools/catalog.py`、工具测试、Case异常处理/材料接口及 `scripts/e2e_harness_java_tools.py`。这是接管线索，不是固定清单或完成证明。**每次先检查实时git状态并确认旧DSH会话是否仍在写；同文件未完成交接不得覆盖。** C06.4⑤可先收口现有真实Java工具联调并留基线，但不继续扩展旧自写循环/接入LangGraph。

`docs/c064-handoff.md`等旧交接只作历史证据，里面的HEAD、测试数量、“下一步”和“空包”描述不得覆盖当前代码。已有Java逐路由scope强制、调查worker组合等缺口须逐项核对；不能借框架迁移把欠账写成已完成。

## 3. 目标责任边界

| 层 | 目标职责 | 不允许承担 |
| --- | --- | --- |
| AgentScope SDK | 唯一推理—行动循环、模型/工具协议与结构化结果能力 | 自行审批退款、另起不受控的模型/工具调用 |
| 领域Harness | 动作校验、ContextBuilder、预算/终止、引用验证；通过适配器/中间件接入 | 第二套完整Agent循环、通用工作流引擎 |
| RunStore + 薄恢复适配 | PG任务领取、稳定调用账、运行快照、fence、终局与callback_outbox | 用聊天历史/JSON文件冒充事务恢复 |
| MCP适配 | 原5个只读工具、run凭据、scope、大小/分页限制 | 绕过官方stdio路径直接import业务函数 |
| Java | 工单/授权/金额权威、审批、退款与对账 | 信任模型confidence作为授权 |

现有 `harness/actions.py`、`budget.py`、`model.py`、`mcp_client.py` 的有效约束与测试优先复用。`runner.py`改成装配/适配入口，不再保留生产自写`while`驱动完整决策；AS02切换完成后只有一套生产循环。旧行为测试可以换夹具/适配入口，但不能删断言或把新断言只跑在旧循环上。

### 3.1 框架工具与领域动作映射

AS01.1必须先写可执行映射测试，不能边实现边改变动作协议：

- 框架原生tool call或结构化输出先正规化为既有 `READ_TOOL/SEARCH_POLICY/READ_OBSERVATION/ASK_CUSTOMER/PROPOSE/ESCALATE`，再过统一守卫。MCP仍只有5个外部只读工具；检索/读回/终止动作可用本地适配，不新增MCP服务器。
- 普通自然语言回复不是有效方案；`PROPOSE`须通过既有Schema/引用校验。`ASK_CUSTOMER/PROPOSE/ESCALATE`是领域终止，不允许SDK在终止后自动补一次总结调用或继续执行同批后续工具。
- READ_TOOL保留每次1–3个独立只读调用；混有非法动作、写工具、身份/URL字段或终止与读取混排时整批拒绝，不能部分执行后才发现越权。并发执行前先校验整个批次并预占预算；开始时可顺序调度同批工具，不能删除批次语义来适配SDK。
- 身份、run/revision、credentials由运行时注入，不能从模型参数取。绑定仍由Java资源接口复核。
- `ModelClient`可以增加SDK适配，但mock/live记录和测试脚本用途不变；不得外层先调模型决定动作，再让SDK调模型重新决定一次。

### 3.2 预算、上下文与扩展点

AS01.1产出“实际API → 拦截点 → 测试”的能力表。具体类/方法从锁定版本源码验证，不照抄旧版ReActAgent或开发版教程。

- 每次模型请求（含网络重试、输出修复、终止总结等）必须先检查run/fence/deadline并计attempt；只允许一层重试。
- 输入计数覆盖最终system、messages、工具Schema及provider包装，不能只算新ContextPacket；输出按请求上限预占，不填0。估算与真实usage分开，UNKNOWN保守记账，预算不足不得发起网络调用。
- SDK内置“达到预算后提示收尾”不能替代项目的调用前硬拦截和持久账本。禁止在预算耗尽后为生成好看的结语再调用模型。
- SDK历史、自动上下文注入不得绕过ContextBuilder长度/事实保护；关键事实、来源/版本/冲突不可生成式改写。保持 [上下文规格](context-engineering.md)，不因此增加LLM摘要功能。
- 记录脱敏后的最终provider请求、显式响应/工具参数、usage与版本；不展示/落库隐式思维链，不记录凭证。若provider有续接必需的opaque字段，先核实是否能不保存敏感推理且安全续接，未验证前不启用该模式。
- 权限硬边界同时在ToolExecutor和Java资源接口；中间件仅是接入位置，不是跨调用路径安全性的证明。

## 4. 持久恢复：验收不变，实现重验证

不再要求LangGraph专用表。`checkpoint`在当前规范中指**可恢复的领域运行快照**，不是某一SDK的类名；SDK状态只是其中一部分。拟复用现有PG RunStore，通过薄适配层保存SDK续接必要状态和领域进度，最终形状由AS01.2验证后记录，生产实现归C09。

最低持久内容：run/case/revision、manifest/state版本、逻辑step与下一阶段、待执行动作及稳定call_id、已落库响应/Observation引用、已应用结果游标、上下文引用、预算预占/usage、deadline、租约/fence。框架聊天历史不是唯一事实源；SDK session ID不是授权主体。

事务与重入要求：

1. 领取run并持久增加fence；同run排他执行，网络期间不持有长业务事务。session级advisory lock的连接寿命与连接池释放必须明确。
2. 外部调用前以稳定call_id保存请求和预算预占；外部调用在事务外。逻辑调用与重试attempt分开，响应不明不得冒充成功或重新生成整个步骤ID。
3. 返回后在同一PG事务锁run行并核验当前fence/有效状态，再保存响应与usage。旧worker不能更新有效结果、快照或callback；不能“先查fence再另开连接写SDK状态”。
4. 结果已保存但快照未推进：重建该步骤，按原call_id复用记录；工具调用序号/结果应用须幂等，不再次结算预算。原外部响应未保存：允许按重试上限再次请求，保留UNKNOWN成本，不能承诺零重复计费。
5. 终局方案、run状态和callback_outbox在同一受fence保护事务提交；已有回调投递循环复用。补证new revision/new run与同run故障恢复严格分开。
6. 同run保持原manifest、预算和deadline。过期则明确终止而非续期。取消后/失去租约的迟到结果不得再产生有效动作。

如果SDK仅支持reply结束时保存，必须用稳定调用账+已记录模型/工具结果重建未完成reply，并证明可以绕开网络且不重复记账；不能退化成“从头重新调模型”。若公开扩展点不足以满足上述要求，AS01失败并提交最小复现，不私自回LangGraph或降低H4。

## 5. manifest、协议与回放兼容

- 暂不修改 `contracts/harness-manifest.schema.json` 的v1 wire字段。保留 `graph_version` 作为历史字段名，在AgentScope目标实现中表示运行编排版本，值约定 `agentscope@<精确版本>+resolveflow@<适配版本>`；不得因换框架删除required字段。`state_schema_version`跟踪新快照格式，`code_revision`关联可追溯代码/锁文件。
- SDK版本、依赖锁hash、适配版本、动作映射、Prompt和工具Schema必须能从manifest及关联记录追溯。若确需新增wire字段，另立契约子步，同步Schema/类型/fixture/消费者，不能悄悄追加被`additionalProperties:false`禁止的成员。
- 新旧manifest不可在同run静默替换；历史LangGraph试验记录保留，不能改成AgentScope成功报告。无新旧状态自动转换要求；不支持的历史run明确拒绝并走既定人工路径。
- strict使用同一AgentScope+Harness执行逻辑，但模型、工具、Clock、存储、callback全部换成记录/本地隔离适配；不是另写播放器直接输出期望答案。禁用telemetry/自动下载/自动重试回源，并由测试在进程/容器层阻止网络。缺记录明确失败。
- AS01.3只验证一条完整顺序轨迹及缺记录反例可行；5个golden packs和全部H5仍归C10。原合成样本规模、CF1–CF6及H1–H5不扩大、不删减。

## 6. 版本与官方依据

2026-09-25选择的 [AgentScope v2.0.8](https://github.com/agentscope-ai/agentscope/releases/tag/v2.0.8)现已锁入spike和agent；MCP沿用2.2.0并走项目自带官方stdio客户端，AgentScope只接普通工具适配。保留已批准的依赖override，不重新选型或自动升级；实际API以锁定源码为准。

- [官方仓库](https://github.com/agentscope-ai/agentscope)：SDK与Agent Service是不同层，本项目只选前者。
- [2.x Agent说明](https://docs.agentscope.io/en/versions/2.0.9dev/building-blocks/agent/overview)、[中间件说明](https://docs.agentscope.io/en/versions/2.0.9dev/building-blocks/middleware)：只作能力线索，URL明确是开发版；实际API以选定release源码和最小测试为准。
- 不混用旧站 `doc.agentscope.io` 的1.x示例与新站 `docs.agentscope.io` 的2.x实现。

先在独立 `spikes/agentscope/` 验证与当前Python/FastAPI/Pydantic/psycopg/MCP精确版本的依赖交集，不污染现有agent锁。若MCP等不兼容，先尝试不改变stdio线协议的隔离适配；需要改既有共享主版本须报告冲突，不能顺手全栈升级。不得复制凭据或调用收费模型来验证安装。

## 7. 迁移历史顺序、验收与可复跑命令

顺序：AS00接管/基线 → AS01.1依赖与循环拦截 → AS01.2真实PG恢复探针 → AS01.3隔离回放探针 → **技术门禁审阅** → AS02.1依赖/适配 → AS02.2生产循环替换 → AS02.3真实MCP/Java回归 → C07 → C08 → C09 → C10及其余原计划。

AS任务替代C06剩余框架接入及C08–C10的框架专项预研，**不是新增一套产品路线**。AS01探针不能把C09/C10勾完成。每项的文件/验收/验证在 [账本](../tasks/todo.md)；超过3–5个核心文件再拆，记实际文件和执行结果。

AS01全部通过后，提交兼容报告（建议 `reports/agentscope-migration/compatibility.md`）给用户审阅，再进入AS02。该检查点只确认技术风险，不重复询问已批准的场景和迁移方向。报告至少含：版本/来源、API拦截表、动作映射、失败窗口、快照形状、真实测试命令及通过/失败/跳过/未运行。任何关键失败不得用“框架支持状态保存”掩盖。

### 已存在命令（仓库根执行，除明确注明）

```powershell
git status --short
git log -1 --oneline
uv run --project agent --frozen pytest agent/tests/unit/test_harness_loop.py agent/tests/integration/test_harness_mcp.py -q
uv run --project agent --frozen pytest agent/tests -q
uv run --project agent --frozen ruff check agent/src agent/tests
pwsh -File scripts/verify.ps1 -Suite contracts
pwsh -File scripts/verify.ps1 -Suite all-offline
```

类型检查必须在 `agent/` 下执行 `uv run --project . --frozen mypy`。Java验证在 `java/` 下执行 `.\mvnw.cmd -B test` 与 `.\mvnw.cmd -B spotless:check`。遵循 [工程命令](engineering.md)；命令存在不代表本轮运行。完整离线集仍需Docker/数据库，未启动不能报绿。pytest临时目录若受权限限制，使用新建的任务专用临时目录，不把含用户文件的目录传给会清理目录的`--basetemp`。

### 已有隔离spike命令（执行不代表生产C09/C10通过）

```powershell
uv sync --project spikes/agentscope --frozen
uv run --project spikes/agentscope --frozen pytest spikes/agentscope/tests -q
```

上述项目和锁已存在，不重新创建/解析。测试优先在spike目录运行`uv run --frozen pytest tests -q`，与agent的同名tests包分开。报告记录真实命令和临时PG schema；缺Docker/PG的关卡标未运行，无API预算不做live。既有mypy错误单列基线，新增错误不得豁免，也不写全绿。

## 8. 历史迁移首轮提示词（已失效，不再复制执行）

当前提示词统一见[tasks/handoff-current.md](../tasks/handoff-current.md)。下方仅保留迁移决策追溯。

```text
请在 E:/Code/Agent+Backend 接续 ResolveFlow。用户已批准仅将 Agent 框架改为 AgentScope 2.x Python SDK，保留 v1.2 的业务范围、Java/MCP 契约、领域 Harness 和全部核心验收；本轮文档 v1.3 已更新，但代码尚未迁移。

先读 AGENTS.md、README.md、docs/core-scope.md、docs/agentscope-migration.md、docs/implementation-handoff.md、docs/dsh-migration-handoff.md、tasks/plan.md，再读 tasks/todo.md 顶部及 AS 区块；C06 历史只按需查。检查 git status、HEAD 和现有未提交改动，确认旧会话没有同时写文件。不要从 C00 重做，不继续旧 T03–T39，也不要继续接入 LangGraph。

本轮只执行 AS00 与 AS01.1。先接管并记录现有 C06.4⑤ 改动和测试基线，再在隔离 spike 验证已发布 AgentScope 2.x 与现有依赖、动作 ABI、真实主循环、模型/工具硬拦截的兼容性。不要直接改生产依赖锁或重写 runner。先写关键失败测试，每个子步通常3–5个核心文件；复用已有代码，保留旧断言。模型先用mock，不能宣称live自主性。

其后按账本做 AS01.2/AS01.3 的真实PG恢复及禁网络回放探针，提交证据供我确认后再进入 AS02。恢复验证不能用聊天历史保存代替；必须覆盖稳定call_id、结果复用、UNKNOWN、旧fence拒绝、预算/deadline不重置。若框架有无法拦截的调用或恢复接口不足，报告最小复现，不降低要求或擅自换栈。

不要增加多Agent、平台配套或新中间件，不覆盖现有工作，不删除测试/清库/删卷，不使用收费API或公网部署，不擅自推送。每步更新 tasks/todo.md 的实际文件、命令、报告、失败/未运行和下一步。结束时告诉我：本轮完成了什么、哪些未验证、下一子步是什么。
```
