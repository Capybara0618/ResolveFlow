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
- [ ] C00.2：按消费者分批新增核心Schema/OpenAPI、Java/Pydantic DTO及正反fixture/路由覆盖；新命令/事件/方案版本与旧基线显式区分。
- [ ] C00.3：调整核心启动/smoke选择，默认不要求fulfillment/Nacos/全套观测；旧协议和测试保留，服务镜像未就绪则不宣称core profile完整可用。
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
  - C00.2c 小结：a（契约实例）、c-1（提案 schema 与 OpenAPI 对齐）、c-2a/b（正反语料 51 条）、c-3a/3b（Python+Java DTO 与跨语言字节级一致）均已完成并推送；`verify -Suite all-offline` 在核心改动后完整通过。
  - 未执行：`verify -Suite all-offline` 仍未重跑（留到 C00.3）
  - 未执行：C00.3（core profile 的启动与 smoke 选择：当前 smoke 仍会拉起 fulfillment-service 与 Nacos，且启动清单尚未迁移到 core 口径）未开始。；C00.2c-2b（核心反向 fixture）、C00.2c-3（Java/Pydantic 核心 DTO）、C00.3（core profile 启动与 smoke 选择）未开始；core profile 的服务启动尚未验证。

### C01 身份与订单只读切片

- [ ] C01.1：演示身份/网关与资源服务JWT，固定商家/用户/审核角色；不做完整IAM。
- [ ] C01.2：Commerce订单/支付快照迁移、种子和读接口，Case公共订单视图，跨主体拒绝。
- 依赖：C00。文件：Java安全模块、Commerce订单、Case视图及测试，按纵向接口分批。
- 验收：本人能看订单，跨用户/商家不能看；金额为整数原快照，独立数据库账户不跨库读取。
- 验证：JWT/归属单元、MySQL集成与核心契约测试。
- 实际记录：未执行。

### C02 建单、材料与版本

- [ ] C02.1：建单/幂等/同line活跃slot、状态与查询。
- [ ] C02.2：补充证据增revision、消费前取消、timeline和权限；预留SSE读接口。
- 依赖：C01。文件：Case domain/application/api/migration/tests；逐行为交付。
- 验收：同key换body409、同line不并发建多个活跃case；材料不覆盖，旧revision不可写。
- 验证：数据库并发建单、状态转换与材料权限测试。
- 实际记录：未执行。

### C03 政策、方案与审批

- [ ] C03.1：合成政策受控导入、不可变版本、按支付时间选择；不做管理后台。
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
