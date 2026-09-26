# ResolveFlow 当前执行交接

更新：2026-09-26。唯一当前执行入口；进度唯一维护在[todo顶部](todo.md)。本文件替代handoff-c08和handoff-c08-2的开工指令，旧文件只按具体问题查历史，不要求逐份追读。

## 1. 接管与事实

先读[todo顶部](todo.md)的当前快照和接续顺序，再按当前任务读取本文对应小节。当前状态不在本文重复维护；下面各阶段的“未做/下一步”只描述当时断点，后续实现可能已经覆盖，不能跨过账本直接执行。

目标是用一个自研项目展示Java后端与Agent工程能力，不增加微服务、中间件或平台。每个核心交付同时留下可演示行为、关键失败测试和证据入口；简历候选方向见[证据映射](../docs/resume-evidence.md)，不是预设成果或必须写满的条数。

先检查实时git状态、相关diff和文件内容，保留其他客户端修改。确认同文件仍在并行写入时先协调交接；不能用重写文件或reset“整理”进度。常规脏工作树不是停止理由。

### 历史接管快照（2026-09-26早期，保留追溯，不作为当前起点）

- 范围仍是个人简历项目：Gateway、Case、Commerce三个Java进程+Python Agent；不增平台、多Agent或中间件。
- AgentScope 2.0.8为唯一生产循环；MCP 2.2.0沿用项目自带官方stdio客户端，不重新迁移框架或换锁。
- C00–C06有完成记录，C07检索/上下文组件已实现；C08仅部分接入。组件完成≠默认启用≠真实模型验证≠端到端交付。
- 本轮已修：输出预占/结算与超额停止；ContextPacket与ModelClient输入一致；旧路径最终请求先冻结再核算；中文计数不再除以3；退款预留事实字段对齐；回放Python入口拦截。命令与边界见[修复报告](../reports/c08-review-fixes.md)。不要重新实现这些修复。
- 2026-09-26 C08.1a 已完成（小步：默认收口 → 读取方式迁移 → P1已确认动作），见[报告](../reports/c08-1a-context-path.md)：
  `AgentScopeRunner.use_context_builder` **默认为 `True`**，即正式路径是 ContextBuilder(P0–P4)；
  C06.4证据包降为**显式兼容路径**（旧交换不再要求调用方传False）。测试读取改为模型**实际收到的messages**，
  不再用mock隐藏结构化`context`充数。新增P1「已确认动作」（有界窗口4，排除模型自由文本）。
- 2026-09-26 C08.1b-1「冻结HarnessManifest」已完成，见[报告](../reports/c08-1b-frozen-manifest.md)：
  新增`harness/manifest.py`，按已冻结Schema构造完整manifest，`manifest_id`=排除自身后的canonical SHA-256；
  runner记忆化`manifest()`，报文不再用`bundle@hash[:16]`冒充。`index_generation`在Python侧解析（READY生成优先，
  否则pin的确定性uuid5且注明非行id），**未改派发协议**故无需消费者同步。`verifier_version="unimplemented"`（C08.1c）。
- 2026-09-26 C08.1b-2「live ModelClient（离线请求捕获）」已完成，见[报告](../reports/c08-1b-live-client.md)：
  新增`harness/live_model.py`——ceiling必填且进实际请求体、**恰好一次发送无内部重试**（失败尝试也入账）、
  缺usage标ESTIMATED且非零、记录无凭据只存body+canonical hash；13例离线单测+1例集成（live客户端跑完整循环，
  ceiling抵达provider body）。**未联网**；尚未有从配置构造live客户端的工厂（属C08.2 worker）。
- 仍待交付：候选引用验证、调查worker。模型默认仍mock；H1未验证。
- **已知缺口（故意未擅自补）**：冻结prompt/ABI未规定答案必须是JSON，live客户端只能宽松提取否则拒绝；
  修法在prompt/ABI层（会改`prompt_hash`），应与候选引用验证一并处理。
- 两处边界经重新划定，见报告§5：正式报文**不含**`content_hash`（只在run记录里）；预算位置在ModelClient的
  结构化`context`而**不在**provider request（P0–P4无预算层，与旧证据包不同）。

先看实时`git status --short`、`git log -3 --oneline`和diff。保留本轮未提交修改与已有reports产物；普通脏工作树不是阻塞。发现同文件并行编辑、批量消失或异常回退才停下确认，不能reset/覆盖。不要要求HEAD等于旧SHA。

`git rev-list --left-right --count origin/main...HEAD`左边是远端领先，右边是本地领先；只反映本地远端跟踪引用，不保证已联网刷新。2026-09-26用户已授权每个验证通过的小步提交并正常推送；按[工程约定第8节](../docs/engineering.md#8-每小步提交并推送2026-09-26用户授权)核实远程与全部待推送提交，不再等待逐次授权。

## 2. 执行规则与历史实施记录

当前任务由账本顶部定位。下面C08.1a至C08.2-7为按阶段追加的历史记录，保留当时的失败、测试和取舍；不能把较早的“仍缺/下一步”覆盖后续源码。每次收口一个子步，更新账本顶部，并在对应C任务下追加实际记录，不再在本文追加第二份当前进度。

### C08.1a 正式上下文路径收口——历史已完成记录

结果与证据见[报告](../reports/c08-1a-context-path.md)；`pytest tests` **930 passed, 9 skipped**、ruff 通过、
strict mypy **9=基线**。要点：正式默认已是ContextBuilder；测试读取改读真实messages；P1补「已确认动作」（有界）。
**翻默认不再有回归**（旧交接的"58个红"在当前工作树不复现，实测0失败）。

1. ~~先列出语义测试对旧packet的依赖，区分脚本读取的`context`与模型实际收到的`messages/sent_context`。~~ 已完成。
2. ~~补失败测试，再将正式runner默认切换到ContextBuilder；同步测试读取方式~~ 已完成，未删任何预算/权限/防循环/批次/错误Observation断言。
3. ~~确保SDK工具结果/错误/分页cursor/READ_OBSERVATION窗口及已确认动作，通过有界上下文传给模型~~ 已完成并有用例；
   P0动作描述仍是简化目录，补真实动作参数Schema时一起核算（未做）。
4. 每轮的实收输入、角色、输出上限、输入计数与hash一致；SDK消息后续变化不能改写历史请求。（修复集已覆盖，本轮未改）
5. ~~单步3–5核心文件，跑受影响unit/integration、全部agent tests、Ruff、strict mypy并记录。~~ 已完成。

### C08.1b/c 模型与方案

- ~~落实冻结的HarnessManifest~~ **已完成 2026-09-26（C08.1b-1）**：完整manifest按冻结Schema构造、`manifest_id`=排除自身后的canonical SHA-256、
  runner记忆化、`index_generation`在Python侧解析未改派发协议、`verifier_version`如实记`unimplemented`。证据见[报告](../reports/c08-1b-frozen-manifest.md)。
- live ModelClient明确供应商与模型参数，实际请求强制`max_output_tokens`，无隐藏重试；usage未知标ESTIMATED/UNKNOWN，不能以默认0退款预占。保存脱敏后的实际HTTP请求/hash、usage与mock/live模式。无API预算先做离线请求捕获测试。
  → **已完成 2026-09-26（C08.1b-2）**：`harness/live_model.py`+13例离线单测+1例集成；未联网；尚无配置工厂（C08.2 worker）。见[报告](../reports/c08-1b-live-client.md)。
- 候选引用校验：可见来源、版本/hash、缺证、跨scope与政策固定版本；Python校验不等于Java授权。
  → **已完成 2026-09-26（C08.1c-1）**：`harness/verifier.py`（`ProposalVerifier`）+ABI补引用成员+P0告知+runner内拒绝路径。
  引用须逐成员匹配run自己的observation（`SEARCH_POLICY`命中从该observation的`result`读取，不另立台账）；`verifier_version`由`unimplemented`变为`python-citations-v1`（仅Python侧引用校验，不含Java独立复核/批准）。
  **仍缺（下一步C08.1c-2）**：模型引用/schema错误只可修复一次（`docs/agent-spec.md:52`）尚未实现，当前是不可修复的硬停止；以及一个"真实工具observation+真实政策命中"双来源fixture下的端到端通过型退款用例。
  见[报告](../reports/c08-1c-proposal-verifier.md)。
  → **已完成 2026-09-26（C08.1c-2a，修复一次的前置）**：发现 `gate.notices` 只进 `RunResult.notices`、**从未送达模型**
  （`docs/agent-spec.md:44`「前两次回传」实际未满足；`sdk_adapter.py:118` 的 `self.notices` 无人使用）。已把通知渲染进
  **P1**（强制层，不可裁剪；`ContextBuilder.build(notices=)` + `_packet_of["notices"]`），正式与 legacy 两条路径各有测试
  断言通知出现在**发出的 messages** 里。见[报告](../reports/c08-1c-2a-feedback-channel.md)。
  **C08.1c-2机制已查证（未实现）**：AgentScope 对权限拒绝(`_agent.py:2582-2590`，回传 `decision.message`)与未知工具
  (`:2509-2517`)**都继续循环**，故"第一次拒绝不终止、让拒绝原因作为工具结果回到模型、第二次才停"可达；
  终止性PROPOSE的引用拒绝需另发一个会被拒的工具调用才换得到修复轮（**未验证**）。`agent-spec.md:52` **仍未满足**，不宣称。
  → **已完成 2026-09-26（C08.1c-2，`docs/agent-spec.md:52` 可修复一次）**：`MAX_REPAIRS=1`+gate `_refuse(repairable=)`+
  权限钩子修复分支+`_repair_probe()`。非终止拒绝原样交还SDK（由其执行→钩子拒绝→原因回喂）；终止性PROPOSE的引用拒绝
  换成一次白名单工具探测调用（`required: []`可过SDK校验，`accepted`未设置故不可能ALLOW，**不会执行**）。
  无进展停止为 `repairable=False`。实测 `pytest tests` → **976 passed（+4）, 9 skipped**；ruff通过；mypy **9=基线**。
  见[报告](../reports/c08-1c-2-repair-once.md)。
  **仍缺**：①端到端**通过型**退款用例（需"真实工具observation+真实政策命中"双来源fixture）；②`verify_proposal()`
  接入run路径（属C08.2组装callback）。修复次数按**run全局一次**计（对"可修复一次"的保守读法，已记录）。
  **本步全部为mock驱动**：只证明harness对不合法输出的行为，**不等于**真实模型会自我修正，H1仍不勾。
- 无API预算先完成离线适配/请求捕获测试；付费live小样本须用户确认。H1的至少6组配对案例用真实模型证据验收，mock不勾H1。

### C08.2 单执行者业务闭环

组合PG待办run领取、现有模型/工具、问题/方案/失败callback_outbox。打通派发→调查→回调→Java复核/必要审批→模拟退款，以及补证新run/旧结果STALE。此处完成worker；C09是恢复与竞争保护，不能继续把“根本没人消费run”推迟到C09。

- **已完成 2026-09-26（C08.2-1「单执行者worker：待办run真的被消费」）**：新增 `runtime/worker.py`（`RunWorker.claim_one/finish/run_once/drain`）。
  领取=`QUEUED`→`RUNNING`（`FOR UPDATE SKIP LOCKED`）+授权窗口 `min(deadline_at, start+120s)` + `STARTED` 回调**同一事务**；
  调查在事务**之外**；收尾用 `WHERE status='RUNNING'` 条件更新，取消者胜出且**拒绝写回调**（fence属C09）。
  回调映射 `PROPOSE→PROPOSAL/CALLBACK_PENDING`、`ASK_CUSTOMER→QUESTION/WAITING_INPUT`、其余`FAILED/FAILED`；
  id 由 run 派生，载荷幂等。`CallbackStore.enqueue_for_run` 增**可选** `connection`（同事务落库，缺省行为不变）。
  实测 `pytest tests` → **987 passed（+11）, 9 skipped**；ruff通过；mypy **9=基线（51文件）**。见[报告](../reports/c08-2-run-worker.md)。
  **仍缺**：①派发→调查→回调之后半段（Java复核/必要审批→模拟退款）；②补证新run/旧结果STALE（`STALE`状态与`parent_run_id`列已在，无人使用）；
  ③mock/live 客户端工厂（`investigate` 是可注入缝但无可部署入口）；④`verify_proposal()` 接入run路径；
  ⑤**新发现需决策**：v2 proposal 要求 `case_type`，而 `agent_run`/`RunRequest` 均无此列——**未编造取值**，修法是派发协议带上并同步Java消费者（契约变更，需确认）；
  ⑥`result_summary` 仍留NULL（脱敏规则未定前不写原始模型文本）；⑦崩溃时run留`RUNNING`不伪装成`FAILED`（有测试钉住），其恢复属C09。
- **已完成 2026-09-26（C08.2-2「部署装配缝」）**：新增 `runtime/factory.py`——`DeploymentConfig.from_environ` + `build_investigation(database, config, model=, tools=, …)`
  返回 `Callable[[RunFacts], RunResult]`（每run新建模型客户端与MCP执行器、跑`AgentScopeRunner`、退出关闭执行器；索引建一次）。
  三处刻意拒绝：**模式必须指名（无默认值**——默认mock会产出非模型产出的方案，默认live会在没人写过的配置上花钱）；
  mock模式必须传入脚本化客户端（工厂替它写脚本=替它写决定）；live缺endpoint/model_id在**构造期**拒绝（配错不会先发请求再发现）。
  实测 `pytest tests` → **994 passed（+7）, 9 skipped**；ruff通过；mypy **9=基线（52文件）**。
  **Python侧"派发→调查→回调"闭环已通**（端到端一例：真实AgentScope循环、工具真的执行、出箱`["STARTED","PROPOSAL"]`、run=`CALLBACK_PENDING`；模型脚本化/工具替身，无provider/无MCP子进程）。
  见[报告](../reports/c08-2-deployment-factory.md)。**仍缺**：Java复核/审批→模拟退款；补证新run/旧结果STALE；`verify_proposal()`接入；`case_type`决策；常驻调度循环入口。
- **已完成 2026-09-26（C08.2-3「补证→旧run STALE」）**：`RunStore.queue()` 在**同一事务**内、插入新run后调用
  `_supersede_older_revisions`：同case旧revision的**非终态**run置 `STALE`（`COMPLETED`/`FAILED`/`CANCELLED` 不动——
  `COMPLETED`表示回调已被Case接收，改它会抹掉事实；"方案不再适用"属Case的 `case_proposal`），并以
  `CallbackStore.void_pending_for_run`（**不累加 attempts**，只动PENDING行）同一事务关掉旧run未投递的回调。
  实测 `pytest tests` → **1001 passed（+7）, 9 skipped**；ruff通过；mypy **9=基线（52文件）**。
  US-C3"旧结果不会覆盖"有正面测试：调查进行中被补证，`finish()` 条件更新拒绝、run留STALE、出箱无PROPOSAL。
  见[报告](../reports/c08-2-3-supersede-stale.md)。**注意**：该逻辑使 `test_drain_...` 原fixture（同case revision 2）
  失效——**实现对、fixture不现实**，已改为两个不同case（断言未删，测试docstring写明）。
- **新发现缺口（下一子步，须两件一起改）**：`docs/agent-spec.md:9` 规定 `COMPLETED`表示**方案回调被Case接收**、
  `QUESTION接收后WAITING_INPUT`，但 `delivery.py:192` 只记录 `disposition`、**无人把答复回写run状态**（全仓 `UPDATE agent_run`
  仅在 `worker.py`/`runs.py`），故方案被ACCEPTED后run永远停在 `CALLBACK_PENDING`；而C08.2-1的
  `ASK_CUSTOMER→WAITING_INPUT`（finish时直接置位）与规范不符（应先 `CALLBACK_PENDING`、接收后才是 `WAITING_INPUT`）。
  只改后者会让QUESTION永远停在CALLBACK_PENDING，故**两件必须同一步改**。设计：`RunStore` 按答复落状态
  （ACCEPTED/DUPLICATE：PROPOSAL→COMPLETED、QUESTION→WAITING_INPUT、FAILED→FAILED；STALE→STALE），由 `deliver_one`
  在与出箱记录**同一事务**内调用（需 `connection=` 缝）。届时 `test_a_question_moves_the_run_to_waiting_input`
  须按规范改写而非删除。
- **已完成 2026-09-26（C08.2-4「答复决定run状态 + QUESTION语义纠正」）**：补上"Case答复无人回写run状态"的缺口。
  `db.reuse_or_open(database, connection)`（调用方有事务就用它）+ `CallbackStore.transaction()`；`record_delivery` 增 `connection=` 缝，
  三处缝统一同一写法。`deliver_one` 在**同一事务**内先 `record_delivery` 再
  `RunStore.apply_callback_disposition`：PROPOSAL+ACCEPTED/DUPLICATE→`COMPLETED`、QUESTION→`WAITING_INPUT`、
  FAILED→`FAILED`、任意+STALE→`STALE`、STARTED→不变（`RUNNING`由claim写下）；`DUPLICATE`与`ACCEPTED`同义
  （`contracts.md:80`，状态不该取决于网络重试几次）；条件更新 `WHERE status<>ALL(terminal) AND status<>STALE`，
  **已取消的run不会被答复复活**。`worker.py` 的 `ASK_CUSTOMER` 终态由 `WAITING_INPUT` 改为 `CALLBACK_PENDING`
  （`agent-spec.md:9`：接收后才是WAITING_INPUT）。实测 `pytest tests` → **1010 passed（+9）, 9 skipped**；ruff通过；
  mypy **9=基线（52文件）**。见[报告](../reports/c08-2-4-answer-decides-status.md)。
  **一处断言改写已披露**：`test_a_question_moves_the_run_to_waiting_input` 钉的是与规范相反的行为，改为
  `test_a_question_is_filed_and_leaves_the_run_awaiting_receipt`（断言**更多**：run为CALLBACK_PENDING且回调仍PENDING，
  并指向投递侧钉"接收后WAITING_INPUT"的那一例），非删除。
- **C08.2 剩余**：Java半段**未由本轮验证**——`docs/implementation-handoff.md:27` 记 Case 的 `POST /evidence` 与回调收件箱
  （DUPLICATE/STALE/409语义）已实现、PROPOSAL可按钉住政策版本核对引用并重算金额；未打通的是 Java `PENDING_REVIEW`→审批→
  执行派发→模拟退款（`ExecutionDispatchLoop` 默认关闭），且 **Java侧本轮未运行**（C07.1 的 BUILD SUCCESS 非本轮证据）。
  另缺：`verify_proposal()` 接入run路径；`result_summary` 脱敏规则；常驻调度循环入口；`case_type`（**需决策**）；`parent_run_id` 无人写。
- **契约核查发现（2026-09-26，C08.2-5，仅核查未改码，严重度高）**：上一条把 `case_type` 记为"需决策"是**错的**——
  `openapi-agent.yaml`(派发)确无该字段，但 `openapi-case.yaml:1622 ProposalPayload` **要求**它，并写明
  "**the run classified the case**"，即它是**run自己的分类产出**，无需外部决策，缺的是run产出它的能力。
  顺查发现更严重的问题：**worker 现在发出的四种回调载荷都不满足已发布契约**（均会被422/失败记录）——
  STARTED/QUESTION/FAILED 多了 `schema_version`（`additionalProperties:false`）；QUESTION 的 `AgentQuestion` 要 `field`+`prompt` 而非 `question_id`；
  PROPOSAL **缺** `run_id`/`case_id`/`input_revision`/`case_type` 且 `proposal_id` **不是UUID**（契约是 `$ref: Uuid`）。
  根因：现有测试只对照 **Python 自己的 `_REQUIRED_PAYLOAD_KEYS`**（只查缺、不查多/类型/枚举），且投递测试用 `ScriptedPoster` 绕过契约校验
  ——"Python通过不等于Java批准"的具体形态。**因此"C08.2 闭环已通"须收窄为"只在Python自身检查下通"**。
  修复计划（小步）：①先写"载荷对照 `openapi-case.yaml`/`agent-proposal.schema.json`"的失败测试；
  ②`ModelDecision` 在 PROPOSE 上要求 `case_type`（枚举=`enums.py:97 CaseType`），其它kind出现即拒，缺失走既有一次修复通路，
  并让 `_tool_schema_document` 广告该成员（**会改 prompt_hash 与 manifest_id**，须一并记录）；③`_payload` 逐kind对齐契约；
  ④再谈 `verify_proposal()` 接入（否则校验的是错的文档）。详见[报告](../reports/c08-2-5-callback-payload-contract-gap.md)。
- **已完成 2026-09-26（C08.2-6「载荷对照已发布契约」）**：新增
  `tests/unit/test_callback_payloads_match_the_case_contract.py`，用仓内 `component_validator("case",<组件>,"contracts/core",CORE_SCHEMA_FILES)`
  把**实际组装的载荷**喂给契约（并为此把组装函数提为公有：`worker.started_payload(...)`、`_payload`→`callback_payload(...)`）。
  捕获到真实错误：FAILED/QUESTION/STARTED 均因 `additionalProperties:false` 多 `schema_version`（QUESTION还多`summary`），PROPOSAL缺
  `proposal_id`/`run_id`/`case_id`/`input_revision`/`case_type`。**已修STARTED与FAILED**（现在**真通过**契约校验）；
  **PROPOSAL/QUESTION 仍 `pytest.skip(<具名理由>)`**——缺ABI成员（`case_type`、`AgentQuestion.field`），断言体已留，实现后去skip即可。
  实测 `pytest tests` → **1012 passed, 11 skipped**；ruff通过；mypy **9=基线**。
  **下一步**：`ModelDecision` PROPOSE 加 `case_type`（枚举 `enums.py:97`）、问题成员加 `field`，在 `_tool_schema_document` 广告二者
  （**会改 prompt_hash/manifest_id**，须记录），再去掉两个skip。
- **已完成 2026-09-26（C08.2-7「ABI成员 + 载荷合法化」）**：`actions.py` 增 `ModelDecision.case_type`（PROPOSE专用、取值限 `CASE_TYPES`=`enums.py:97` 四个之一）
  与 `AskQuestion.field`；`sdk_runner._tool_schema_document` 广告二者（**已改变 packet 与 prompt_hash/manifest_id**）；
  `worker.callback_payload` 按契约重塑（PROPOSAL=全 `ProposalPayload` 必备成员且 `proposal_id` 为 **uuid5**；
  QUESTION 只发 `question_id/questions[{field,prompt}]/reason_codes`）。**两个skip已转真通过，4例契约校验全绿**。
  实测 `pytest tests` → **1014 passed, 9 skipped**；ruff通过；mypy **9=基线**。
  **刻意保留的部分状态（下一步必做）**：两个新成员目前**只是"可选但必须合法"，尚未强制**——强制会让**60个既有用例**
  失败（其PROPOSE/问题fixture尚无新成员；13处字面量好改，但 `test_harness_loop.py`/`test_loop_semantics.py` 走各自
  `propose()` 辅助函数，grep未及）。**后果：模型漏填 `case_type` 时仍会组装出Case会拒的载荷**。
  顺序：先补全fixture → 再打开强制 → 全量复验。详见[报告](../reports/c08-2-5-callback-payload-contract-gap.md) §8。

### C09/C10及后续

- C09：持久预占、稳定call_id、UNKNOWN成本、fence、结果复用、manifest/deadline不重置；复用已有spike，但在生产路径重新验证。
- C09开工前解决恢复预算冲突：历史记录批准“预留恢复额度”，spike实现为普通12次之外再2次，规格却是总12次。默认不继承豁免；应在总额内预留或请用户确认显式扩额，并同步manifest/协议/实验。不要在本轮提前修改该历史决策。
- C10：5个strict包、缺记录/篡改失败、无业务凭据与OS级禁网、实际业务写反例。Python monkeypatch与import扫描不算完整隔离证明。
- 再按todo推进C11–C13，不增加非核心功能；简历只用已验证证据。

## 3. 验证与记录

在各项目目录运行，不混用两个tests包；命令完整说明见[engineering](../docs/engineering.md)。现有venv可直接运行：

```powershell
# 工作目录 agent/
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=short
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy
# 工作目录 spikes/agentscope/
.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=short
```

报告分别列：通过、失败、跳过/未运行；strict mypy既有9处问题不能写成全绿，新增错误不得混入基线。`all-offline`不包含全部Python integration/live；它通过不等于H1–H5。没有改相关代码时无需反复重跑相同命令；最终回归必须针对交付状态。

## 4. 可复制给DSH的提示词

```text
请在 E:/Code/Agent+Backend 接续 ResolveFlow。先读 AGENTS.md、README.md、docs/core-scope.md、tasks/handoff-current.md，以及 tasks/todo.md 顶部/C08 和 tasks/plan.md；历史交接仅按需查，不重做C00或AgentScope迁移。

先检查实时git状态和diff，保留已有未提交修复与报告，确认无同文件并行编辑；正常新提交或报告脏文件不是停止理由。2026-09-26已修复预算、上下文核算、退款事实提取和回放Python入口，详见 reports/c08-review-fixes.md，勿重复造实现。

从 tasks/todo.md 顶部列出的当前接续项开始，不从本文历史C08.1a或AS迁移重新开工。先用当前源码和针对性测试确认该项是否已实现；已有实现只补缺口，不重写。按账本收口C08的ABI/fixture、最终方案验证、常驻worker与跨服务业务闭环，再接C09/C10及依赖满足的C11–C13。若代码已前进，先记录证据并更新账本起点，不照抄旧测试数量。

每步通常3–5核心文件，先关键失败测试再实现；保留权限、预算、无进展、工具批次、错误回传和契约断言。模型所需事实必须进入实际messages，不能只让mock读取隐藏context。组件测试、真实MCP/Java闭环和live效果分别记录，不能因此提前勾H1–H5、C09或C10。保留AgentScope 2.0.8/MCP 2.2.0和其他版本锁，不做整体重构。

项目以简历展示为导向，但不增加组件凑亮点。开工某个亮点任务前读 docs/resume-evidence.md 的对应映射；每步记录业务问题、设计取舍、实际代码入口、失败测试/报告和主张边界。C11.2必须按账本子步完成一个真实读路径的SQL基线、索引分析、Redis非权威缓存、有界回源及故障验证；测量口径只遵循 docs/evaluation.md，不编造收益、不人为劣化基线。性能入口未实现时明确失败，不能空跑成功。

进度只更新 tasks/todo.md 顶部，详细结果追加到对应C任务或reports；handoff-current只维护通用执行规则。每步报告实际文件、完整命令、通过/失败/跳过/未运行和下一子步，最终按C13把候选简历主张逐条对应到真实证据。原任务依赖与实验规模不变。

用户已授权每个验证通过的独立小步立即commit并正常push，无需再问，不等整包完成。严格遵循 docs/engineering.md 第8节：先核对既有remote/upstream和历史待推送范围，只精确暂存本步及必要依赖、测试和记录，不夹带其他改动或敏感文件。已有积压先分组核实验证，不全仓add。本步测试不能依赖未提交内容才能通过。每次提交后推送并确认远端包含该SHA，报告commit、目标分支和push结果；失败保留commit并报告，暂停新增功能，不force push或擅自重写历史。

范围内普通实现自行推进；仅涉及收费API/模型选择的实质新决策、恢复预算规范冲突、外部权限、Git目标/冲突或同文件并行改动时请求确认。不要清库、删卷、reset或覆盖用户修改。结束时给出可演示行为、实际验证结果、未完成项、提交/推送状态和下一子步。
```
