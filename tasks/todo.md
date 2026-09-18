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
  - 未执行：C00.2（核心 OpenAPI/Schema/DTO/fixture/路由覆盖）与 C00.3（core profile 启动与 smoke 选择）未开始；`verify -Suite all-offline` 本轮未重跑（留到 C00.3）；core profile 的服务启动尚未验证。

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
