# 核心版执行账本 · v1.2

2026-09-18。当前唯一实施入口。旧40个T任务已退出当前必做顺序；完整原进度/命令/报告原样保存在[历史账本](archive/v1.1-todo.md)，不是删除已完成证据。

## 已有成果（历史记录，非本轮重测）

- T00：任务记录完成，兼容与版本锁；报告见docs/compatibility-report.md及reports/t00-compatibility/。
- T01：任务记录完成，工程与命令/基础CI。
- T02：任务记录完成，4份旧OpenAPI、双语言hash/签名/fixture；2026-09-18记录all-offline 17/17，Python155、Java shared-kernel29。
- v1.2 迁移进行中：C00.1 已完成（2026-09-18，核心 profile 与允许能力清单），下一子步 C00.2；不继续旧T03，不重新执行T00。
- 本轮只修订文档；后续完成项必须填写真实记录，不能引用本表把C任务勾完成。

每个C工作包分子步实施，单子步尽量3–5核心文件；需更多时先在该任务下继续拆，不一次生成整包。命令当前/目标可用性见docs/engineering.md。

### C00 核心协议与启动范围迁移

- [x] C00.1：读取core-scope/core-contracts，建立核心协议目录与profile允许能力清单；确认旧fulfillment/补发/权益仅兼容保留。
- [x] C00.2：按消费者分批新增核心Schema/OpenAPI、Java/Pydantic DTO及正反fixture/路由覆盖；新命令/事件/方案版本与旧基线显式区分。
- [x] C00.3：调整核心启动/smoke选择，默认不要求fulfillment/Nacos/全套观测；旧协议和测试保留，服务镜像未就绪则不宣称core profile完整可用。
- 依赖：无（沿用已完成T00–T02）。文件：contracts/core、共享DTO、契约测试、infra/scripts；每子步再按协议/语言/profile拆分。
- 验收：核心禁止RESHIP/entitlement假字段；旧compat和新core测试独立通过；迁移说明列出当前可启动服务与尚未实现能力。
- 验证：pwsh -File scripts/verify.ps1 -Suite contracts；相关format/unit；Compose配置与已实现smoke，不要求未写业务的system套件。
- 实际记录：
  - C00.1 完成（2026-09-18）。修改文件：`contracts/core/profile.json`（新建：核心版允许能力清单）、`contracts/core/README.md`（新建：核心/兼容边界与现状表）、`agent/src/resolveflow/contracts/core_profile.py`（新建：加载与校验）、`agent/tests/unit/test_contracts_core_profile.py`（新建：23 个测试）。
  - 命令与结果：先写测试运行 → 预期失败 `ModuleNotFoundError: resolveflow.contracts.core_profile`；实现后 `uv run --project agent --frozen pytest agent/tests/unit/test_contracts_core_profile.py -q` → 23 passed；`ruff check agent/src agent/tests` → All checks passed；`mypy agent/src` → Success: no issues found in 17 source files；`pytest agent/tests/unit -q` → **178 passed**（T02 原有 155 + 新增 23，无回归）；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**（python-contracts-freeze 1.5s、python-contracts 9.5s、java-contracts 14.4s）。
  - 报告路径：`reports/verify/20260918-174507-contracts.txt`。
  - 关键结论：核心 profile 只授予动作 `REFUND` 与目标服务 `commerce-service`；`RESHIP` 仍在旧 `Action` 枚举中（兼容资产）但不在核心允许集合，并以 `reship` 列入 `capabilities.deferred`；`payload_hash` 的 12 个字段由测试直接与 `docs/core-contracts.md` 文本比对，profile 不能与权威文档各说一套；`entitlement_id`/`address_hash` 明确不在核心哈希字段内；旧 4 份 OpenAPI 与 5 份 Schema/fixture 有存在性测试，迁移不得静默删除。
  - C00.2a 完成（2026-09-18）。修改文件：`contracts/core/refund-command.schema.json`（新建：v2 退款命令，13 个必需属性 = 12 个哈希字段 + payload_hash）、`contracts/core/event-envelope.schema.json`（新建：v2 信封，4 种事件 + 结果 payload）、`agent/src/resolveflow/contracts/_schemaio.py`（泛化：`CORE_SCHEMA_FILES` 与 `validator_bundle/schema_registry/load_openapi/component_validator` 的 files/directory 参数，旧默认值不变）、`agent/tests/unit/test_contracts_core_schemas.py`（新建：49 个测试）、`contracts/core/README.md`（更新现状表与形状决策）。
  - 命令与结果：先跑新测试 → 3 处失败全部是测试自身写法（`quantity` 误列为未知字段、`event_type` 重复传参），修正后 `pytest agent/tests/unit/test_contracts_core_schemas.py -q` → 49 passed；`pytest agent/tests/unit -q` → **227 passed**（T02 原 155 + C00.1 的 23 + 本步 49，旧 OpenAPI 测试未受 `_schemaio` 泛化影响）；`ruff` All checks passed；`mypy agent/src` no issues in 17 files；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**（1.5s / 9.1s / 5.7s）。
  - 报告路径：`reports/verify/20260918-175954-contracts.txt`。
  - 关键结论：核心 Schema 与旧 v1 的 `$id` 互不相交且互不可解析（测试断言）；`RESHIP`、`entitlement_id`、`address_hash`、旧 topic `rf.case.v1`、`schema_version=1`、无签名的结果、浮点/负/超上限金额均被拒；命令属性集合恰好等于 `canonical.REFUND_FIELDS + payload_hash`，Schema 与哈希实现不能各自漂移；旧 v1 命令/信封的宽松行为（RESHIP 分支、条件 amount_minor、结果不签名、信封带 aggregate_*）原样保留并有测试对照。
  - 规范差异已按权威解决并记录：`docs/core-contracts.md` 第5节把 `aggregate_version` 放在结果 payload，因此 core 信封不再重复 `aggregate_id`/`aggregate_version`（旧 v1 信封保持不变）；详见 `contracts/core/README.md` 第4节。
  - C00.2b 拆为三步（b-1 commerce / b-2 agent / b-3 case），本轮完成 b-1（2026-09-18）。修改文件：`contracts/core/openapi-commerce.yaml`（新建：4 条核心路由 + LineContext/ShipmentSnapshot/LineRefundStatus/RefundOperationView 及错误体）、`agent/tests/unit/test_contracts_core_routes.py`（新建：16 个测试，含从 `docs/core-contracts.md` 第3节解析路由表并钉住每类数量）、`contracts/core/README.md`（现状表与决策 5/6）。
  - 命令与结果：`pytest agent/tests/unit/test_contracts_core_routes.py -q` → 16 passed（中途 4 次失败全为测试自身缺陷：目录写成 `core`、正则缺 `re.MULTILINE`、`/health` 不属版本化前缀、路径重复拼接 `contracts`）；`pytest agent/tests/unit -q` → **243 passed**（此前 227 + 本步 16）；`ruff` All checks passed；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**（1.5s / 8.8s / 5.5s）。
  - 报告路径：`reports/verify/20260918-180556-contracts.txt`。
  - 关键结论：核心路由表的权威是文档而非测试内的副本——测试解析 `docs/core-contracts.md` 第3节并钉住 Case 18 / Commerce 4 / Agent 5（共 27 条），再与核心 OpenAPI 的 `paths` 逐项比对；commerce 文档已确认不含 entitlement/packing/reship/cancel-before-start 任何片段，也没有 `Action` 与 `EntitlementState*` 组件，`line_refund` 状态收窄为 FREE/RESERVED/CONSUMED（compat 的 `IN_USE` 仍在旧枚举里，有对照断言）；`ShipmentSnapshot.synthetic` 为必填常量 true；文档内每个 `$ref` 均可解析，7 个示例全部通过自身组件校验；核心错误体与 compat 错误体逐字段相同（`docs/core-contracts.md:15` 要求错误体不变）。
  - C00.2b-2 完成（2026-09-18）。修改文件：`contracts/core/openapi-agent.yaml`（新建：5 条路由 + RunRequest/RunView/ObservationRecord 等组件）、`agent/tests/unit/test_contracts_core_routes.py`（改为按文档参数化，31 个测试，覆盖 commerce 与 agent 两文档）、`contracts/core/README.md`（现状表与决策 6/7/8）。
  - 命令与结果：`pytest agent/tests/unit/test_contracts_core_routes.py -q` → 31 passed（过程中 5 次失败均为真实信号或我自身缺陷：core agent 的 ApiError 描述未与 compat 逐字一致、`/health` 无业务规范可引（测试显式豁免）、ANALYZING 断言写法过宽、`domain-model.md` 正则漏 `_`、一行超 120 字符）；`pytest agent/tests/unit -q` → **258 passed**（此前 243 + 本步 15）；`ruff` All checks passed（修掉一处 E501）；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**（1.4s / 10.5s / 5.2s）。
  - 报告路径：`reports/verify/20260918-181250-contracts.txt`。
  - 关键结论（规范冲突已按权威解决，写入 README 决策 7/8）：`docs/domain-model.md:57` 明确核心退款 operation 只有 RECEIVED/IN_PROGRESS/UNKNOWN/SUCCEEDED/FAILED 五态且不启用旧 STARTING/CANCELLED 目标协议——我最初照搬 compat 的 14 态两阶段状态机是错的，已收窄为五态，并加了从该句解析状态集合的测试（compat 枚举保持不动并同时断言）。核心 agent 文档三处收窄：`requested_actions` 只有 REFUND、证据来源去掉 LINE_ENTITLEMENT/PACKING_MANIFEST（核心无可复核端点）、`RunAccepted.status` 为常量 QUEUED（ANALYZING 是 case 状态）；`/health` 显式免 token。两文档的每个 `$ref` 均可在文档内解析，全部 18 个示例通过自身组件校验，核心错误体与 compat 错误体逐字段相同。
  - C00.2b-3 完成，C00.2b 全部结束（2026-09-18）。修改文件：`contracts/core/openapi-case.yaml`（新建：18 条核心路由 + 62 个 schema 组件 + 34 个示例）、`agent/tests/unit/test_contracts_core_routes.py`（case 文档规格与 4 项 case 专属断言，45 个测试）、`contracts/core/README.md`（现状表与决策 9/10/11）。
  - 命令与结果：`pytest agent/tests/unit/test_contracts_core_routes.py -q` → 45 passed（过程中 2 次失败全为测试自身问题：登录接口本就不该要求 token、五条内部路由漏写 service token 覆盖）；`pytest agent/tests/unit -q` → **272 passed**（此前 258 + 本步 14）；`ruff` All checks passed；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**（1.6s / 18.6s / 6.2s）。
  - 报告路径：`reports/verify/20260918-182754-contracts.txt`。
  - 关键结论：核心 OpenAPI 三份文档齐备，路由逐项对应（Case 18 / Commerce 4 / Agent 5 = 27 条，数量由文档表格解析并钉住）。case 文档比 compat 少 3 条政策管理路由（`docs/core-contracts.md:53`，政策由受控脚本导入），动作词汇收窄为 REFUND 单值、`RecommendedAction` 去掉 RESHIP；新增 `CaseSnapshot.timeline`（`docs/core-scope.md:7` + `docs/domain-model.md:34` + `docs/core-contracts.md:67` 同事务要求）；回调 payload 由 compat 的自由对象改为按 kind 强类型并加 `if/then` 锚定（QUESTION 问题数上限 3）；`ProposalPayload` 与 `ProposalView` 拆分，C00.2c 需用测试守住二者一致。
  - 过程记录（诚实项）：本轮曾把 case 文档的生成委派给后台子代理，它因通读 55 KB 旧文档耗尽上下文且**未产出任何文件**；随后由我按权威文档 + 精确读取 compat 组件分段自行完成。教训已记录：大文件移植任务应先切分读取范围再委派，或直接自己做。
  - C00.2c 拆为三步（c-1 提案 Schema / c-2 核心正反 fixture 与 corpus / c-3 Java+Pydantic 核心 DTO），本轮完成 c-1（2026-09-18）。修改文件：`contracts/core/agent-proposal.schema.json`（新建，`urn:resolveflow:core:agent-proposal:v2`）、`agent/src/resolveflow/contracts/_schemaio.py`（CORE_SCHEMA_FILES 增加该文件）、`agent/tests/unit/test_contracts_core_proposal.py`（新建，44 个测试）、`agent/tests/unit/test_contracts_core_schemas.py`（核心 `$id` 钉住集合显式扩为三个）、`contracts/core/openapi-case.yaml`（ProposalPayload/ProposalView 的 suggested_amount_minor 去掉 null、EvidenceRef.source_ref 加 URL 拒绝 pattern）、`contracts/core/openapi-agent.yaml`（ObservationRecord.source_ref 同一 pattern）、`contracts/core/README.md`（现状表与决策 12/13/14）。
  - 命令与结果：`pytest agent/tests/unit/test_contracts_core_proposal.py -q` → 44 passed（过程中 6 次失败：核心三个枚举缺 `type: string` 与 OpenAPI 组件不一致（4 项）、我的比较助手把 items 组件误当属性组件（已改为解引用比较）、以及负例 `https://example.com/x` 竟被接受——见下）；`pytest agent/tests/unit -q` → **316 passed**；`ruff` All checks passed（修掉 3 处 E501）；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**（1.5s / 19.2s / 4.7s）。
  - 报告路径：`reports/verify/20260918-183736-contracts.txt`。
  - 关键结论（写入 README 决策 12/13/14）：核心提案不带 `case_id`（回调端点已按 case 定位）与 `schema_version`（版本由 `$id` 承担、该载荷不参与哈希），compat 两字段保留；测试逐个属性、逐条约束（含 `$ref` 解引用）断言提案 Schema 与 `ProposalPayload` 一致，任一侧单独加约束都会失败；`suggested_amount_minor` 三处同步去掉 `null`（缺失即表示没有建议金额）；最重要的一条：`docs/core-contracts.md:61` 说 ref 不是可请求的任意 URL，但 compat 只写了 minLength/maxLength —— **文档声称的约束并未被 Schema 强制**，负例测试把这个漏洞暴露出来后，核心三处统一加了拒绝 `https://` 的 pattern 并配负例断言。
  - 记账修正：本条记录首次写入时脚本因中文引号与 Python 字符串冲突而中止，代码提交已先推送，故本条以补记提交进入历史（不改写已推送历史）。
  - C00.2c-1 修正（权威冲突，2026-09-18/19）：上一步把核心提案的 `schema_version` 与 `case_id` 都删掉，理由是「回调端点已按 case 定位、版本由 $id 承担」。重读 `docs/core-contracts.md:9`（核心Agent方案 schema_version=2 且不允许 RESHIP，**其他字段复用旧结构**）与 `:57`（body 主体必须与 service JWT 及 Case 绑定一致）后确认这是**未经授权的收窄**：compat 提案（`contracts/agent-proposal.schema.json`，schema_version 常量 1、case_id 必填）就是那个「旧结构」，而绑定不在 body 里 Java 就没有可交叉校验的东西。两字段已加回三处（`contracts/core/agent-proposal.schema.json`、`contracts/core/openapi-case.yaml` 的 ProposalPayload/ProposalView）并同步两个示例；测试从「断言两字段不存在」改为「断言 schema_version 常量 2、case_id 必填、compat 侧仍是常量 1」，并新增 `schema_version=1`、字符串版本、`case_id` 非 UUID、payload 带 status/created_at 的负例。`contracts/core/README.md` 决策 12 整条重写并写明教训：**收窄 compat 字段必须有权威行号，否则就是自造协议**。
  - C00.2c-1a 引用行号守卫（2026-09-18/19）：新增 `agent/tests/unit/test_contracts_core_citations.py`，扫描 `contracts/**`、`agent/src/resolveflow/contracts/**`、`java/shared-kernel/.../contract/**` 里所有 `docs/X.md:N` 引用，断言文件存在且至少有 N 行。加它的直接原因是 `contracts/core/event-envelope.schema.json` 引用 `docs/domain-model.md` 第126行（该文件仅 72 行），而原有引用规则只覆盖 OpenAPI 文档、只检查「写了引用」不检查「引用指得通」。守卫上线后共揪出 **15 处**指不到的行号（1 处核心 + 14 处 compat 基线与 Python/Java 契约源码）：`docs/product-spec.md` 第46行（仅 40 行，真实权威第 25 行「Java 重算金额」）、`docs/domain-model.md` 第104/110/122/126行、`docs/engineering.md` 第98行。逐条改为真实权威：case 取消/对账 → `docs/domain-model.md:55`，旧 revision/作废方案不能授权 → `docs/domain-model.md:13`，方案不可原地改载荷 → `docs/domain-model.md:29`，provider 调用规则 → `docs/domain-model.md:51`（并注明 `IN_USE` 只是兼容超集，`docs/domain-model.md:59`），旧 wire enum 可作兼容超集 → `docs/domain-model.md:59`，JWT aud/issuer → `docs/core-contracts.md:15` + `docs/engineering.md:64`（密钥不提交），RiskRoute → `docs/product-spec.md:19`。只改描述文本与 DTO 文档串，不动任何线上形状；改动落在 `contracts/openapi-case.yaml`、`contracts/openapi-commerce.yaml`、`agent/src/resolveflow/contracts/enums.py`、`java/shared-kernel/src/main/java/com/resolveflow/shared/contract/ContractEnums.java`。
  - C00.2c-1a 附带发现（同一步）：核心信封签名不能复用 compat 的 `signing_input_bytes`——核心键集合去掉了 `aggregate_id`/`aggregate_version` 并新增 `topic`，复用会把两个不存在的成员填成 null 且漏签 `topic`。已在 `agent/src/resolveflow/contracts/events.py` 增加 `CORE_ENVELOPE_KEYS`/`CORE_SIGNABLE_KEYS`/`core_signing_input_bytes`/`sign_core_envelope`/`verify_core_envelope`（保留 `traceparent`/`causation_id` 可选成员并按 compat 规则把缺失归一化为 null），并抽出共用的 `_verify`；键集合由 c-2 的语料测试对着核心 Schema 的声明成员钉住。
  - 命令与结果（C00.2c-1 修正 + c-1a）：`pytest agent/tests/unit -q` → **350 passed, 9 skipped**；`ruff check agent/src agent/tests` → All checks passed（修掉 1 处 UP035：`Callable` 改从 `collections.abc` 导入）；`mypy agent/src/resolveflow/contracts` → Success（9 个源文件）；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**；`-Suite format` 中 python-ruff 曾失败（同 UP035），已修复，其余步骤（含 Java Spotless、web typecheck）通过。
  - 报告路径：`reports/verify/20260918-184516-contracts.txt`（修正前的失败留档：python-contracts FAIL，即 ProposalView 示例缺两个必填字段）、`reports/verify/20260919-095226-contracts.txt`（修正后 PASS）。
  - C00.2c-2a 核心正向 fixture 与 core_corpus（2026-09-19）：新增 `contracts/core/fixtures/valid.json`（7 条正向语料：1 条命令、5 个信封（四种事件类型 + 一个不带 traceparent 的对照）、2 条提案）、`contracts/core/fixtures/README.md`（结构/引用/占位符/测试密钥/为何不能复用 compat 签名函数的说明）、`agent/src/resolveflow/contracts/core_corpus.py`（节→schema 表、引用解析、占位符重算、整份语料校验）、`agent/tests/unit/test_contracts_core_corpus.py`（45 个测试）；`contracts/core/README.md` 现状表更新。
  - 命令与结果：`pytest agent/tests/unit/test_contracts_core_corpus.py -q` → **45 passed**（过程中 40 次失败逐条暴露了三个真实缺陷，见下）；`pytest agent/tests/unit -q` → **398 passed, 9 skipped**；`ruff` All checks passed（修掉 1 处 F401）；`mypy agent/src/resolveflow/contracts` → Success（10 个源文件）；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**；报告 `reports/verify/20260919-095930-contracts.txt`。
  - 三个真实缺陷（都是「看着能过、其实没有证据」那类）：一是**顶层别名被静默解析成空对象**——compat 的 `resolve_instance` 会把所有 `_` 开头键当注解丢掉，于是 `{"_ref": "components.x"}` 整条变成 `{}`，一个空 fixture 仍能通过某些校验；已在 `core_corpus` 显式支持顶层别名并加测试。二是**注解随引用进入实例**——compat 的解析器只清理条目顶层的 `_` 键，被引用组件内部的 `_comment` 会一路进入实例，而核心每个 schema 都是 `additionalProperties: false`；已改为递归清理并加测试。三是**签信封时把该信封自身的签名占位符也拿去代换**，导致 KeyError；已改为只签去掉 `signature` 的部分。
  - 另一处认知修正：测试里曾假设「RESHIP 在核心不可哈希」，实际 `canonical.payload_hash` 仍保留 compat 的补发分支（`docs/core-scope.md:34` 保留旧协议为兼容资产），所以改哈希会要求 `address_hash` 而不会静默按退款字段算。测试改写为：`action` 不是被哈希的普通值而是字段集合选择器；核心 Schema 才是拒绝补发命令的地方（action 是常量 + v1 的 `address_hash` 属未知字段），三者一次断言。
  - 语料测试覆盖的关键性质：每个核心 schema 都有正向语料（无语料的 schema 等于没有证据）；占位符「用了就要能填、填了就要有人用」；12 个字段任一改动都改变摘要、改 `payload_hash` 自身不改变摘要、浮点金额根本无法规范化；签名覆盖每个声明成员（逐字段篡改必须验不过）、覆盖可选的 `traceparent`/`causation_id` 与 payload、换密钥验不过；**核心签名输入与 compat 签名输入必须不相等**（compat 规则会给核心信封补两个 null 并漏签 `topic`）；可选成员缺失与显式 `null` 签出同一字节。
  - C00.2c-2b 核心反向语料（2026-09-19）：新增 `contracts/core/fixtures/reject.json`（51 条负例：命令 15、信封 13、提案 19、摘要输入 4；每条用 `base` 指向正向语料再给 `overrides`/`remove` 表达增量，并写明 `why` 且必须引用权威行号）、`agent/tests/unit/test_contracts_core_reject.py`（18 个测试）；`agent/src/resolveflow/contracts/core_corpus.py` 增加反向语料支持（`CORE_REJECT_TARGETS`、`resolve_core_negative_instance`、`validate_core_reject_corpus`、`validate_core_invalid_payloads`、点路径 `remove`）；两个 README 更新。
  - 命令与结果：`pytest agent/tests/unit/test_contracts_core_reject.py -q` → **18 passed**；`pytest agent/tests/unit -q` → **417 passed, 9 skipped**；`ruff` All checks passed（修掉 2 处 E501）；`mypy agent/src/resolveflow/contracts` → Success（10 个源文件）；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**；报告 `reports/verify/20260919-100456-contracts.txt`。
  - 负例测试的设计要点（写入 fixtures/README）：一是**每条理由必须引用权威行号**——没有引用的理由只是个人意见；二是**增量既必要又充分**：对每条基于正向 bas​e 的负例，测试同时断言「改过的必须被拒」且「没改的必须仍被接受」，否则一条本来就无效的负例可以永远通过却什么都没测（这条断言首次运行即通过，说明 51 条负例的 base 确实都有效，拒绝确实来自所声明的增量）；三是 `remove` 删不存在的路径当场失败，避免「本该缺少某字段」其实什么都没删；四是**摘要一节由哈希实现拒绝而非 schema**——整数金额、2^53-1 上界、摘要字段集合（补发是另一套字段）都无法用「约束摘要输入」的 schema 表达，悄悄算出一个摘要比算错更糟。
  - 负例覆盖的协议红线（节选）：补发动作/补发事件/权益事件、`entitlement_id`/`address_hash`/`schema_version` 出现在核心命令里、错 `target_service`、非 CNY、金额 0/浮点/超上界、数量 0、revision 0、摘要非十六进制、未知字段；信封 schema_version=1、RefundRequested 走错 topic、结果由 case-service 伪造、结果无签名或无 signing_key_id、信封上出现 `aggregate_id`/`aggregate_version`、结果缺 `aggregate_version`、state=IN_PROGRESS、无偏移时间戳、非 UUID event_id、畸形 traceparent；提案 RESHIP/EITHER、schema_version=1 或缺 `schema_version`/`case_id`、REFUND 无证据或无政策、REFUND 同时又索取材料、金额 null/浮点/超上界、载荷带 `status`/`created_at`、空摘要、空理由码、小写理由码、`source_ref` 是 URL、证据缺 content_hash、政策引用缺 chunk。
  - C00.2c-3a Python 核心 DTO（2026-09-19）：新增 `agent/src/resolveflow/contracts/core_models.py`（`CoreRefundCommand`/`CoreRefundResult`/`CoreEnvelope`/`CoreEvidenceRef`/`CorePolicyRef`/`CoreAgentProposal`，与 v1 `models.py` 显式区分，不继承不别名）与 `agent/tests/unit/test_contracts_core_models.py`（80 个测试）。
  - 命令与结果：`pytest agent/tests/unit/test_contracts_core_models.py -q` → **80 passed**；`pytest agent/tests/unit -q` → **498 passed, 9 skipped**；`ruff` All checks passed（修掉 1 处 E501）；`mypy agent/src/resolveflow/contracts` → Success（11 个源文件）；`pwsh -File scripts/verify.ps1 -Suite contracts` → **3/3 PASS**；报告 `reports/verify/20260919-101038-contracts.txt`。
  - DTO 与 Schema 的双向一致性作为测试来测，而不是靠人工比对：字段集合与必填集合逐字段等于 schema 的 `properties`/`required`；**正向语料全部被接受、47 条负例全部被拒绝**（DTO 是同一批线上的第二种描述，「接受 schema 拒绝的东西」是洞，「拒绝 schema 接受的东西」是墙，两种都用现成语料回放检查）。
  - 过程中查出一个真实不一致：**显式 null**。schema 里信封的 `traceparent`/`causation_id` 是 `type: string`（不带 null），提案的 `suggested_amount_minor` 同样是纯整数，只有结果载荷的 `provider_ref`/`reason_code` 是 `[string, null]`；而 Pydantic 里 `X | None = None` 会把显式 null 一起接受，于是 DTO 比 schema 宽。已把「缺席只能用省略表达，只有 schema 声明可空的成员才允许 null」做成 DTO 的显式规则（`NULLABLE_MEMBERS` + before 校验器），并加一条 `NULLABLE_MEMBERS == schema 可空属性集合` 的一致性测试；两个方向各有一条测试（信封与金额的 null 必须被拒，结果两个字段的 null 必须被接受）。
  - 另一处刻意的 DTO 加强：信封的路由与事件类型、结果事件与 payload 的 `state` 必须一致（同一个事实写了两遍，就两遍都校验，而不是信任其中一遍）；可执行方案必须引用证据与政策（schema 用 allOf/if/then 表达，DTO 用 model validator）。`source_ref` 的「不是 URL」用 Python 正则 + AfterValidator 实现，因为 Pydantic 的 `pattern=` 走 Rust regex，不支持前瞻断言。
  - 未执行：Java 侧核心 DTO 与 Java 测试（C00.2c-3a 的 Java 部分）、核心期望值冻结与跨语言一致性（C00.2c-3b）尚未开始。
  - C00.2c-3b-1 核心期望值冻结（2026-09-19）：新增 `scripts/contracts_core_freeze.py`（从 `contracts/core/fixtures/valid.json` 重算并写 `contracts/core/fixtures/expected.json`，支持 `--check`）、`contracts/core/fixtures/expected.json`、`agent/tests/unit/test_contracts_core_freeze.py`（8 个测试）；`scripts/verify.ps1` 的 contracts suite 增加 `python-core-contracts-freeze` 步骤；两个 README 更新。
  - 命令与结果：`python scripts/contracts_core_freeze.py --check` → **up to date (6 frozen values)**；`pytest agent/tests/unit/test_contracts_core_freeze.py -q` → **8 passed**；`pytest agent/tests/unit -q` → **507 passed, 9 skipped**；`ruff check agent/src agent/tests scripts` 中新脚本无告警（`scripts/contracts_freeze.py` 有 6 条既存告警：`I001`/`RUF100`，因 `scripts/` 不在 format suite 的检查路径内，未在本次改动）；`mypy` → Success；`pwsh -File scripts/verify.ps1 -Suite contracts` → **4/4 PASS**（新增步骤 0.4s）；报告 `reports/verify/20260919-101524-contracts.txt`。
  - 为什么要冻结（写入 fixtures/README）：占位符在解析时重算是为了不让**语料文件**自抄摘要，但「Python 自己算又自己对上」证明不了 Java 也这么算。`expected.json` 冻结的是**跨语言的比较点**：Java 与 Python 各自从同一份语料复现 `payload_hashes`/`signing_inputs`/`event_signatures` 并比对；文件过期则 `--check` 与 pytest 双双失败。
  - 冻结内容与证据：`placeholder_values`（6 个占位符）、`payload_hashes`/`canonical_payloads`（命令摘要与它覆盖的规范化 JSON）、`signing_inputs`/`event_signatures`（5 个信封的签名输入与签名）、`signing_keys`（测试密钥的 PKCS#8 与 SPKI DER、被签名成员列表）、`refused`（本轮的拒绝记录）。测试断言：重算值等于冻结值；签名能用核心签名输入在 Python 侧验过；签名输入字节与冻结串一致；被签名成员列表是核心的那一套（含 `topic`、不含 `aggregate_*`）；DER 私钥/公钥解回来等于语料声明的种子与公钥（Java 会用现成的 `EventSignature` 加载这两个 blob）；同一信封在 compat 规则下签的是不同字节。
  - 生成脚本过程中修掉的两个自身缺陷：一是先按 `resolve_core_instance` 的返回值去查占位符表（返回值已被替换成摘要，查表必然 KeyError），改为「token 从语料读、value 从重算表读」，这样写错 token 会直接报错而不是把自己冻结进去；二是漏了 `import sys`。
  - 未执行：Java 侧核心 DTO（records）、Java 的 core fixture 加载与跨语言摘要/签名比对测试（C00.2c-3b-2）尚未开始。
  - C00.2c-3b-2 Java 核心 record 与跨语言证据（2026-09-19）：新增 `java/shared-kernel/src/main/java/com/resolveflow/shared/core/` 下 `CoreContract.java`（6 个 record，与 Python `core_models.py` 同名同字段，与 v1 显式区分）、`CoreFixtures.java`（读同一份核心语料：节→schema 表、`payload_ref` 与顶层 `_ref` 别名、递归清理注解、按冻结表代换占位符）、`CoreEventSignature.java`（核心签名输入与 Ed25519 签/验，含被签名成员列表），以及 `src/test/java/com/resolveflow/shared/core/CoreContractTest.java`（7 个测试）。
  - 命令与结果：`mvnw -pl shared-kernel spotless:apply` → BUILD SUCCESS；`mvnw -pl shared-kernel test` → **Tests run: 36, Failures: 0**（其中核心 7 个）；`pwsh -File scripts/verify.ps1 -Suite all-offline` → **PASSED**（含 format/unit/contracts 与 smoke：5 个服务与 Python API 启动并通过健康检查）；报告 `reports/verify/20260919-101928-all-offline.txt`。
  - 跨语言证据的四条（写入 fixtures/README）：一是 record 的**线上字段名**（读 `@JsonProperty` 而非字段名）与对应 schema 的 `properties` 集合一致；二是每条正向语料能反序列化并**原样写回**——这是 Java 在没有 JSON Schema 校验器时能给的形状层证据（读入 schema 合法文档再写回若变样，Java 产出的文档就不是它 schema 接受的那份）；三是 Java 复算的 `payload_hash` 与规范化 JSON 字节等于 Python 冻结值；四是 Java 能用冻结的 SPKI 公钥验过 5 个信封签名、用 compat 验签器**验不过**（compat 给核心信封补 `aggregate_*` 并漏签 `topic`），并用冻结的 PKCS#8 私钥重签出逐字节相同的签名（Ed25519 确定性）。
  - 往返断言抓到真实缺陷：Java record 会把**缺席**的可选成员写成显式 `null`（`traceparent`/`causation_id`），而核心 schema 对它们是 `type: string` 且 `additionalProperties: false`——即 Java 作为生产者会产出自己 schema 拒绝的信封。已给三个含可选成员的 record 加 `@JsonInclude(NON_NULL)`；注意这一层不会影响 payload 内部（Map 内容的 null 仍保留，`provider_ref: null` 照常往返）。
  - 另修一处编译错误：`RecordComponent[]` 没有 `stream()`，改为普通循环。
a（契约实例）、c-1（提案 schema 与 OpenAPI 对齐）、c-2a/b（正反语料 51 条）、c-3a/3b（Python+Java DTO 与跨语言字节级一致）均已完成并推送；`verify -Suite all-offline` 在核心改动后完整通过。
  - C00.3 完成（2026-09-19）。修改文件：`scripts/verify.ps1`（新增 `-Profile core|compat`，默认 core；启动集合从 `contracts/core/profile.json` 的 `core_services`/`compat_only_services` 读出，脚本只保留「名字→jar 与端口」映射；profile 里有服务却没有启动器会当场 throw；报告里记录本次用的 profile）、`infra/compose.yaml`（Nacos 挂到 `compat` profile 后面，默认 `docker compose up -d` 不再拉起；头部注释写明两个 profile 与"观测容器将来也该有自己的 profile"）、`agent/tests/unit/test_contracts_core_startup.py`（新建，17 个测试）、`contracts/core/README.md`（新增第 5 节「启动范围与尚未实现的能力」+ 现状表两行）、`docs/implementation-handoff.md`（当前事实与「当前可启动的服务/尚未实现」两节，并把「下一项 C00」改为「C00 已完成，下一项 C01」）、`docs/engineering.md:40`（原句「旧 smoke 仍可能启动 fulfillment/Nacos」已过时，改为当前事实）。
  - 命令与结果：`pytest agent/tests/unit/test_contracts_core_startup.py -q` → **17 passed**；`pytest agent/tests/unit -q` → **524 passed, 9 skipped**；`ruff` All checks passed；`docker compose --profile compat stop nacos` 后 `pwsh -File scripts/verify.ps1 -Suite smoke`（默认 core）→ **PASSED**，启动集合 `gateway, case-service, commerce-service, agent`，报告 `reports/verify/20260919-102959-smoke.txt`；`pwsh -File scripts/verify.ps1 -Suite smoke -Profile compat` → **PASSED**，启动集合多出 `fulfillment-service`，且 `infra-up` 带 `--profile compat` 拉起了 Nacos，报告 `reports/verify/20260919-103025-smoke.txt`；`pwsh -File scripts/verify.ps1 -Suite all-offline` → **PASSED**，报告 `reports/verify/20260919-103213-all-offline.txt`。
  - 关键做法：一是**启动集合只有一个来源**——脚本从 profile 读，避免「文档说不需要、脚本里又启动一份」的漂移；二是**核心 smoke 的证据是先把 Nacos 容器停掉再跑**（不是假定服务不依赖它），四个进程照常起来并通过健康检查；三是**旧入口保留**：`-Profile compat` 才加 fulfillment 与 Nacos，旧断言一条未删（`docs/engineering.md:40` 的要求）；四是新增测试盯着「`not_required` 里的容器不得出现在默认 compose 集合里」和「profile 里每个服务都要有启动器」，因为把容器悄悄放回默认集合会让「核心不依赖它」这句话变成假的，而不需要改任何文档。
  - 事实核对：四个服务的 `application.yml` 目前只有端口与 `application.name`，没有 Nacos 发现、没有数据源配置——所以核心 smoke 不依赖 Nacos 是可验证的事实，而不是假设；`fulfillment-service` 的骨架、协议、测试原样保留，只是默认不启动。
  - 未执行：`verify -Suite all-offline` 仍未重跑（留到 C00.3）
  - 未执行：C00.3（core profile 的启动与 smoke 选择：当前 smoke 仍会拉起 fulfillment-service 与 Nacos，且启动清单尚未迁移到 core 口径）未开始。；C00.2c-2b（核心反向 fixture）、C00.2c-3（Java/Pydantic 核心 DTO）、C00.3（core profile 启动与 smoke 选择）未开始；core profile 的服务启动尚未验证。

### C01 身份与订单只读切片

- [x] C01.1：演示身份/网关与资源服务JWT，固定商家/用户/审核角色；不做完整IAM。
- [x] C01.2：Commerce订单/支付快照迁移、种子和读接口，Case公共订单视图，跨主体拒绝。
- 依赖：C00。文件：Java安全模块、Commerce订单、Case视图及测试，按纵向接口分批。
- 验收：本人能看订单，跨用户/商家不能看；金额为整数原快照，独立数据库账户不跨库读取。
- 验证：JWT/归属单元、MySQL集成与核心契约测试。
- 实际记录：
  - C01.2a 完成（2026-09-19）：**契约缺口修正**（本步先改协议，再写实现）。撞上的问题：核心路由表写着 Case `GET /api/v1/orders` 是「当前主体订单视图；内部请求Commerce」（`docs/core-contracts.md:26`），但核心 commerce 文档（compat 也一样）4 条路由全是按 `line_id`/`operation_id` 取单点事实，**没有按主体列订单行的内部路由**；订单与支付属 `commerce_db`（`docs/architecture.md:11`），Case 的 case_db 里也没有订单表或订单投影（`docs/domain-model.md` 第2节），所以这条公共路由没有合法数据来源。处理：补上缺的内部读路由而不是让 Case 越权读别人的库——`contracts/core/openapi-commerce.yaml` 新增 `GET /internal/v1/order-lines`（service token；`merchant_id` 必填、`customer_id` 可选、游标分页；200 `OrderLinePage`、403 `ForbiddenScope`），并镜像 case 文档的 `PageMeta`/`OrderLineSummary`/`OrderLinePage` 三个 Schema；`docs/core-contracts.md` 第3节新增对应行（Commerce 4 → 5、总数 27 → 28）。
  - 命令与结果：`pwsh -File scripts/verify.ps1 -Suite contracts` → **PASSED**（报告 `reports/verify/20260919-105617-contracts.txt`；其中 core 路由覆盖测试 49 passed，较 C00.2b 的 45 增加 4 个：新增路由 1 个 + 两个文档订单视图逐字一致 3 个）。测试钉住三件事：`OrderLineSummary`/`OrderLinePage`/`PageMeta` 在 case 与 commerce 文档里**逐字相同**（同一载荷两份定义必须有守卫，否则必然单边漂移）；公共 `GET /api/v1/orders` **不得**出现 `merchant_id`/`customer_id`/`scope` 参数（否则客户可指定别人的作用域）；权威句子「内部请求Commerce」仍在那份文档里（改这条路由的正当性来源）。
  - 判断依据与未越界之处：这是**指出并解决规范冲突**（AGENTS.md 要求），不是自造协议——路由表同一行已经声明了这条内部依赖，只是没有给出路由；新增只动核心文档与核心 OpenAPI，compat 基线一个字未改，旧测试未删。作用域由 Case 从已校验的用户 token 推导后传给内部调用，Commerce 只信 service token，与本项目既有的「主体来自认证上下文」一致（`docs/core-contracts.md:15`）。
  - 未执行：`LineContext` 读接口与 `line_refund` 相关读路径（属 C04/C05 的退款链）未开始；`demo_user` 的迁移/种子仍未落库（当前演示账号来自 `DemoAccounts` 种子常量，见 C01.1b 记录）。
  - C01.2c-1 完成（2026-09-19）：内部列行路由加可选 `order_id` 过滤。原因：公共 `GET /api/v1/orders/{order_id}` 需要「这一单，如果是你的」，而只靠分页碰运气在订单行跨页时是错的。文件：`contracts/core/openapi-commerce.yaml`（新参数 `OrderId` 复用 `Uuid`，并在描述里写明它是**作用域内的收窄**而不是绕过作用域）、`OrderLineRepository.java`/`OrderLineReadService.java`/`internal/OrderLineController.java`（`order_id` 与该主体条件**并列**，不替换）、`agent/tests/unit/test_contracts_core_routes.py`（路由参数钉成五个：MerchantId、CustomerId、OrderId、Cursor、Limit）、`java/commerce-service/.../OrderLineReadServiceDatabaseTest.java`（同一订单在 M-1001/C-2002 有两行、换商家或换同一商家的另一个 customer 都查不到）。命令与结果：`mvnw -pl commerce-service -am test` → commerce-service 22（原 20 + 2），0 失败 0 错误；契约测试 49 通过。
  - C01.2c-2 完成（2026-09-19）：Case 的公共订单视图。文件：`java/case-service/src/main/java/com/resolveflow/caseservice/order/CommerceOrderLineClient.java`（出站调用集中在此：**作用域只能由传入的 principal 推导**——方法签名里根本没有 merchant/customer 参数，控制器想从请求里填也无从填起；出站带的是 **service token**，用户的 bearer 绝不转发给下一个服务）、`order/RequestPrincipalResolver.java`（`Authorization` → 已验证 principal，失败 401 且不回显 token 失败的具体规则）、`order/OrderController.java`（`GET /api/v1/orders` 只收 `cursor`/`limit`，`GET /api/v1/orders/{order_id}` 在作用域内查这一单，空结果 → 404 `NOT_FOUND`，消息与「订单不存在」逐字相同，所以「别人的订单」与「不存在」不可区分）、`order/OrderReadConfiguration.java`（`RestClient.Builder` 做成 bean，测试才能绑 mock 观察真正发出的东西）、`error/ApiExceptionHandler.java`（新增 401/404/503 映射；下游不可用是 503 `retryable=true`，绝不能被读成「订单列表为空」或「订单不存在」）；`application.yml` 增加 `resolveflow.commerce.base-url`（默认 `http://127.0.0.1:8081`）。契约侧给两个订单路由补声明 `503`（复用已有的 `ServiceUnavailable` 组件；实现比文档多一个响应码就是漂移），并用新测试钉住「两条订单路由都声明 503、列表有 401、单笔只有 404、公共列表参数只有 Cursor/Limit」。
  - C01.2c-2 测试：`order/CommerceOrderLineClientTest.java`（6，用 `MockRestServiceServer` 断言**发出去的 URL 与头**：顾客 token → merchant_id=M-1001 且 customer_id=C-2002、评审只有 merchant_id、单笔读保留作用域再加 order_id、下游 500 抛 `CommerceUnavailableException` 而不是空页、公共 payload 的成员名与 `paid_at` 格式对齐核心契约）；`order/OrderApiTest.java`（7，真 HTTP + 打桩下游：查询串里写 merchant_id=M-1002&customer_id=C-2004&scope=all **完全不被读取**、评审不带 customer 作用域、不可见订单 404、可见订单 200、无 token 401 且下游**一次都没被调用**、下游故障 503 retryable=true、登录路由不受影响）。
  - **真实跨服务端到端验证**（不是 mock）：`java -jar` 同时起 commerce-service(8081) 与 case-service(8083)，compose 的 `mysql` 容器为真库。证据：登录取 demo-customer token 后 `GET /api/v1/orders` → 200，真实返回 ...aa 的 7002/7001 两行（line_paid_amount 1999/2599、paid_at 2026-09-10T08:15:00Z）；同一请求加上 `?merchant_id=M-1002&customer_id=C-2004` → **逐字相同**的响应（请求里的作用域没被读）；`GET /api/v1/orders/...aa` → 200 两行；`GET /api/v1/orders/...cc`（M-1002 的订单）→ **404**，与请求不存在的 `...ff` **响应逐字相同**；demo-customer-m2 的列表只有 ...cc/7201，它请求 ...aa → 404；demo-reviewer（M-1001）列表 3 行（整个商家）；用户 token 直接打 Commerce 内部路由 → **403 FORBIDDEN_SCOPE**，不带 token → **401 UNAUTHENTICATED**；不带 token 打公共路由 → 401。
  - C01.2c 命令与结果汇总：`mvnw -pl case-service -am test` → shared-kernel 55 + case-service 23（登录 8、订单客户端 6、订单 API 7、应用 2），0 失败 0 错误；`-Suite contracts` → **PASSED**（50 个契约测试，报告 `reports/verify/20260919-113548-contracts.txt`）；`-Suite unit` → **PASSED**（`reports/verify/20260919-113619-unit.txt`）；`-Suite smoke`（core）→ **PASSED**（`reports/verify/20260919-113750-smoke.txt`）。
  - 一次失败仍是断言方式而非实现缺陷：想表达「不带 customer_id」时写了 queryParam 且期望 null，那其实是「参数存在且为 null」；改成用 requestTo(精确 URI) 断言，因为精确 URI 本身就说明该参数根本没发。
  - **C01.2 验收已达成**：本人能看订单（A/E 与单测），跨用户/商家看别人的订单一律 404 且与不存在不可区分（C2/D2 与单测），作用域只来自已校验 token（B1 与单测），内部读接口只认 service token（F1/F2）。演示账号仍来自 `DemoAccounts` 常量而非 `demo_user` 表，这条留给后续（README/交接文档已标注），不影响本验收。
  - C01.2b-2 完成（2026-09-19）：内部路由的 HTTP 层与 service token 边界。文件：`java/commerce-service/src/main/java/com/resolveflow/commerce/internal/ServiceTokenFilter.java`（只拦 `/internal/**`；缺 token/坏 token 401 `UNAUTHENTICATED`，**有效用户 token 403 `FORBIDDEN_SCOPE`**——它是真 token，只是不是服务 token；失败直接写统一错误体，因为过滤器在 MVC 之前，够不到异常处理器）、`internal/OrderLineController.java`（`GET /internal/v1/order-lines`，出参逐字对齐核心 OpenAPI：snake_case、`line_paid_amount`、`paid_at` 带 Z、`next_cursor` 无下一页时**缺席**而不是 null；同文件里的 `InternalSecurityConfiguration` 提供内部面自己的 `JwtCodec`）、`error/ApiExceptionHandler.java`（缺 `merchant_id`/类型错/坏游标/未知字段一律 400 `INVALID_ARGUMENT`，坏游标消息是「cursor was not issued by this service」）；`application.yml` 增加内部面签名密钥（与 case-service 同值，边界靠 `aud` 而不是靠密钥不同）。测试 `internal/OrderLineControllerTest.java`（6：文档形状与 UTC 时间戳、商家作用域不外溢、游标翻页、无 token 401 / 用户 token 403、缺参/坏游标/limit 越界 400、`/actuator/health` 无需 token）、`CrossSchemaPrivilegeTest.java`（3）。
  - 跨库权限的真正证明：`CrossSchemaPrivilegeTest` 把 **compose 真正挂载的** `infra/mysql/init/01-databases.sql` 原样应用到测试容器（`copyFileToContainer` + `mysql -uroot <`，脚本不存在就失败），再以 `commerce`/`case_svc` 两个真实账号连库断言：`commerce` 能读 `commerce_db.order_line`、读 `case_db` 里**故意由 root 建好**的探测表被拒（denied，而不是「表不存在」）；反向同理；`SHOW GRANTS FOR CURRENT_USER()` 只含自己的 schema。这就是「一台 MySQL 承载多个 schema 不等于共享数据权限」的可复核证据。
  - 命令与结果：`java\mvnw.cmd -f java/pom.xml -B -ntp -pl commerce-service -am test` → **shared-kernel 55 + commerce-service 20（应用 2、跨库权限 3、内部路由 6、读模型 9），0 失败 0 错误**；`pwsh -File scripts/verify.ps1 -Suite unit` → **PASSED**（java-unit 47s、python-unit 24.4s、web-test 23.2s，报告 `reports/verify/20260919-112228-unit.txt`）；`-Suite smoke`（默认 core）→ **PASSED**（报告 `reports/verify/20260919-112403-smoke.txt`，启动集合仍是 gateway/case-service/commerce-service/agent）。
  - 迁移在真实 compose MySQL 上生效的独立证据：`docker exec resolveflow-mysql-1 mysql -uroot -proot -e "SELECT installed_rank, version, description, success FROM commerce_db.flyway_schema_history"` → rank 1 `commerce order read model` success=1、rank 2 `demo order seed` success=1；`order_line` 4 行、`payment_ledger` 3 行、`case_db` 表数 0（case 侧尚未建表，符合 C02 才动的计划）。
  - 一次失败是事实性差异而非缺陷：`next_cursor` 为 null 时被 Jackson 省略（`NON_NULL`），而测试原本断言成员存在且为 null。按项目既有规则「同一个事实只有一种表示」保留省略，测试改为断言成员缺席；核心 Schema 里 `next_cursor` 仍是 `[string, "null"]`（compat 基线形状不动），两者不矛盾。
  - C01.2 尚未完成的部分：验收里的「本人能看订单，跨用户/商家不能看」目前只在 Commerce 内部路由这一层被证明（HTTP 测试里 6 条覆盖了作用域），**公共 `GET /api/v1/orders` 还不存在**，所以 C01.2 的验收整体尚未达成，不能勾选。
  - C01.2b-1 完成（2026-09-19）：commerce_db 读模型（迁移 + 种子 + 读服务 + 真实 MySQL 集成测试）。文件：`java/commerce-service/src/main/resources/db/migration/V1__commerce_order_read_model.sql`（`orders`/`order_line`/`payment_ledger`，列与约束按 `docs/domain-model.md:40-41`；金额整数分、时间 UTC DATETIME(6)；`chk_payment_ledger_within_paid` 把「已退+预留 ≤ 支付额」`docs/product-spec.md:13` 落到库上；`idx_order_line_scope` 与列表查询的 keyset 顺序一致）、`V2__demo_order_seed.sql`（两个合成商家：M-1001/C-2002 两行、M-1001/C-2003、M-1002/C-2004；第一条订单与行的值与核心 OpenAPI 的 `LineContext` 示例逐字一致，所以契约里的示例是库里真实存在的行）、`order/OrderLineRow.java`、`OrderLineRepository.java`（MyBatis `@Mapper`，**每个查询都带 merchant 作用域**，`limit+1` 判断是否还有下一页）、`OrderLineCursor.java`（不透明 keyset 游标，自带 `paid_at:line_id`，坏游标抛 `InvalidCursorException`）、`OrderLineReadService.java`；测试 `CommerceDatabaseTest.java`（Testcontainers 2.0.5 的 `org.testcontainers.mysql.MySQLContainer` + mysql:8.4，与 compose 同镜像同库名同账号）、`order/OrderLineReadServiceDatabaseTest.java`（9 个）、`CommerceServiceApplicationTest` 改为继承前者（上下文现在真的需要一个库）。
  - 命令与结果：`java\mvnw.cmd -f java/pom.xml -B -ntp -pl commerce-service -am test` → **shared-kernel 55 + commerce-service 11（9 个 DB 测试 + 2 个应用测试），Failures: 0, Errors: 0**；官方入口 `pwsh -File scripts/verify.ps1 -Suite unit` → **PASSED**（java-unit 84.8s、python-unit 49.6s、web-test 41s，报告 `reports/verify/20260919-111205-unit.txt`）。
  - 过程中两次失败都不是读模型缺陷：一是断言类型错了——MySQL 把 CHECK 违约报成 SQLState HY000/3819，Spring **不会**翻译成 `DataIntegrityViolationException`，改成 `DataAccessException` + 约束名（这个坑对 C05 有意义：退款路径若依赖该约束，就得处理未翻译的 `DataAccessException`，已写进测试注释）；二是编辑脚本又按 LF 匹配被 spotless 重排过的 CRLF 文件，改为先读真实文本再用 `edit` 改。
  - 性能与成本如实记录：DB 集成测试随 `-Suite unit` 一起跑，java-unit 因此从 32s 涨到 85s。最初用 `@Container` + 静态字段，两个测试类各启一次 MySQL（~90s）；改为静态块里显式 `start()` 单例容器后，第二个类降到 1.4s。容器与 compose 用同一 `mysql:8.4` 镜像，由 Ryuk 回收。
  - 尚未实现（不要读成已实现）：HTTP 路由与 service token 校验未接；`line_refund`、`refund_operation`、`shipment_snapshot`/`shipment_event`、inbox/outbox 等表按 `docs/domain-model.md:42-45` 属 C04/C05，本迁移**未**提前建表；`LineContext` 读接口也未实现。
  - C01.1a 完成（2026-09-19）：shared-kernel 演示身份。新增 `java/shared-kernel/src/main/java/com/resolveflow/shared/security/`：`Role.java`（CUSTOMER/REVIEWER/OPERATOR，`docs/product-spec.md:9`）、`AuthenticatedPrincipal.java`（record 构造器直接拒绝「REVIEWER 带 customer_id」与「CUSTOMER 无 customer_id」，无效主体无法存在）、`JwtCodec.java`（HS256；`aud` 分离用户面/服务面；算法固定、不读 token 自带的 `alg`；exp/nbf/必需 claim 逐条校验；`Authorization: Bearer` 解析；失败一律带明确原因的 `TokenException`）、`DemoAccounts.java`（6 个种子账号：M-1001 有 demo-customer/demo-customer-2/demo-reviewer，M-1002 有 demo-customer-m2/demo-reviewer-m2，另有本地 demo-operator；只存 PBKDF2-SHA256 哈希，未知账号同样走一次派生以免用时间泄露用户名）；测试 `JwtCodecTest.java`（12）、`DemoAccountsTest.java`（7）。
  - C01.1b 完成（2026-09-19）：case-service 登录端点。新增 `java/case-service/src/main/java/com/resolveflow/caseservice/auth/`：`LoginRequest.java`（长度按核心 OpenAPI 1..120/1..200，空值算 400 不算 401）、`LoginResponse.java`（snake_case，`customer_id` 仅在客户账号出现）、`AuthController.java`（`POST /api/v1/auth/login`，无 merchant/role 参数，主体只来自账号）、`IdentityConfiguration.java`（`JwtCodec`/`DemoAccounts`/`Clock` bean，密钥走配置而不是源码常量），以及 `error/ApiExceptionHandler.java`（统一错误体；401 单一消息防用户名枚举；400 含未知字段；`trace_id` 取 `X-Request-Id` 否则生成）；`case-service/src/main/resources/application.yml` 打开 `spring.jackson.deserialization.fail-on-unknown-properties`（核心 Schema 全是 `additionalProperties: false`，Boot 默认却是忽略未知字段，因此这条由契约决定）；测试 `AuthControllerTest.java`（7）。
  - 命令与结果：C01.1a 先写测试后实现，首跑为编译失败（`JwtCodec`/`AuthenticatedPrincipal`/`Role`/`DemoAccounts` 不存在）即本步的红；实现后 `java\mvnw.cmd -f java/pom.xml -B -ntp -pl shared-kernel test` → **Tests run: 55, Failures: 0, Errors: 0**。C01.1b：`java\mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am test` → **shared-kernel 55 + case-service 9（AuthControllerTest 7、CaseServiceApplicationTest 2），Failures: 0, Errors: 0**。整套入口：`pwsh -File scripts/verify.ps1 -Suite format` → **PASSED**（报告 `reports/verify/20260919-104541-format.txt`），`-Suite unit` → **PASSED**（java-unit 40.9s、python-unit 21.9s，报告 `reports/verify/20260919-104551-unit.txt`）。
  - 过程中三次失败都不是实现缺陷：`foreignKeyIsRefused` 用了 14 字符的外部密钥，先撞上 codec 的「密钥至少 16 字符」前置校验；`roleAndCustomerMustAgree` 原本期望 codec 抛 `TokenException`，实际由 `AuthenticatedPrincipal` 构造器拒绝——按事实改写为「一致性由 record 保证，同时保留 token 级校验」，并补了两条用 `signRaw` 伪造 claim 的负例；`issuedTokenVerifiesAsAUserToken` 用测试自己写的密钥去验服务签发的 token，改为注入容器里装配好的 `JwtCodec` bean（否则服务换了密钥这条测试还会绿）。另有一次编辑脚本失败：该测试文件是 CRLF，按 LF 匹配必然 0 处——脚本改为按文件实际换行符构造匹配串。
  - 提交拆分的失误（如实记录）：C01.1b 的红测试 `AuthControllerTest.java` 被 `git add -A` 一起并进了 C01.1a 的提交 `5b303df`，于是该提交里的 case-service Java 测试是红的（端点还没实现，且其中一条口令写成了 `demo-pass-1001`）。不重写已推送历史，改为让 C01.1b 紧随其后落地：本步提交同时修正口令为 `demo-pass-1003` 并让测试转绿；此后 `git add` 要按路径而不是 `-A`，别把下一步的红测试捎带进去。
  - 安全边界（明写的「没做」）：无 JWKS、无密钥轮换、无 RS256、无 refresh、无吊销列表；演示密钥与演示口令均为非机密材料，`application.yml` 里的默认签名密钥只是让 core profile 可跑可解释，真实部署必须覆盖。
  - C01.1c 完成（2026-09-19）：网关身份头卫生。新增 `java/gateway/src/main/java/com/resolveflow/gateway/security/IdentityHeaderStripFilter.java`（WebFlux `WebFilter`，最高优先级，剥离 `X-User`/`X-Role`/`X-Merchant`/`X-Customer`）与 `IdentityHeaderStripFilterTest.java`（3 个）。做在 WebFilter 层而不是 Gateway 的 `GlobalFilter`：网关目前没有路由，没有路由时 GlobalFilter 根本不会跑，只在有路由时才成立的规则不能算已实现。同时给 `AuthControllerTest` 加了一条反证 `identityHeadersAreNeverTrusted`：请求带上**另一个商家**的 `X-Merchant`/`X-Role`/`X-Customer` 去登录，返回的仍是 `M-1001`/`C-2002`/`CUSTOMER`——即绕过网关直连服务也伪造不了身份，网关剥离只是卫生而不是安全边界。
  - 命令与结果：`java\mvnw.cmd -f java/pom.xml -B -ntp -pl gateway,case-service -am test` → gateway 5（过滤 3 + 应用 2）、case-service 10（AuthControllerTest 8 + 应用 2）、shared-kernel 55，全部 0 失败 0 错误；`pwsh -File scripts/verify.ps1 -Suite unit` → **PASSED**（java-unit 32.2s、python-unit 24.2s、web-test 3.3s，报告 `reports/verify/20260919-105005-unit.txt`）。
  - 又一次编译失败是测试自身问题：`MockServerHttpRequest.get(URI)` 在该版本只有 `get(String)` 重载；spotless 重排过该文件，所以按 LF 匹配的编辑脚本再次 0 处命中，改为先读文件确认实际文本再改。
  - C01.1 完成判据：演示身份可登录、token 携带主体且服务只认 token、网关不转发客户端自称的身份、旧协议与旧测试未动（compat 基线无改动）。

### C02 建单、材料与版本

- [x] C02.1：建单/幂等/同line活跃slot、状态与查询（C02.1a 建单 + C02.1b 查询）。
- [x] C02.2：补充证据增revision（C02.2a）、消费前取消（C02.2b）、timeline和权限、SSE读接口（C02.2c）。
  - C02.2b 完成（2026-09-19）：`POST /api/v1/cases/{case_id}/cancel` 消费前取消 + **终态释放活跃 slot**。
  - 契约缺口修正：该路由只声明 `200/404/409`，**缺 `401`**（作用域来自 token）；并把「取消是终态、终态释放该行的活跃 slot（`docs/domain-model.md:26`）、不可重复取消（第二次 409 而不是假装又取消了一次）、可见者皆可取消（客户或拥有该行的商家）、看不到的工单 404 而非 403」写进路由描述。契约测试 54 通过（新增：取消路由声明 401/404/409、描述里必须提到释放该行、`ReasonRequest.reason` 必填且 minLength=1）。
  - 代码：`CaseCancellationService`（一个事务内：锁 case 行 → 校验可见性/可取消 → **条件更新** → 释放 slot → 写 `CASE_CLOSED` 轨迹）、`CaseCancelResponse`、`ReasonRequest`、`CaseController` 取消路由、`CaseRepository.markCancelled`/`releaseActiveSlot`、`CaseStateConflictException`（从 `CaseEvidenceService` 里提出来成为独立类型，因为现在是两个服务共用的「该状态不允许此变更」）。
  - 两处「两条规则落在一个动作上」的取舍：① `markCancelled` 把**期望状态写进 UPDATE 的 WHERE**，所以「两个取消同时到达不可能都成功」是数据库的条件写，而不只是上面的检查；② 状态更新与 slot 释放**同事务**——已取消却仍占着行会让该行以后永远拒绝；释放了却还活着的行会同时存在两个活跃 case。
  - 「终态释放」用唯一有意义的方式断言：取消后**对同一行重新建单**（HTTP 201、新 case_id、slot 恰好 1 条）。
  - 测试 `casefile/CaseCancelApiTest.java`（8）：200 成员集合与契约一致 + status/version + **input_revision 不变**（取消不是新输入）+ slot 归零 + 轨迹 `CASE_CLOSED` 且 detail 含 CANCELLED/cancelled_by + 读回视图 summary；**同一行可再次建单**；再次取消 409 且 version 与 `CASE_CLOSED` 轨迹条目都没动；`EXECUTING` 下 409 且**没有释放 slot**；别人的客户/别的商家/不存在的工单 404、无 token 401、且这些尝试都没改动 case；reason 空白/缺失/超 500 字 422；取消后追加材料 409；**并发 2 个取消恰好一个成功**、version 只 +1、`CASE_CLOSED` 只有一条。
  - 命令与结果：`mvnw -pl case-service -am test` → shared-kernel 55 + case-service **54**，0 失败 0 错误；`-Suite contracts` **PASSED**（`reports/verify/20260919-132350-contracts.txt`）；`-Suite unit` **PASSED**（`reports/verify/20260919-132320-unit.txt` 的后续 `-132422`）；`-Suite smoke`（core）**PASSED**（`reports/verify/20260919-132554-smoke.txt`）。
  - **真实端到端**（两个 jar + compose 真 MySQL）：对前几步建的工单取消 → 200 `{CANCELLED, version:3}`；再次取消 → 409；**对已取消工单补材料 → 409 且文案为「already ended as CANCELLED」**；随后对同一行（7001）重新建单 → **201 新 case_id**；再取消新单 → 200；库内三条 case 中两条 CANCELLED、`active_case_slot` 只剩仍为 QUEUED 的那条（7002）——终态释放与活跃占用同时成立。
  - 一次**我自己制造的错误被真实验证抓到**：第一次写这个端到端时 PowerShell 给 `Invoke-WebRequest` 传了两次 `-Headers`，reopen 请求**根本没发出去**，`$new` 为 null 而我把这当成「验过了」。重跑时才发出真正的请求并拿到 201。同一轮里还暴露出**码对但话在说谎**：给已取消工单补材料返回的 409 文案是「this case is already executing」（它明明是 CANCELLED）。原因是终态与已消费共用了一条消息；已按状态分开（终态→「already ended as X」，执行中→「already executing」），并让两个测试**断言文案**（含 `doesNotContain("executing")`）而不只断言 code。
  - C02.2c 完成（2026-09-19）：`GET /api/v1/cases/{case_id}/events` SSE 轨迹流。C02.2 全部完成。
  - 契约缺口与**示例造假**各一处：该路由只声明 `200/404`，**缺 `401`**；而它的 200 示例写的是 `event: case.updated` + `id: t-4` + 一个自造的 data 形状——契约的 `TimelineEventType` 里根本没有 `case.updated`，示例在教客户端一个工单视图永远不会返回的名字。示例改成真实词表（`event: CASE_CREATED`、id 为事件 UUID、data 就是工单视图的 `TimelineEvent` 对象），并把「先重放后推送、frame 语义、未知 Last-Event-ID 从头重放并用注释说明、注释永不是事件、终态收流、预流拒绝是 JSON」写进描述。契约测试 56 通过，新增两条：① SSE 示例里的 `event:` 必须是 `TimelineEventType` 成员且 data 必须含 `event_id`/`occurred_at`；② **跨三个文档**断言没有任何路由把凭据类参数放在 query（`docs/core-contracts.md:32`：URL 会进日志与 referrer）。
  - 代码：`CaseEventStreamService`（订阅者一个 `Stream`：首次 tick 重放、之后轮询，同一条 `sequence > cursor` 读既做重放又做轮询，所以重放不是一条可能和实时路径不一致的特殊逻辑；1s 轮询、15s 心跳注释、10 分钟上限；`Last-Event-ID` 未知则 `cursor=0` 并发一条注释）、`CaseTrajectoryReader`（**状态与轨迹在同一事务快照里读**，见下）、`TimelineEventView`（工单视图与事件流共用同一个映射，删掉了 `CaseSnapshotResponse` 里重复的嵌套记录）、`CaseRepository.findTimelineAfter`/`findSequenceByEventId`、`CaseController` 路由（**故意不写 `produces`**，理由见下）。
  - **实现里的真 bug（被测试抓到）**：最初状态与轨迹是两次独立读。撤销把状态与闭合事件**一起**提交，于是某一 tick 更早的轨迹读还在旧快照、之后的状态读已看到 `CANCELLED` → 流在闭合事件发出前就 `complete()`，订阅者最后收到的是材料追加，工单就这么「停」了。修法是把两次读放进**同一事务快照**（`CaseTrajectoryReader`，`@Transactional(readOnly = true)`；为跨代理边界才单独成类），此后一个 tick 要么看到活着的工单、要么看到终态**及解释它的事件**，不会只见其一。这条 bug 是「实时投递」测试抓到的——只测重放的测试永远看不到它。
  - **预流拒绝的渲染问题（真实环境实测才发现）**：SSE 客户端会发 `Accept: text/event-stream`，而错误体是 JSON，协商失败会把拒绝变成 **500**（不是 401）。第一次跑 SSE 测试就是 500。修法：`ApiExceptionHandler` 新增一个 `error(...)` 助手，**给每个错误体显式设置 `MediaType.APPLICATION_JSON`**（15 处调用点统一改写）——错误不是一种表示选择，因此不参与协商；一个读不懂自己拒绝原因的流式客户端比换个 content type 更糟。
  - **测试清理顺序集中到基类**：`case_evidence` 对 `aftersale_case` 有外键，加表后所有「删父表」的测试开始失败（7 个 error）。与其在每个测试里补一行，改为 `CaseDatabaseTest.deleteAllCaseData(jdbc)` 一处持有外键顺序并说明理由（C03 还会加子表，届时只需一处学习）。
  - 测试 `casefile/CaseEventStreamApiTest.java`（5）：终态工单重放三帧且**顺序**正确、data 成员集合与契约一致；`Last-Event-ID` 指向已见事件则该事件不再发送、其后的事件都发送；未知 id → 从头重放且带 `unknown Last-Event-ID` 注释；**先订阅再从另一线程改工单** → 订阅者收到 `CASE_CREATED`、后来的 `EVIDENCE_APPENDED` 与 `CASE_CLOSED`（只测重放的测试会漏掉这条）；无 token 401（JSON）、别的客户/别的商家/不存在的工单 404，全部在流开始前。
  - 命令与结果：`mvnw -pl case-service -am test` → shared-kernel 55 + case-service **59**，0 失败 0 错误；`-Suite contracts` **PASSED**（56，`reports/verify/20260919-133803-contracts.txt`）；`-Suite unit` **PASSED**（`reports/verify/20260919-133832-unit.txt`）；`-Suite smoke`（core）**PASSED**（`reports/verify/20260919-134004-smoke.txt`）。
  - **真实端到端**（两个 jar + compose 真 MySQL，curl -N）：① 订阅终态工单 → `content-type: text/event-stream`，重放三帧（id/event/data 齐全）后自行收流；② `Accept: text/event-stream` 且无 token → **401 JSON 错误体**、别的客户 → 404 JSON（修复前的 500 已不复现）；③ 未知 `Last-Event-ID` → 先输出 `:unknown Last-Event-ID; replaying from the beginning` 再重放三帧；④ **实时投递**：先 `curl -N` 开流（header 经 `--config` 传入，避免引号被拆），3 秒后追加材料、再 2 秒后取消，订阅者依次收到 `CASE_CREATED`、`EVIDENCE_APPENDED`（开流之后才发生）、`CASE_CLOSED`（summary「工单已取消」），随后流自动结束。
  - 两次**我自己造成的验证失误**（如实记录）：第一次实时投递的 curl 用了 `Start-Process -H "Authorization: Bearer ..."`，参数里的空格被拆开导致收到 401——我差点把「实时投递没验成」记成通过；第二次换行时踩到「真实 404」（7003 不在种子客户的订单里，这也是正确行为），再换到被占用的 7002 又得到 `CASE_ALREADY_OPEN`（顺带证明单活跃 case 规则在真库跨进程成立）。第三次才对上，并且这次把 header 写进 curl 配置文件。
  - C03.1a 完成（2026-09-19）：合成政策 bundle 受控导入 + 不可变版本 + 只读面 `GET /internal/v1/policies/{bundle_id}`（schema_version 无关，走 service token）。
  - 政策原件放 `fixtures/policies/bundles/`（2026.08 三条规则、2026.09 五条规则，两版真的不同，否则「按支付时间选版本」没有可验证的新旧差），生效区间 2026.08 与 2026.09 不重叠、后者开放。README 里 T01/T07 的占位说明改成实际约定。
  - 导入是**受控命令**而非 HTTP：`java -jar case-service.jar --spring.main.web-application-type=none --resolveflow.policy.import-dir=fixtures/policies/bundles`，`@ConditionalOnProperty` 保证普通启动绝不改政策（否则政策会变成「部署的函数」）。拒绝时进程退出码 1，所以流水线里不会被当成成功。
  - 三条让「不可变版本」有意义的规则，各有测试：① **hash 由内容算出、不读文件里的 hash**（文件自带 hash 就能声称一套、装着另一套；而这个 hash 是以后证明「当初生效的规则就是被引用的规则」的依据）；② **同内容重复导入是跳过而非第二版**（重新部署后再跑一次是正常操作）；③ **同 bundle_id 换内容被拒绝**，报出旧 hash 与新 hash，并保持存储行不变。manifest_hash = 规范化 JSON（bundle_id/version/safety_epoch/窗口/按序规则）的 SHA-256，不含文件路径（同一 bundle 复制到别处仍是同一 bundle）。
  - 窗口**不得重叠**（选择必须唯一），**允许有空隙**（政策发布前的支付就是没有政策，必须显式处理，不能悄悄借用最近的版本）。校验另含：未知成员拒绝（拼错的成员被忽略＝bundle 的规则比作者以为的少，而规则正是退款决定的引用依据）、同 bundle 内 rule_id 重复、空规则集、`effective_to <= effective_from`、非 `Z` 结尾的瞬时（拒绝而不是归一化：窗口必须与作者写下的一致）；规则数上限 200、position 保序（读取按 position，正文按作者写的顺序返回）。
  - 契约缺口：`GET /internal/v1/policies/{bundle_id}` 只声明 200/404，而 `/internal/**` 过滤器在处理器之前就会用 **401**（无/坏令牌）和 **403**（合法**用户**令牌）拒绝。补上后顺手加了一条**覆盖全部内部路由**的契约测试——结果发现 **16 处**内部路由都没声明这两个拒绝（含已实现的 commerce `GET /internal/v1/order-lines`），三个文档都补了，commerce/agent 文档还缺 `Unauthenticated` 响应组件（一并补）。契约测试 56 → **58**。
  - **真实代码 bug（测试抓到）**：路由最初直接返回领域记录 `PolicyRule`，于是响应里出现 `ruleId` 而不是 `rule_id`——**契约形状与实际输出不一致**，而契约测试当时还没覆盖这条 200 示例。修法：控制器有自己的响应记录 `Rule`（`@JsonProperty("rule_id")`）并按「一个事实一种表示」映射，领域记录不再兼任线协议。
  - **MySQL 拒绝把不可变性做成触发器**：应用账户在开启 binlog 时没有 SUPER 权限，`CREATE TRIGGER` 报 1419（"You do not have the SUPER privilege and binary logging is enabled"），迁移因此失败并留下 `policy_bundle`/`policy_rule` 半成品与一条失败 history 记录。**迁移只在特权账户下能通过，比没有触发器更糟**——它在本机通过、在下一台机器失败。于是改成：mapper 里没有 UPDATE/DELETE（只有 insert 与 select），并由 `PolicyMutationGuardTest` **读 mapper 自己的注解**断言这一点（比全局搜「UPDATE」字样更精确：这张表只有一个写入者，而它只插入）。删除整版仍允许：那是破坏性的且可见，而 case 会钉住它做决定时的 hash，事后用重新导入的版本核对引用会明确失败，而不是悄悄匹配错正文。
  - **我自己造成的两次验证失误**（如实记录）：① 修复 compose 上那条失败迁移时，我先用 `Add-Content` 拼接改动版政策，把 YAML 写坏了，导入以「语法错误」被拒——那是我的文件写错，不是不可变性生效，重做后才拿到真正的「同 bundle_id 换内容被拒绝」；② `CaseServiceApplicationTest`（T01 的启动验收）**不继承 `CaseDatabaseTest`**，所以它连的是 compose 真 MySQL，我这次 `mvn test` 因此把 compose 的 `case_db` 迁移到一半。已按 Flyway 的提示修复（丢弃半成品表 + 删掉失败 history 行，未清库、未删卷），但这种「跑单元测试会写开发库」的行为本身是个隐患，记在下面待处理。
  - 测试：`policy/PolicyImportTest`（5）、`policy/PolicyApiTest`（4）、`policy/PolicyMutationGuardTest`（2）。命令与结果：`mvnw -pl case-service -am test` → shared-kernel 55 + case-service **70**（0 失败 0 错误）；`-Suite format` **PASSED**（`reports/verify/20260919-141501-format.txt`）、`-Suite contracts` **PASSED**（58，`…-141148-contracts.txt`）、`-Suite unit` **PASSED**（`…-141218-unit.txt`）、`-Suite smoke`（core）**PASSED**（`…-141359-smoke.txt`）。
  - 格式套件发现 **C01.2 遗留的真实违规**：`OrderLineReadService.list(...)` 一行超长未格式化，说明 C02.2c 那次只跑了 contracts/unit/smoke、没跑 format（该次记录也只声称了这三项）。已 `spotless:apply` 修好（纯换行，无语义变化）。
  - **真实端到端**（compose 真 MySQL + 打包后的 jar）：① 受控导入 `imported 2 [2026.08 (3 rules, 20a178a4…), 2026.09 (5 rules, 2fe077a7…)]`，退出码 0；再跑一次 `imported 0, skipped 2` 且规则数不翻倍（幂等）；② 同 bundle_id 改一条规则正文 → 退出码 1，报出旧/新 hash，存储行 hash 与规则数不变；③ 窗口与 2026.08 重叠的新 bundle → 退出码 1「would not be unique」；④ 起服务后用真实 service token 读 → 200，成员恰为 `bundle_id,version,manifest_hash,safety_epoch,rules`，hash 与库里一致，5 条规则按源序，中文正文完整；⑤ 无令牌 → 401 `UNAUTHENTICATED`（`application/json`）、**用户令牌** → 403 `FORBIDDEN_SCOPE`「this route requires a service token, not a user token」、未知 bundle → 404 `NOT_FOUND`。
  - **已知缺口（未做，未声称）**：服务令牌目前只校验 `aud`/`sub`，**没有 scope claim**，因此也没有任何路由做最小权限校验（契约 `serviceToken` 的说明提到 scope）。留到 C06/C07 真正给 Agent 签发工具令牌时统一处理，避免现在先造一套没人用的 scope 词表。另一条：`CaseServiceApplicationTest` 会连 compose 真库跑 Flyway（T01 遗留），待评估是否改为继承 `CaseDatabaseTest`。
- 依赖：C01。文件：Case domain/application/api/migration/tests；逐行为交付。
- 验收：同key换body409、同line不并发建多个活跃case；材料不覆盖，旧revision不可写。
- 验证：数据库并发建单、状态转换与材料权限测试。
  - C02.1a 完成（2026-09-19）：`POST /api/v1/cases` 的建单、幂等与同 line 单活跃 case。
  - 先补契约（本步又一次先改协议）：`contracts/core/openapi-case.yaml` 给建单路由补 `403`（商家侧令牌没有可归属的 customer，商家走审核队列）与 `503`（建单要问 Commerce 行归属，下游不可用必须是被声明的可重试答案），并在描述里写明「同 key 同 body 重放存储的答案」「同 line 最多一个活跃 case」；`contracts/core/openapi-commerce.yaml` 给内部列行路由加可选 `line_id`（与 `order_id` 同性质：作用域内收窄，绝不是绕过作用域），因为建单要回答契约声明的「行不属于我就是 404」。两个新契约测试先写、先失败（建单必须声明 201/401/403/404/409/422/503；列行路由参数集合恰好是 MerchantId/CustomerId/OrderId/LineId/Cursor/Limit）。契约测试 51 通过。
  - 迁移：`java/case-service/src/main/resources/db/migration/V1__case_core_tables.sql`（列与约束按 `docs/domain-model.md:22-36`）。`aftersale_case`（status 的 CHECK 就是契约的 10 个枚举值；`expires_at` 可空——它的值属于 C03 的授权，不留占位日期）；`case_requested_action` 用子表而不是 JSON 列，于是「核心只代表退款请求」（`docs/core-contracts.md:28`）落到 `CHECK (action = 'REFUND')`；`active_case_slot` **整行就是锁**，`PRIMARY KEY (merchant_id, line_id)`，终态删除即「终态释放」（`docs/domain-model.md:26`）——MySQL 没有部分索引，与其用「状态列 + 生成列」绕，不如让槽位的存在本身就是活跃；`case_timeline`（追加，`detail` 存规范化 JSON 文本，不为一个类型处理器引入依赖）；`request_idempotency`（存**当时返回的** body 与状态：事后重算会把旧 key 变成「当前状态」，那不是承诺过的东西）。
  - 代码：`casefile/CaseStatus.java`（10 个枚举值与契约逐字一致 + `isTerminal`）、`RequestedAction.java`（只有 REFUND）、`CaseRow.java`、`CaseRepository.java`（MyBatis `@Mapper`）、`CaseWriter.java`（**一个事务**写入 case、动作、槽位、轨迹首条与幂等答案：业务结果、轨迹与幂等在同一事务）、`CaseService.java`、`CommerceLineLookup.java`、`CaseController.java`、`CaseCreateRequest`/`CaseCreatedResponse`（成员与契约逐字一致）。
  - `CaseService` 的顺序即设计：先校验主体是 customer → 解析动作与描述 → 幂等键命中就回放存储的答案、指纹不同就 409 → **再**问 Commerce「这行是不是你的」 → 最后才进事务（外部网络调用不在长事务里，`docs/engineering.md:68`）。唯一键冲突被分成两种 409：同 key 不同 body 是 `IDEMPOTENCY_CONFLICT`（换新 key 才有意义），同 line 已有活跃 case 是 `CASE_ALREADY_OPEN`（重试永远没用，去读那个 case）。请求指纹用 shared-kernel 已有的 `CanonicalJson.contentHash`（与 `payload_hash` 同一套规范化），动作排序后参与哈希。
  - 数据库测试：`CaseDatabaseTest.java`（与 commerce 相同的单例 MySQL 容器模式，库名/账号与 compose 一致；`AuthControllerTest` 与 `OrderApiTest` 也改为继承它——上下文现在真的需要 case_db，连不上就是启动失败，不该在测试里遮掉）；`casefile/CaseApiTest.java`（8：201+Location+轨迹首条是客户原话、同 key 同 body 逐字重放且只建一个 case、同 key 不同 body 409 且不建、同 line 第二个 key 409 `CASE_ALREADY_OPEN`、行不可见 404 且不写任何行、商家令牌 403 且 **Commerce 一次都没被问**、缺幂等键/多字段 400、`RESHIP`/空/重复动作 422）。
  - **并发证据**（C02 验收「同 line 不并发建多个活跃 case」）：`casefile/CaseSlotConcurrencyTest.java` 用 8 个真线程同时发起，断言恰好 1 个成功、7 个 `CASE_ALREADY_OPEN`，且库里 `aftersale_case`=1、`active_case_slot`=1、`case_timeline`=1、`case_requested_action`=1；另一个测试让 8 个线程用**同一个**幂等键，断言只可能留下 1 个 case、所有成功答案指向同一 case_id，并如实断言「并发重复可能被告知重试」，不假装它一定是重放。
  - **真实跨服务端到端**（两个 jar + compose 真 MySQL）：`POST /api/v1/cases`（line 7001，行归属由 Commerce 真实判定）→ **201**，`Location: /api/v1/cases/58a7…`，body `{QUEUED,1,1}`；同 key 同 body → 逐字相同；同 key 换 body → 409 `IDEMPOTENCY_CONFLICT`；换 key 同 line → 409 `CASE_ALREADY_OPEN`；line 7201（M-1002/C-2004 的）→ 404；自己的另一行 7002 → 201；demo-reviewer → 403 `FORBIDDEN_SCOPE`；另一个顾客的 token 请求 line 7001 → 404；缺幂等键 → 400 `INVALID_ARGUMENT`。库内：2 个 case（均 M-1001/C-2002）、2 个槽位、2 条 `case.opened`、幂等表只留 `k1`/`k4`（status 201）；`case_db.flyway_schema_history` rank 1 `case core tables` success=1。
  - 命令与结果：`mvnw -pl case-service -am test` → shared-kernel 55 + case-service 33，0 失败 0 错误；`mvnw -pl commerce-service -am test` → commerce-service 22，0 失败 0 错误；`-Suite contracts` **PASSED**（51，`reports/verify/20260919-124118-contracts.txt`）；`-Suite unit` **PASSED**（java-unit 57s、python-unit 18.9s、web-test 2.2s，`reports/verify/20260919-124401-unit.txt`）；`-Suite smoke`（core）**PASSED**（`reports/verify/20260919-124526-smoke.txt`，case-service 启动时现在会跑 Flyway）。
  - 三次失败都不是设计缺陷，如实记录：① 配置补丁插入了一个**重复的顶层 `spring:` 键**，SnakeYAML 在加载上下文时直接拒绝（真实缺陷，已并入已有 `spring:` 块）；② `list(...)` 多了一个参数后，C01.2c-1 写的三处测试调用点不再编译（改用 `listByOrder`，意图更清楚）；③ 商家 403 测试断言「Commerce 从未被问」失败，因为打桩 bean 在共享上下文里保留了上一测试的观测值——测试卫生问题，已在 `@BeforeEach` 重置。另外把已弃用的 `HttpStatus.UNPROCESSABLE_ENTITY` 换成 Spring 7 的 `UNPROCESSABLE_CONTENT`。
  - C02.1b 完成（2026-09-19）：`GET /api/v1/cases/{case_id}` 的工单视图、可见性与轨迹。
  - 契约缺口修正：该路由原先只声明 `200`/`404`，**缺 `401`**——作用域来自 token，缺 token 必然 401，同一类问题在 C01.2 也出现过（补上并在描述里写明「可见性同订单视图：本人工单或拥有该行的商家；别人的工单是 404 而非 403，proposal/authorization/operation 存在时才出现」）。新契约测试钉住：401/404 都在、`CaseSnapshot.required` 只有 `case`（其余是「存在才出现」）、轨迹 `maxItems ≤ 200`、证据 `maxItems ≤ 64`、`TimelineEvent` 有 `revision`。契约测试 52 通过。
  - **只追加的迁移**：`java/case-service/src/main/resources/db/migration/V2__case_timeline_vocabulary.sql`。V1 已执行，绝不回改（`docs/engineering.md:64`），所以两件 V1 当时不可能知道的事用 V2 修正：① `kind` 用了自造拼写 `case.opened`，而契约的 `TimelineEventType` 是**闭枚举**、首值是 `CASE_CREATED`——不能对着契约校验的轨迹只是私有日志；② 事件需要自己的身份与所属 input revision，从序号推导会让事件 id 随 revision 改变含义。V2 加 `event_id`/`input_revision` 两列、为既有行 `UUID()` 补齐并改写旧拼写、然后**删掉临时默认值**并对 `kind` 加 CHECK（7 个契约枚举值）与 `input_revision >= 1`。
  - 代码：`TimelineEventType.java`（与契约枚举逐字一致；只有 `CASE_CREATED` 会被写入，其余属于 C06 起的步骤，声明它们是因为契约已经有）、`TimelineEventRow.java`、`CaseReadService.java`（可见性同订单视图：本商家 + 本人；差一个商家或不同 customer 一律同一个 `CaseNotVisibleException`，即「看不到」与「不存在」在**同一处抛出同一个异常**）、`CaseSnapshotResponse.java`（`case`/`evidence`/`timeline`，proposal/authorization/operation 未实现前**缺席而不是 null**——同一个事实不写两种表示）、`TimelineSummary.java` + `JsonField.java`（给轨迹行生成人读的一句话；从存储的 `detail` 派生而不是二次存储，两者无法互相矛盾；`detail` 读不出来时仍然给出类型与时间，宁可有缺口也不让整条轨迹加载失败）、`CaseController` 增加读路由、`CaseRepository` 增加 `findTimeline` 与 `event_id`/`input_revision` 写入、`CaseWriter` 写 `CASE_CREATED` 并生成事件 UUID。
  - 测试：`casefile/CaseReadApiTest.java`（5：本人读到的 `case` 成员集合与契约逐字一致、轨迹首条 `CASE_CREATED` + `event_id` + `revision=1` + 时间戳带 Z、四个不该出现的成员确实缺席、拥有该行的商家（reviewer）能读（审核队列就是商家的视图）、同商家不同客户/另一商家客户/另一商家 review 一律 404、操作员（同商家）能读、**别人的工单与不存在的工单 message 逐字相同**、缺 token 401、两次读取响应逐字相同（事件 id 是存储的，不会随读而变））。
  - **真实端到端**（两个 jar + compose 真 MySQL，并且是对**迁移前建的**工单读回）：`GET /api/v1/cases/58a76775…` → 200 `{case:{QUEUED,1,1,created_at,updated_at,[REFUND],7001}, timeline:[{event_id:23285ea2…, CASE_CREATED, 客户提交退款诉求（line_id=7001）, revision:1}]}`；demo-reviewer(M-1001) → 200；另一个顾客 → 404；不存在的 case → 404（与前者 message 相同）；无 token → 401。迁移在**已跑过 V1 的库上就地生效**的独立证据：`case_db.flyway_schema_history` rank 2 `case timeline vocabulary` success=1，两条既有行变成 `CASE_CREATED` + `input_revision=1` + 36 位 `event_id`（即 V2 的 `UUID()` 补齐确实执行过）。
  - 命令与结果：`mvnw -pl case-service -am test` → shared-kernel 55 + case-service 38，0 失败 0 错误；`-Suite contracts` **PASSED**（52，`reports/verify/20260919-125643-contracts.txt`）；`-Suite unit` **PASSED**（`reports/verify/20260919-125713-unit.txt`）；`-Suite smoke`（core）**PASSED**（`reports/verify/20260919-125846-smoke.txt`）。
  - 两次失败都是测试自身的问题，不是实现缺陷：① 建单测试仍断言旧词表 `case.opened`（迁移是刻意改词表，测试跟着改成 `CASE_CREATED` 并注明原因）；② 可见性测试原本用「JWT 字符串里是否含 M-1001」判断角色——JWT 是 base64，当然不含，于是把操作员也当成不该可见，写成显式的 `Caller(who, token, mayRead)` 三元组，失败信息里也会说出是谁被放进来了。另 `StatusAssertions` 在该版本没有 `as(String)`，改为在 `value(...)` 里用 AssertJ 带描述的断言。
  - C02.1 完成判据：同 key 换 body 409、同 line 不并发建多个活跃 case、状态与查询可用、跨主体 404 且与不存在不可区分——全部有测试（含 8 线程并发）与真实端到端证据；材料相关（C02.2）未开始，材料不覆盖/旧 revision 不可写仍属未验证。
  - C02.2a 完成（2026-09-19）：`POST /api/v1/cases/{case_id}/evidence` 材料追加。
  - 契约缺口修正（两处）：① 该路由只声明 `200/404/409/422`，**缺 `401`**（作用域来自 token）与 **`403`**（客户端不得把系统读到的事实当成自己的陈述）；② 契约的 `TimelineEventType` 是闭枚举，却**没有任何成员表示「材料到了」**——那样一个 revision 变了却无人解释的工单视图，恰好是最需要解释的那种。补 `EVIDENCE_APPENDED`，并把来源规则写进路由描述（客户的 `CUSTOMER_STATEMENT`、商家的 `REVIEWER_VERIFICATION`；`ORDER_LINE`/`PAYMENT_LEDGER`/`SHIPMENT`/`SHIPMENT_TRACK`/`POLICY_RULE` 是平台自己读的事实，客户端提交即 403）。契约测试 53 通过，新增的测试断言「每个 kind 要么是某人说的、要么是系统读的，两者不重叠」。
  - **只追加的迁移** `V3__case_evidence.sql`：建 `case_evidence`（来源/ref/version/content_hash/input_revision/observed_at/内容/question_id/提交者与角色），主键 `(case_id, evidence_id)`，`input_revision >= 2` 的 CHECK（revision 1 是建单，永不含材料），`source_type` 用契约枚举的 CHECK；并用 `DROP CHECK` + `ADD CONSTRAINT` 把 V2 的 `kind` 闭列表扩到含 `EVIDENCE_APPENDED`（追加而非回改 V2）。
  - 代码：`EvidenceSourceType`（与契约枚举逐字一致，并显式标注哪种是「平台读到的」）、`EvidenceRepository`（只有 insert / 查询 / 加 revision，**没有任何 update 或 delete 语句**，所以「材料不覆盖」不是靠人记得，而是没有能破坏它的代码路径）、`CaseEvidenceService`（一个事务内：锁 case 行 → 校验可见性/状态/来源 → 写材料 → 同一条 SQL 里 `input_revision+1` 与 `version+1` → 写 `EVIDENCE_APPENDED` 轨迹）、`EvidenceAppendRequest`（**没有 revision 成员**，带了就是未知成员 400）、`EvidenceSubmissionResponse`、`CaseController` 追加路由、`ApiExceptionHandler` 增 409 `STATE_CONFLICT`、`CaseRepository.findCaseForUpdate`/`highestSequence`、`TimelineEventType.EVIDENCE_APPENDED`、`TimelineSummary` 给该类型一句话（`switch` 是穷尽的，所以以后新增事件类型**编译期**就会要求给它一句话）。
  - 三条规则的落点：① 来源由 `requireProvenance` 判定（客户只能交陈述、商家只能交自己的核验、机器来源一律 403）；② revision 由服务端决定——请求体里没有这个成员，所以「写进旧 revision」没有可拼写的表达，比校验一个客户端传来的数字更强；③ 输入封闭由状态判定，`EXECUTING`/`RECONCILING`/终态 → 409，且**被拒绝的追加不会移动 revision**（有断言）。
  - 顺带删掉 `CaseRepository.countCasesForLine`：它**从未被调用**，而它的查询统计的是该行的**所有** case 而非活跃 slot，与「同行一次只有一个活跃 case」相矛盾。活跃规则实际由 `active_case_slot` 主键 + `DuplicateKeyException` 正确且并发安全地实现，所以这不是「修了一个 bug」，而是删掉一个没人调用、却写错规则的陷阱。
  - 测试 `casefile/EvidenceApiTest.java`（8）：200 成员集合与契约一致 + 库内 hash 64 位 + `source_ref=customer:C-2002` + case 的 revision/version 同时 +1 + 轨迹第二条是 `EVIDENCE_APPENDED` 且 revision=2 + 读回视图 summary「客户补充了材料」；两次提交是两条记录且旧内容仍在、id 与 hash 都不同（**材料不覆盖**）；带 `input_revision` 的 body 是 400 且库内**不存在** revision=1 的材料（**旧 revision 不可写**）；4 种机器来源对客户一律 403、reviewer 交客户陈述 403、别的客户 404、reviewer 交自己的核验 200；`EXECUTING` 下 409 且 revision 未动；`WAITING_CUSTOMER` 补证回 `QUEUED`、`PENDING_REVIEW` 补证只动 revision 不动状态；空文本/未知 kind/缺 kind/超 8000 字符 422、无 token 401、不存在工单 404；**并发 8**：4 个追加并发拿到 2/3/4/5 四个互不相同的 revision、库内 4 条记录 4 个不同 revision、case 恰好 +4（`FOR UPDATE` 串行化的直接证据）。
  - 命令与结果：`mvnw -pl case-service -am test` → shared-kernel 55 + case-service **46**，0 失败 0 错误；`-Suite contracts` **PASSED**（53，`reports/verify/20260919-131248-contracts.txt`）；`-Suite unit` **PASSED**（`reports/verify/20260919-131320-unit.txt`）；`-Suite smoke`（core）**PASSED**（`reports/verify/20260919-131456-smoke.txt`）。
  - **真实端到端**（只启动 case-service，**故意不启动 Commerce**，证明追加材料这一路径不依赖下游）：向 C02.1b 之前建的工单 `58a76775…` 追加 → 200 `{case_id, input_revision:2, version:2}`；同一客户提交 `SHIPMENT` → 403 `SHIPMENT is read by the investigation, not asserted by a caller`；带 `input_revision:1` 的 body → 400；读回工单 → 轨迹两条（`CASE_CREATED` revision 1、`EVIDENCE_APPENDED` revision 2），case 的 `input_revision=2 version=2`。迁移就地生效：`flyway_schema_history` rank 3 `case evidence` success=1（V1→V2→V3 全为 1）。库内材料：`source_type=CUSTOMER_STATEMENT`、`source_ref=customer:C-2002`、hash 64 位、`appended_role=CUSTOMER`。
  - 一个诚实的小插曲：`docker exec mysql` 打印中文显示为 `????`，我用 `HEX(LEFT(content,2))` 判定是控制台字符集而非存储损坏——`E5B08FE58CBA`（小区）、`CHAR_LENGTH=17`，即真 UTF-8。没有靠「看起来像」下结论。
  - 落库与可见性的**已知缺口**（如实记录，不假装完整）：材料写入后没有公开读回路径——契约里工单视图的 `evidence` 数组是 **Agent observation 的引用**（`observation_id`），在 C06 把观测绑定到材料之前，我不发明 observation_id，所以该数组仍不输出；也就是说现在「材料存下来并可校验，但还看不到」。
  - C02.2 剩余：消费前取消（含终态**释放活跃 slot**）、SSE 读接口（`GET /api/v1/cases/{case_id}/events`，Last-Event-ID 续传、token 只在 header）。C03 的授权消费会补上「已消费授权」这一层的 409 判定（当前按状态判定，对 `EXECUTING`/`RECONCILING` 已经正确）。

### C03 政策、方案与审批

- [ ] C03.1：合成政策受控导入（C03.1a）、不可变版本、按支付时间选择；不做管理后台。
- [ ] C03.2：Java方案校验/金额重算/风险路由与人工核验。
- [ ] C03.3：版本授权、审批/消费/取消事务边界；消费后拒绝材料变更，固定operation ID。
- 依赖：C02。文件：Case policy/decision/authorization及各自测试，分模块实施。
- 验收：物流自动条件完整，损坏始终人工；旧授权/过期/越权拒绝，approve与consume竞态可解释。
- 验证：规则表驱动、200元边界、revision/取消/消费并发测试。
- 实际记录：未执行。

### C04 持久模拟退款与本地金额事务

- [ ] C04.1：SQLite provider-stub退款幂等、查询、丢响应/延迟可见与重启。
- [ ] C04.2：Commerce line_refund/ledger/operation，接收命令本地预留、成功/失败结算。
- [ ] C04.3：事务外调用provider、UNKNOWN持久对账，不实现跨服务权益协议。
- 依赖：C01。文件：fixtures/provider、Commerce退款及迁移/测试；stub与业务事务分开。
- 验收：同ID换载荷拒绝；100并发不超退；UNKNOWN保持预留，成功不二次结算。
- 验证：provider协议/重启、MySQL事务/并发、成功丢响应集成测试。
- 实际记录：未执行。

### C05 消息与退款端到端

- [ ] C05.1：Case/Commerce Outbox/inbox、核心topic验签、持久重试与错误记录。
- [ ] C05.2：Case消费授权同事务发命令，Commerce结果投影/权威查询，连通人工方案到退款。
- 依赖：C03,C04。文件：messaging、Case执行、Commerce消费者及集成测试。
- 验收：重复/乱序/ACK丢失不重复业务；目标确认成功才关单；失败释放后再试须新授权。
- 验证：真实RocketMQ+MySQL系统退款测试，CF1/CF2/CF3定点冒烟。
- 实际记录：未执行。

### C06 Agent控制面、MCP与能力冒烟

- [ ] C06.1：PG持久run入口、Case HTTP outbox与绑定，尚无模型也能可靠排队。
- [ ] C06.2：Commerce模拟物流只读适配、5个stdio MCP工具、scope与错误Observation。
- [ ] C06.3：mock ModelClient和经预算确认的live小样本结构化调用；提前核验工具能力，不预跑固定业务链。
- 依赖：C02。文件：agent/api/tools、Case dispatcher、Commerce物流及测试；分语言/端点小步。
- 验收：202在落库后，真实MCP list/call，模型无法改line/身份；mock/live记录分开。
- 验证：PG重复提交、MCP协议/越权、工具失败；live不可用明确阻塞项，不伪造。
- 实际记录：未执行。

### C07 政策检索与上下文

- [ ] C07.1：固定bundle索引、真实dense与BM25基线、版本/商家过滤、引用。
- [ ] C07.2：ContextBuilder关键事实/来源/冲突保真、token上限、原文索引及scope读回。
- 依赖：C03,C06。文件：agent/policies、harness/context、相应fixtures/tests。
- 验收：索引未就绪不搜旧版本；关键字段不被摘要改写；超限明确终止，原文可按ref读回。
- 验证：检索过滤/真实embedding冒烟、上下文七类fixture；无四组消融要求。
- 实际记录：未执行。

### C08 动态Harness与业务接入

- [ ] C08.1：固定manifest/动作ABI、动态循环、预算预占/重试、防无进展与候选引用验证。
- [ ] C08.2：问题/方案/失败回调outbox，补证新run、旧结果STALE，Java复核后退款。
- 依赖：C05,C07。文件：agent/harness/runtime/callbacks、Case回调及端到端测试。
- 验收：至少6组配对证据由模型决定不同合理行动；身份不由模型生成；预算/权限有界，闭环不是固定workflow。
- 验证：H1/H2/H3、mock系统闭环、live小样本（需API预算）。
- 实际记录：未执行。

### C09 持久恢复与版本保护

- [ ] C09.1：checkpointer fence事务、租约/advisory lock与取消，复用T00已验证能力。
- [ ] C09.2：稳定call记录、已落库结果复用、UNKNOWN计费/预占、manifest不兼容拒绝。
- 依赖：C08。文件：agent/runtime持久层、调用存储、故障测试。
- 验收：旧worker不能写checkpoint/有效回调；预算/deadline不重置；补证继续与同run故障恢复区分。
- 验证：H4/CF6两类崩溃窗口、旧fence/旧revision/版本不匹配测试。
- 实际记录：未执行。

### C10 选定轨迹的strict回放

- [ ] C10.1：只读导出合成ReplayPack、实际输入/显式响应/观察/usage/Clock与hash。
- [ ] C10.2：只支持strict、隔离adapter与CallbackSink、禁网络执行，5个完整golden packs。
- 依赖：C09。文件：evals/replay、scripts/replay入口、隔离配置与回归测试。
- 验收：规范状态/动作/引用/预算一致；缺记录/篡改/不支持轨迹拒绝，无业务写；不实现反事实/world。
- 验证：H5、strict正反fixture与真实网络阻断测试。
- 实际记录：未执行。

### C11 轻量展示、核心启动与查询优化

- [ ] C11.1：简单建单/补证、审批、轨迹/结果视图，SSE权限与断线续读；不建运营后台。
- [ ] C11.2：一条查询路径索引/非权威缓存优化与Redis有界回源，保留优化前基线。
- [ ] C11.3：core profile服务镜像/健康启动、有限日志指标、已有CI加入核心回归；不依赖Nacos/完整观测集群。
- 依赖：C08。文件：web、Case SSE/query、infra/scripts/CI；三个子项分开迭代。
- 验收：能操作核心闭环、看清UNKNOWN/人工/失败；查询优化不影响授权事实；一键启动不是空操作。
- 验证：web test/build与浏览器核心交互、SQL EXPLAIN、core smoke、已实现all-offline。
- 实际记录：未执行。

### C12 核心实验与报告

- [ ] C12.1：80业务/20安全/40检索案例、冻结划分和至少20个人审记录；小样本先检验Gold正确性。
- [ ] C12.2：B1/A真实模型对照及指定样例重复、RAG两组、CF1–CF6与一项性能实验。
- [ ] C12.3：统计全部失败/成本/分母/资源、分析负面结果，不强求每项提升。
- 依赖：C09,C10,C11。文件：evals/datasets/runner/metrics、tests/faults/performance、reports；按一个实验一批。
- 验收：evaluation核心范围全部有真实报告；非法执行0；缺API/预算标阻塞而非通过。
- 验证：agent-eval live、rag-eval、faults、performance及报告输入hash/计算核对。
- 实际记录：未执行。

### C13 核心交付与简历主张审计

- [ ] C13.1：5个可复现演示、启动/故障手册、个人技术取舍说明。
- [ ] C13.2：按CI-01–10、US-C1–6、K1–K7检查代码/测试/报告，对照实际支持范围写简历候选条目。
- 依赖：C12。文件：docs/demo.md、docs/runbook.md、docs/interview-notes.md、reports/core-final-review.md、todo记录。
- 验收：陌生使用者能复现核心演示；没有未实现补发/反事实/商用/高可用主张；延期项不阻塞完成。
- 验证：最终相关all-offline、演示实跑、报告与简历证据核对；未运行明确列出。
- 实际记录：未执行。
