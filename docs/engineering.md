# 工程与命令 · v1.3（保留v1.2核心）

复用已有骨架与非Agent框架版本锁，不重建仓库。AgentScope 2.0.8已接入，当前任务见[当前交接](../tasks/handoff-current.md)和账本；本文区分已有命令与目标命令，不能把历史通过结论当作本轮验证。

## 1. 目录与风格

java/{gateway,case-service,commerce-service,shared-kernel}为核心；fulfillment-service留作旧骨架，默认不启动。agent/src/resolveflow/{api,runtime,harness,tools,policies,callbacks}沿用。contracts/core为C00新增目标；原contracts兼容基线保留。web保留轻量Vue界面，reports只放真实证据。

Java record DTO、构造注入、MyBatis、Flyway、显式application事务，金额不用float，Clock可注入。Python Pydantic、类型标注、明确timeout与取消、mock/live ModelClient，Ruff/mypy及uv.lock。已有风格不为重构而重构。

示例事务边界（不是完整代码）：

```java
@Transactional
public RefundOperation accept(RefundCommand command) {
    var previous = operations.find(command.operationId());
    if (previous != null) return previous.requireSamePayload(command.payloadHash());
    ledger.reserveUnderLock(command);
    return operations.createWithOutbox(command);
}
```

真实实现必须在同事务处理inbox、金额/行占用及唯一键；provider网络调用在事务外，不照抄示例省略约束。

## 2. 当前可运行入口

下列入口已有实现，历史结果见todo与reports；本轮文档修订不代表全部重跑。工作目录仓库根：

| 用途 | 命令 |
| --- | --- |
| 环境 | pwsh -File scripts/doctor.ps1 |
| 格式 | pwsh -File scripts/verify.ps1 -Suite format |
| 单元 | pwsh -File scripts/verify.ps1 -Suite unit |
| 契约 | pwsh -File scripts/verify.ps1 -Suite contracts |
| 当前离线集 | pwsh -File scripts/verify.ps1 -Suite all-offline |
| Python针对性 | uv run --project agent --frozen pytest agent/tests/unit -q |
| Java契约 | .\java\mvnw.cmd -f java/pom.xml -B -pl shared-kernel -am test |
| 前端 | pnpm --dir web test |

当前all-offline包含真实服务smoke和基础设施依赖，不等于不需要Docker；它只表示不使用外部付费模型API。核心选择已调整（C00.3）：`verify.ps1 -Suite smoke`默认`-Profile core`，只启动gateway/commerce/case与Agent，不启动fulfillment与Nacos；`-Profile compat`保留旧的完整入口，旧断言一条未删。启动集合来自`contracts/core/profile.json`，不在脚本里再写一份。

## 3. 尚未实现的目标入口

| 用途 | 命令 | 归属 |
| --- | --- | --- |
| 核心启动 | docker compose -f infra/compose.yaml --profile core up -d --build | C00选型、C11完整落地 |
| 退款系统测试 | pwsh -File scripts/verify.ps1 -Suite system -Mode mock | C05/C08 |
| Harness回归 | pwsh -File scripts/verify.ps1 -Suite harness -Mode mock | C08–C10 |
| 轨迹导出 | pwsh -File scripts/replay.ps1 -Action export -RunId <UUID> -Out <directory> | C10 |
| 严格回放 | pwsh -File scripts/replay.ps1 -Action run -ReplayMode strict -Pack <directory> | C10 |
| 核心故障 | pwsh -File scripts/verify.ps1 -Suite faults -Seed 42 | C12 |
| 真实模型对照 | pwsh -File scripts/verify.ps1 -Suite agent-eval -Mode live -Seed 42 | C12 |
| 检索对照 | pwsh -File scripts/verify.ps1 -Suite rag-eval -Mode live -Seed 42 | C07/C12 |
| 查询性能 | pwsh -File scripts/verify.ps1 -Suite performance -Seed 42 | C11/C12 |

默认未实现suite退出2、未知suite退出64，不得零步骤成功。-Case支持按case过滤由归属任务实现；不存在脚本/容器时不放空stub凑启动。旧harness-eval、反事实命令标DEFERRED，不是核心交付门槛。

### AgentScope迁移命令边界

`spikes/agentscope`与独立锁已存在。分别在`agent/`或`spikes/agentscope/`执行`uv run --frozen pytest tests -q`，避免两项目的同名tests包互相遮蔽；已同步venv也可用`.\.venv\Scripts\python.exe -m pytest tests -q`，无需每次重新解析依赖。详细聚焦命令与未运行项见任务账本。

生产依赖在AS02更新后用`uv sync --project agent --frozen --all-extras`验证。Python lint为`uv run --project agent --frozen ruff check agent/src agent/tests`；mypy必须切到`agent/`运行`uv run --project . --frozen mypy`，不能从根目录误报空检查成功。Java wrapper在`java/`目录执行`.\mvnw.cmd -B test`及`.\mvnw.cmd -B spotless:check`。相关命令只在对应任务实际运行后登记结果。

旧LangGraph兼容试验保留独立依赖环境，不要求生产agent安装旧框架来运行历史spike。schema/协议测试仍保留；全套门禁不得通过跳过迁移后失败用例变绿。已有mypy欠账与新回归分开记录，未解决前不能宣称全绿。

## 4. 常驻循环与开关（C06.3 补记）

服务里有几件事**没有请求也会发生**。它们各自是一个独立 bean（Java）或一个守护线程（Python），都在自己的开关后面，**默认关闭**——唯一的例外是 Agent 的回调投递：outbox 没人 drain 就是回调永远不到，所以它默认开着，并且必须被告知 Case 在哪。

| 循环 | 触发属性 | 默认 | 做什么 | 失败时 |
| --- | --- | --- | --- | --- |
| `OutboxDeliveryLoop`（case） | `resolveflow.events.outbox.delivery-enabled` | 关 | 把已签名事件投到 broker | 保留行、排下次重试 |
| `ExecutionDispatchLoop`（case） | `resolveflow.dispatch.enabled` | 关 | 把已批准授权花掉，生成退款命令 | 记日志、下次 tick 再来 |
| `AgentRunDispatchLoop`（case） | `resolveflow.dispatch.enabled` | 关 | 把待派发的 run 交给 Agent，直到 202 | 保持 `PENDING`、下次 tick 再来 |
| `CallbackDeliveryLoop`（agent） | 无常驻开关（`delivery_loop=False` 仅供测试） | **开** | 把 callback outbox 投回 Case | 退避重排；永久拒绝记 DEAD |

两个 run/callback 循环是**一条控制面闭环的两端**：Case 把 run 交给 Agent（`POST /internal/v1/runs`，等 202），Agent 把 run 的决定送回 Case（`POST /internal/v1/cases/{case_id}/agent-callbacks`）。两端都用 **at-least-once + 幂等键**（run 侧是 `run_id`，callback 侧是 `callback_id`），所以重投是安全的但不是免费的：Agent 的投递 worker 是进程内线程，**两个 Agent 副本会各自投递同一批行**，第二个只会被答 DUPLICATE。单副本是这个边界的部署前提，不是可以忽略的细节。

读写这两个开关的位置：`java/case-service/src/main/resources/application.yml` 只放数据源与 identity，循环开关由**运行参数/环境**给出（`--resolveflow.dispatch.enabled=true`，见 `scripts/e2e_refund_chain.py`）；Agent 侧读 `RESOLVEFLOW_CASE_BASE_URL`（默认 `http://127.0.0.1:8083`，与 case-service 一致）。

## 5. 五个只读工具（MCP stdio，C06.2b 补记）

Agent 调查工单时能读的东西**只有五个**，白名单在 `docs/agent-spec.md:26-32`，实现在 `agent/src/resolveflow/tools/`。它们以**真实官方 MCP stdio** 提供（`docs/agent-spec.md:34`），启动方式：

```
python -m resolveflow.tools.server          # 由驱动方按 run 起，配置经环境变量
```

| 工具 | 参数 | 读什么 |
| --- | --- | --- |
| `get_order_context` | 无 | Commerce 当前行订单/支付事实（金额的权威） |
| `get_shipment_trace` | `cursor` 可选、`limit<=20` | Commerce 模拟物流；**每 run 最多 2 页** |
| `get_refund_status` | 无 | Commerce 行退款状态 |
| `get_case_evidence` | `kind` 可选 | Case 当前 revision 的材料 |
| `get_policy_manifest` | 无 | Case 绑定的政策版本（不可自选） |

**五条来源都真的有人提供**（C06.2c 补记）：`order-lines/{id}/context`、`.../shipment`、`.../refund-status` 由 commerce-service 提供，`cases/{id}/evidence`、`cases/{id}/policy-manifest` 由 case-service 提供，路径逐字等于 `contracts/core` 里声明的路由——`source_ref` 就是请求路径本身，**引用可以直接 grep 回契约**。这不是自然形成的：`refund-status` 曾经是"契约声明了、工具在读、而 Java 一个字都没实现"，而已有的工具测试**全绿**，因为它们打的是桩，桩对什么都能回答。现在 `test_every_tool_reads_a_route_the_contract_declares` 断言每个工具的 `source_ref` 逐字命中契约路由**且**上游日志里确实出现过该路径；它能证明工具依赖的都是契约声明的东西，**不能**证明 Java 实现了它——那一半归 Java 控制器测试。

配置：`RESOLVEFLOW_CASE_BASE_URL` / `RESOLVEFLOW_COMMERCE_BASE_URL`（默认 `127.0.0.1:8083` / `:8081`，与 `scripts/e2e_refund_chain.py` 声明的端口一致，并由 `agent/tests/unit/test_tool_defaults.py` 钉住）、`RESOLVEFLOW_TOOL_SERVICE_TOKEN`（令牌的**变量名**，不是令牌本身）、`RESOLVEFLOW_TOOL_LINE_ID`（必填，被测行的 id——工具读"当前行"，猜一个就等于替模型决定调查什么）、`RESOLVEFLOW_TOOL_RUN_ID` / `RESOLVEFLOW_TOOL_CASE_ID`。

三条贯穿所有工具、也最容易做反的规则：

- **失败是一次成功的调用。** 读不到时返回的是**带 `error` 的 Observation**（`is_error=false`），不是协议错误——`docs/agent-spec.md:36` 要错误在 Observation 里，好让 `docs/agent-harness.md:51` 把它交回模型；协议级失败会被模型读成"传输抖了该重试"，对 FORBIDDEN 恰好是错的教训。
- **`NOT_FOUND` 不是否定事实，`FORBIDDEN` 不换 ID 重试。** 两者 `retryable=false`：再试一次答案不会变。`UPSTREAM_UNAVAILABLE` 才是 `retryable=true`。失败观察**不写 `source_version`/`content_hash`**——两项在 `CoreObservation` 里是"一起有或一起无"，因为只有版本查不出篡改、只有 hash 查不出过期，**任一个单独存在都比两个都没有更糟：它看起来可引用**。
- **过大就拒，不截断。** 原始响应 >256KiB 明确报错（读取时按块掐断，不信 `Content-Length`），给模型的 excerpt ≤8KiB 且**标注 `truncated`**。截断后的文档算出的 hash 谁也复现不出来，建立在它上面的引用会自己通不过校验。

每 run 的 trace 页预算记在**进程**上，不是记在 MCP session 上：mcp 2.2.0 每个请求给的是不同的 `ServerSession` 对象，挂 session 会导致计数器每次重置、上限形同不存在。stdio 下一个 server 进程就是一次会话，所以进程是对的；**将来若加多会话传输（streamable-http），这里必须改成按会话的键**（`server.py` 里 `_RUN_STATE` 的注释就是这条提醒）。

## 6. 核心资源与安全

MySQL的Case/Commerce独立schema/账号；PG Agent账户只访问agent_db；Redis不是授权事实。RocketMQ用核心v2 topics。core profile不依赖Nacos/Sentinel/完整观测容器；保留锁与可选配置，避免全量换栈。

### 演示账号（C03.2b-1 补记）

口令只以 PBKDF2 哈希存在 `DemoAccounts` 里，仓库文档此前没有列出；下表是**按哈希逐个验证过**的口令（不是按命名猜的），跑真实端到端要登录时用得上。它们只是演示凭据，正式部署应换掉并轮换 JWT 密钥。

| 用户名 | 商户/客户 | 角色 | 口令 |
| --- | --- | --- | --- |
| demo-customer | M-1001 / C-2002 | CUSTOMER | demo-pass-1001 |
| demo-customer-2 | M-1001 / C-2003 | CUSTOMER | demo-pass-1002 |
| demo-reviewer | M-1001 | REVIEWER | demo-pass-1003 |
| demo-operator | M-1001 | OPERATOR | demo-pass-3001 |
| demo-customer-m2 | M-1002 / C-2004 | CUSTOMER | demo-pass-2001 |
| demo-reviewer-m2 | M-1002 | REVIEWER | demo-pass-2002 |

provider-stub在C04落地轻量Python+SQLite持久模拟退款，含幂等/故障注入，不实现物流写协议。物流只读适配内置Commerce；版本化合成资料可从fixtures加载。

秘密不入库/日志/报告；.env不提交。故障路由仅lab且受控。数据库迁移只追加；旧履约库和卷不因停用被删除。关闭用compose stop保留卷，不授权清库、Git历史重写、购买或公网发布。正常Git推送已获用户授权，边界见第8节。

## 7. CI与完成定义

每子步先关键失败测试，再实现、验证、记录；通常3–5核心文件，过大先拆。CI覆盖现有兼容+核心契约、格式、单元、关键DB/MQ集成、mock闭环、strict小包、web build，不默认付费/重压测。

每完成项记录实际命令/日期/文件/报告/失败与未运行。允许任务含多子步，但不能只生成所有代码最后才跑。核心完成标准以core-scope/evaluation为准，不被旧T任务清单重新扩大。

### 常驻调查 worker（C08.2）

入口仍为 `uvicorn resolveflow.api.app:app`，不增加部署进程。调查默认关闭；显式设置
`RESOLVEFLOW_INVESTIGATION_ENABLED=1` 后，启动时打开/迁移Agent库并消费已有QUEUED记录。
关闭时停止领取新run，等待在途调查，然后关闭自有连接池；135秒内未结束明确报错，不假装线程已停止。

常驻worker每个run从Agent服务JWT密钥签发新的部署身份，再向Case的
`POST /internal/v1/runs/{run_id}/tool-credential` 领取绑定run/case/revision的工具凭证。
每次MCP工具读取都重新领取并使用run凭证；领取失败即该读取失败，不以部署身份向Case或Commerce读取。
`RESOLVEFLOW_TOOL_SERVICE_TOKEN`仅供直接使用部署工厂的脚本/测试提供领取凭证的身份；API常驻入口自行签发。
真实Java联调须使Agent与Case使用同一受控JWT密钥。

- `RESOLVEFLOW_MODEL_MODE=mock`：必须指定 `RESOLVEFLOW_MOCK_SCRIPT` 为UTF-8 JSON文件路径，内容是1–12个显式决策对象的数组，文件≤64KiB。
  每run使用新mock客户端与脚本副本，不内置脚本、不循环补造决定；输出仍受原Harness校验。它只用于合成演示，不代表live自主性。
- `RESOLVEFLOW_MODEL_MODE=live`：必须显式配置 `RESOLVEFLOW_MODEL_ENDPOINT` 和 `RESOLVEFLOW_MODEL_ID`；凭据用
  `RESOLVEFLOW_MODEL_API_KEY`。沿用工厂的timeout、输出ceiling、MCP与政策配置。启动live消费队列会调用模型，须先确认API预算。
- 未指定模式、mock缺脚本/文件不可读或畸形、live缺endpoint/model时启动拒绝。不开调查时保留原控制面与回调投递行为，不要求模型配置。

本阶段单Agent副本、进程内单调查线程；意外异常停止调查线程并记录错误，RUNNING遗留由C09恢复工作处理。
尚无生产租约/fence/崩溃恢复，不将本入口称为C09完成。操作员可通过线程状态与错误日志识别失败；现有`/health`仍仅表示HTTP进程存活。

## 8. 每小步提交并推送（2026-09-26用户授权）

执行节奏：**独立小步实现 → 针对性验证 → 更新任务记录 → 审查暂存差异 → commit → push → 确认远端 → 下一小步**。适用于功能、修复、测试与文档，不等C08/C11整包完成，也不把未通过的小步伪装成完成。纯文档跑差异/链接/一致性检查；代码跑相关测试、构建/静态检查，既有失败基线与新增失败分开披露，不删除断言或跳过钩子来提交。

1. **核对目标和工作区**：开工读`git status --short`、`git diff`、`git diff --cached`、当前分支及upstream。授权目标为既有仓库`https://github.com/Capybara0618/ResolveFlow.git`；本次确认分支`main`跟踪`origin/main`，以后每次读取实际配置，不静默更换仓库/分支。没有upstream、detached HEAD、目标变化或同文件并行编辑时先确认。
2. **核实历史积压**：本次授权不意味着把全部脏文件一次推上去。已有未提交成果先按功能和必要依赖归组、审阅并验证，分步提交；来源/边界无法确认则询问。push会携带该分支此前未推送的提交，须在fetch后检查整个待推送范围，不只看最后一个commit。不要提交包含依赖缺失的片段，也不能把依赖未提交文件才通过的工作区测试当作提交可复现的证明。
3. **精确暂存与审查**：只暂存本步清单中的文件或改动块；检查`git diff --cached --stat`、`git diff --cached`及`git diff --cached --check`。不使用全仓`git add .`/`git add -A`扫入未验证改动，不清空/夹带他人的暂存区。排除`.env`、令牌、数据库文件/快照及含敏感数据的原始日志；只提交脱敏、必要的报告。
4. **提交**：用任务号和行为描述，例如`fix(C08.2): validate proposal before callback`，代码、相关测试及本步任务记录一起提交。已有明确基线问题要披露，但本步不能新增失败。没有本步变化则不造空commit。禁止自动amend、rebase、reset或强制推送。
5. **正常推送**：检查已确认远程的实际push目标，fetch后核对分支关系；执行显式目标的普通push。本次目标示例为`git push origin HEAD:refs/heads/main`，仅在当前分支/upstream仍与上述一致时使用。成功后通过`git ls-remote origin refs/heads/main`或重新fetch核实远端包含本次SHA；若远端已前进，核实祖先包含关系，不覆盖远端。
6. **失败不隐藏**：网络短暂失败可有限重试；认证、分支保护、非快进或目标不明时保留本地commit，报告准确错误和未推送SHA，暂停新增功能直到同步问题解决。若响应不确定先核查远端，不盲目重复创建提交；不得自动force push、改变remote或绕过保护。无需为正常已授权push再次询问，但解决权限/冲突可能需要用户介入。
7. **每步交接**：报告任务号、验证结果、commit SHA、远程/分支、推送成功/失败/未确认及剩余改动。记录测试后再提交；本次SHA和push结果在交接消息中给出或下一次正常任务记录追加，不为把自身SHA写回同一提交无限递归提交。直到确认远端包含提交，才称“已同步”，本地commit不能写成“已推送”。
