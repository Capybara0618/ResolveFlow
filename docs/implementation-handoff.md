# 实现模型交接 · v1.2

目标是个人技术展示，不是公司级平台。用户已批准瘦身；请从[核心范围](core-scope.md)、[新任务账本](../tasks/todo.md)继续，不按旧40项计划推进。

## 当前事实

T00–T02有已完成证据，包含锁、骨架、旧协议与测试。C00（核心协议与启动范围迁移）已完成：`contracts/core` 下已有 profile、三个 v2 Schema、三份核心 OpenAPI、正反 fixture 与冻结期望值，Python/Java 两侧核心 DTO 与跨语言字节级一致测试，启动/smoke 已按 core profile 选择。旧资料见tasks/archive，不要重新生成全部项目或删除已有测试。

### 当前可启动的服务（2026-09-23）

`pwsh -File scripts/verify.ps1 -Suite smoke` 默认 `-Profile core`，实际启动并读健康端点：gateway(8080)、commerce-service(8081)、case-service(8083)、agent(8090)。commerce-service 自 C01.2b 起在启动时连接 `commerce_db` 并跑 Flyway 迁移（compose 的 mysql 由 smoke 的 infra-up 先起，本机默认 `commerce/commerce`），所以它现在真的需要一个数据库才能健康。默认**不**启动 `fulfillment-service` 与 Nacos；`-Profile compat` 才加上它们（旧入口与旧断言保留）。证据见 `reports/verify/` 下的两份 smoke 报告。

### 已实现到哪一步（不要读成已完成；每步的命令/结果/欠账见 tasks/todo.md）

后端服务已经不止骨架，粗略按工作包如下：case-service 的 `POST /api/v1/auth/login`（演示账号换 JWT）、`GET /api/v1/orders`、`GET /api/v1/orders/{order_id}`、`POST /api/v1/cases`（建单：`Idempotency-Key` 幂等、同 line 单活跃 case、行归属由 Commerce 判定）、`GET /api/v1/cases/{case_id}`（工单视图 + 轨迹；跨主体 404）与 `POST /api/v1/cases/{case_id}/evidence`（材料追加：只追加不覆盖、revision 由服务端决定、来源决定谁可提交、已终结则 409）与 、`POST /api/v1/cases/{case_id}/cancel`（消费前取消：终态、释放活跃 slot、不可重复取消）与 `GET /api/v1/cases/{case_id}/events`（SSE 轨迹流：先重放后推送、Last-Event-ID 续传、终态收流）；政策由受控命令导入（`--resolveflow.policy.import-dir`，不可变版本 + 按支付时间选择窗口），只读面 `GET /internal/v1/policies/{bundle_id}` 供 Agent 取正文，`GET /internal/v1/cases/{case_id}/policy-manifest` 返回按支付时间选中并钉在工单上的版本；作用域一律由已校验主体推导，内部调 commerce-service 的 `GET /internal/v1/order-lines`（列表）与 `GET /internal/v1/order-lines/{line_id}/context`（单行 + 该订单 ledger 的 `refunded_amount`/`reserved_refund_amount`，Java 重算金额的权威来源），两者都 service token 专用，数据来自 `commerce_db` 的迁移与种子。回调面 `POST /internal/v1/cases/{case_id}/agent-callbacks` 已实现收件箱与投递语义（`callback_id` 主键即「最多应用一次」、逐字重投 DUPLICATE、旧 revision 或人工接管后 STALE、同 id 换内容 409、STARTED/QUESTION/FAILED 各自的状态与轨迹后果），**PROPOSAL 已可接受**：Java 按工单钉住的政策版本核对引用（`bundle_id`/`version`/`rule_id`/`chunk_id` 与重算的 `content_hash`）并从 Commerce 的行上下文重算金额，结果以 `case_proposal` 存下 `VALIDATED` 或带原因的 `REJECTED`，工单转入 `PENDING_REVIEW`，方案随工单视图返回（旧 revision 显示为 `STALE`）；结构或绑定错误（`case_id`/`input_revision`/未知动作/非 REFUND 带金额等）仍是 422；C03.2c 补上商家内审核队列 `GET /api/v1/review/cases`（只含本商家 `PENDING_REVIEW` 工单、`updated_at` 倒序 keyset 游标分页、客户角色 403、坏游标与越界 limit 400）与人工核验追加 `POST /api/v1/cases/{case_id}/reviewed-evidence`（新记录引用被核验记录并带 CONFIRMED/REFUTED/INCONCLUSIVE，原材料正文与 hash 不动，客户角色 403，跨工单引用 422，工单材料按契约 `maxItems` 封顶 64 条），工单视图的 `evidence` 因此从只声明变为真的在服务（`EvidenceView`：引用 + 正文 + 追加人与 revision；核验结论结构化可读），`authorization` 也在 C03.3a 开始服务：授权随通过重检的方案在回调事务内创建，`operation_id` 与 `payload_hash` 在批准之前定死（重试只能复用同一 operation id），`AuthorizationState` 带自己的 `input_revision`，被拒方案与不动钱的建议都不产生授权；C03.3b 补上人工决定 `POST /api/v1/cases/{case_id}/reviews`（`If-Match` 为工单版本、body 的 `authorization_version` 为授权版本，任一过期 409；批准前重新校验 revision/hash/Commerce 可付性，revision 或 hash 不成立即令授权 `EXPIRED`，Commerce 暂时不成立只回 409；REJECT 结束工单并释放 slot，REQUEST_INFO 回到 `WAITING_CUSTOMER` 并令授权 `EXPIRED`；`decided_by`/`decided_role`/`decision_reason` 与 `AUTHORIZATION_DECIDED` 轨迹行一起落库，客户角色 403、跨商家 404、非本工单授权 422），但**尚未有人批准过任何东西**：compose 库里四条 line 都已被活跃工单占用、唯一被接受的方案早于授权表存在，因此真实数据上只验证了各条拒绝路径（`tmp/e2e_review_decision.py`，8 条），决定路径由模块测试在真 MySQL 上覆盖。C03.3c-1 补上人工方案 `POST /api/v1/cases/{case_id}/manual-proposals`（商家员工提交依据与理由，请求**没有金额成员**，金额由本服务从 Commerce 重算；提交推进工单输入 revision、同事务把活授权置 `REVOKED` 并为新 revision 建新授权，`AUTHORIZED` 的工单回到 `PENDING_REVIEW`，被拒提交什么都不写）；C03.3c-2 让任何新输入（追加材料、人工核验）都在写入事务里撤回活授权、在 `revoked_authorization_id` 里点名，并把 `AUTHORIZED` 的工单推回 `PENDING_REVIEW`（改前的行为是留给批准路径事后令其失效，工单视图会在一段时间里显示一笔对不上输入的批准）。case-service 需要 `case_db`（Flyway 迁移 + `case_svc` 账户）。C04 起退款执行侧开始成真：C04.1 交付跨进程的持久模拟 provider（`agent` 的 `POST /provider/v1/refunds` 与查询面；`UNKNOWN` 不是 `FAILED`、丢响应不结算、确定性失败成墓碑、重启后状态仍在），C04.2 交付 Commerce 的本地金额侧（`line_refund`/`refund_operation`/`refund_request_inbox`：同 id 换载荷拒绝、100 并发恰好一条成功、成功后预留 → 已退），C04.3 把 provider 调用放到**事务外**并让 `UNKNOWN` 可持久对账（传输错误=UNKNOWN、`reconcileDue` 是"读"而不是重发），但**没有自动对账调度器**。C05.1a 在 case-service 交付带签名的 event outbox（业务效果与事件同事务、事件离开服务时自带签名；默认 publisher 故意抛错，所以**没有真实 broker 时事件会重试后变 `DEAD`**）。C05.1b 补上 RocketMQ 生产/消费接线与 Commerce 的消费端 inbox（`V4__commerce_event_inbox.sql`：`event_inbox` 以 `(consumer, event_id)` 为主键 = "最多应用一次"，`event_rejection` 保留每条被拒消息；验签要求密钥在信任列表内、签名必须覆盖 topic/producer；被拒消息不再重试但在库里留档）。C05.1c 让这条链路第一次在**真实 RocketMQ + 真实 MySQL** 上跑通（`scripts/e2e_transport_refund.py`，PASSED，报告 `reports/c051c-transport/20260923-114527-e2e-c051c.txt`：CF1 重排后同一份字节被再投一次、重复投递恰好一笔预留、篡改消息被拒并在 `event_rejection` 留档、`deadlocks=0 redeliveries=0`），并且**磨出了五个 mock 暴露不出的问题**：RocketMQ 拒收带点的 topic 名（协议里的 `rf.case.core.v2` 保持不动，新增 `CoreTopicNames.brokerName()` 只在传输边界派生，两个服务共用）；并发重复投递让"插入即认领"死锁（改为单语句 upsert + 受影响行数，注意 Connector/J 的 `CLIENT_FOUND_ROWS` 会让未变更的重复行也返回 1）；确定性业务拒绝曾被无限重投、而重投会重复拿行锁进而死锁无关命令（listener 现在对它也 ACK，只改"要不要再问一次"，C05.1b"业务拒绝不是毒消息、不写 `event_rejection`"的判定原样保留）。**仍未实现（不要读成已有能力）**：从"已批准的授权"到"落库并投递命令"（C05.2，`case_execution_command` 有表但没有写入方）、退款结果事件（`RefundSucceeded/Failed/Unknown`）的 outbox 与 Commerce→Case 的投影/权威查询（业务拒绝回传给 Case 也依赖它，在那之前只有日志行）、`UNKNOWN` 的自动对账调度、并发 upsert 残留死锁的取舍、以及真实 broker 上的乱序面与多实例竞争。核心其余 11 条路由（28 − 17）、Agent 调查/政策检索、恢复与回放、实验与主张都未实现；observability 容器尚不存在。`contracts/core` 里的目标协议不代表已在运行。

### 当前位置（2026-09-23，C06 开工前）

**C04 与 C05 已全部完成**（C04：持久 provider、Commerce 本地金额事务、UNKNOWN 对账；C05：带签名 event
outbox、RocketMQ 生产/消费、结果 inbox 与投影、**真实 broker 上的系统级 e2e**，以及 C05.3 复审收口与
C05.4 债务清理）。当前可复现的证据：case **187（4 skipped）** / commerce **72** / shared-kernel **59**、
`spotless:check` 干净、契约 pytest **548 passed**、项目门禁 `all-offline` **PASSED**
（`reports/verify/20260923-181119-all-offline.txt`）、真实链路 `scripts/e2e_refund_chain.py`
**RESULT: PASSED (111.5s)**。

**家（唯一工作副本）**：`E:\Code\Agent+Backend`（在 `E:\Code\` 里面，名字是 `Agent+Backend`）。2026-09-23
做过一次**工作区归一化**：项目最初就在这里，2026-09-22 第一次事故后为了不丢东西从 GitHub 重新克隆，克隆落到了
只多一个 `+` 的 `E:\Code+Agent+Backend`，此后所有工作都在那边做——于是同一台机器上出现两个只差一个字符的
仓库，2026-09-23 就有一次新会话开错目录、白问了三个早就做完的问题。现在工作副本已搬回这里：完整历史、
`origin` 远端、`core.autocrlf=false`/`core.eol=lf` 一致；`agent/.venv` 与 `web/node_modules` 是重建的。
原因、命令、结果与未做项见 `tasks/todo.md` 的 **C05.5**。

**下一件事是 C06（Agent 控制面、MCP 与能力冒烟；依赖 C02，早已满足、无阻塞）**。开工读
**`tasks/handoff-c06.md`**：那里有 Python 侧的真实起点（`api/app.py` 其实是 provider stub 的 HTTP 面，
`tools/`/`runtime/`/`harness/` 还是空包）、C06 三片的验收原文，以及**会影响 C06 的新约束**
（服务令牌必须带 `iss`、证据引用必须四件齐且 hash 是 64 位 hex、结果金额必须等于本工单授权金额）。

**✅ 2026-09-23 已全部推送**：`b814463`（C05.2b-3b）之后的全部提交都已在远端（含本文件与
`tasks/handoff-c06.md` 的同步提交；精确数量用 `git rev-list --count b814463..HEAD` 查）。**状态以
`git log -1` 与 `git status` 为准，不要以本文件里写的 sha 或数字为准**——文档里的这些一定会比仓库旧。
开工先核对 HEAD；本仓库曾被会话之外的进程静默回退过两次，若发现 HEAD 明显落后、或文件在批量消失，
按下面"开始步骤"第 5 条处置。

## 开始步骤

1. 读AGENTS.md、README.md、core-scope、dsh-migration-handoff、tasks/plan和todo。
2. 检查git status与当前实现；并行客户端如仍在改同一文件，先停止冲突编辑并确认交接，不覆盖其工作。
3. C00–C03 已完成，C04.1–C04.3、C05.1a/C05.1b/C05.1c、C05.2a 与 C05.2b-1 也已完成（退款执行侧：持久 provider、Commerce 本地金额、带签名 event outbox、RocketMQ 接线与消费端 inbox、真实 broker 上的系统级 e2e；C05.2a 补上授权→命令的写入方：消费与命令同一事务，取消会撤回还没消费的批准；C05.2b-1 补上 Commerce 的结果 outbox：成功/确定失败/UNKNOWN 三个路径与结算同事务写签名结果事件，形状与 `contracts/core/fixtures/expected.json` 的冻结期待逐成员比对；C05.2b-2 补上结果投递：commerce 侧签名发布器、投递服务与投递循环（镜像 C05.1a/b，含"没接 broker 时拒绝一切而不是静默 no-op"的默认发布器），投递状态机的失败/放弃/不重发三条路径有测试，但**结果真的进了真实 broker 尚未验证**）；下一项是 **C05.2b-3**（Case 的结果 inbox、按信任表验签、按 `aggregate_version` 排序的投影——成功才关单、失败释放后再试须新授权、UNKNOWN 保持 `RECONCILING`——以及仍未定的"业务拒绝怎么回传 Case"），之后 C05.2c 用真实 broker 跑 approve→command→refund→result 两段端到端，再按 tasks/todo.md 的 C01–C13 图推进，不回旧 T03 扩展。C05.1c 的复跑方式与五个发现（含"发现 D：确定性业务拒绝曾被无限重投"这一 C05 复审要点）见 tasks/todo.md 的 C05.1c 条目，C05.2a/C05.2b-1/C05.2b-2 的实现、守卫与未做项见同文件对应条目。**〔2026-09-23 更新：上面这段"下一项是
C05.2b-3"已经过时——C05.2b-3、C05.2c、C05.3（复审收口）与 C05.4（债务清理：坏游标 400/503、JWT `iss`
校验、证据引用完整性三处真修复）均已完成并通过门禁。**当前起点是 C06，读 `tasks/handoff-c06.md`。**〕**
4. 只加载当前任务相关专题规格；每子步3–5核心文件，先失败测试、再实现/验证、更新真实记录。
5. **开工前先确认工作区是真的**：本仓库在 2026-09-22 与 2026-09-23 两次被会话之外的进程静默回退/删除（第二次把工作区退回 2026-09-22 16:36 的快照，未推送的提交与文件全部消失，C05.1b 的代码只能从会话记录里恢复）。因此：先 `git log -1` 与 `git status` 核对 HEAD 是不是预期提交，发现文件批量消失时先停掉自己起的后台作业与进程、把残留状态保全到仓库外，再从远端恢复，并优先把已验证的提交推到远端——本机不是可靠存储。详见 tasks/todo.md 的 C03.3c-2 与 C05.1b 两条记录。

## 不再必做

补发/库存/Fulfillment独立部署、跨动作权益Saga、执行中取消协议、反事实/world回放、完整RAG/上下文消融、完整观测集群。旧T35–T39不自动继续；其核心内容已并入C06–C10/C12。

## 不能简化掉

真实MCP、自主动作、预算/上下文/恢复边界；Java权限、金额、退款幂等、UNKNOWN处理、Outbox/inbox与旧授权拒绝；真实评测分母及严格回放隔离。不用固定工具workflow冒充Agent，不用内存状态冒充恢复。

## 持续推进

普通实现字段/索引/帮助类自行处理；改契约同步类型/fixture/消费者，迁移只追加。重大架构矛盾、外部权限或API预算需要用户决定。无密钥可先mock/独立任务，不声称live完成。

每阶段报告可演示行为、实际命令/测试/报告、失败/未运行、下一步。C05审查退款边界，C09审查恢复，C12审查实验，C13审查简历主张。文档不能替代代码验证。

## 可直接给DSH的指令

> 项目已调整为v1.2个人项目核心版。请先停止按旧T03–T39清单扩展，保存当前进度，不删除现有代码。阅读AGENTS.md、docs/core-scope.md、docs/core-contracts.md、docs/implementation-handoff.md和tasks/todo.md，检查工作区后从C00开始。复用T00–T02成果，保持旧兼容测试，并新增核心协议/profile，不实现延期功能。每次交付一个可验证小步骤，执行相关测试、更新实际记录；不要把目标规格当成已有实现，不启动未经确认的收费评测。
