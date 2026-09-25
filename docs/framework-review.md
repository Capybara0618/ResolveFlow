# 框架审阅记录

当前框架文档v1.3（2026-09-25），业务范围沿用v1.2。下文各版本检查是对应日期的历史记录，旧范围/任务数量/“尚未实现”不作为当前进度。当前范围见core-scope，当前进度见tasks/todo；v1.3检查另列于末尾。

## v1.0已执行检查（历史记录）

- Markdown文件的本地链接存在性、代码围栏配对。
- 3个JSON Schema通过Draft2020-12元Schema检查；通过本地registry解析跨Schema引用。
- 14组正/反fixture验证：合法退款、合法补发、Agent方案、签名事件，以及负金额、错target、坏UUID、未知字段、缺证、越权输出字段、缺schema_version、缺签名、事件动作错配和伪造producer。
- 35个任务全部有验收/验证/实际记录字段；依赖引用存在，依赖图无环。
- 人工式逐节交叉审阅：业务范围、表状态、接口、失败路径与实验分母；以下问题已在文档修正。

验证运行使用临时目录tmp/spec-validation中的jsonschema库，未加入产品依赖。该检查证明文档结构和样例协议有效，不能证明未来Java/Python实现已经正确。

## 修正后的关键设计

1. 退款与补发统一行权益；权益历史表保留释放后的幂等记录，旧operation不能重新占用。
2. 目标start与取消墓碑一起防迟到命令；UNKNOWN不可凭TTL释放。
3. Agent风险提示与Java授权分开；金额、规则和身份必须权威复核。
4. 授权绑定不可变载荷、输入/政策版本，消费与撤销在case事务内排序。
5. 授权预分配operation ID，明确hash输入避免自引用及跨语言差异。
6. Agent checkpoint也受fence约束，避免只保护业务表却被旧worker覆盖图状态。
7. 补证后的新run与同run故障恢复分别定义；模型调用未落库窗口允许重复并计入成本。
8. RAG按合同时间与发布时点选择版本，执行时单独检查撤销；Java结构化规则控制动作。
9. live、mock、合成数据和真实业务用户严格区分；Agent准确率分母含超时/失败。

## 已定与仍需实测

已定：产品范围、服务数据归属、主技术栈、业务不变量、Agent执行方式、接口方向、事务协议、实验设计、任务依赖与交接方式。

T00实测锁定：框架补丁版本/镜像digest、客户端兼容、PG checkpointer事务接入。T02生成：完整OpenAPI与对应代码类型/fixture。实施时依规范补全各服务迁移DDL和方法内部细节。live评测前配置模型API与预算；没有这些信息不妨碍先完成其余实现。

尚未执行：任何业务构建、集成测试、负载/故障实验、模型效果评测。全部任务仍为未完成，指标仍为目标。

## v1.1 Harness深化与本轮检查

新增agent-harness.md、context-engineering.md、trajectory-replay.md与harness-manifest.schema.json；同步Agent规格、数据表、架构、工程命令、评测、交接、任务和简历证据。Java业务边界与资金不变量未扩大。

本轮实际执行的文档检查：

- 20份Markdown的本地链接与代码围栏检查通过，检查时共36个本地链接，无缺失目标。
- 4份JSON Schema通过Draft2020-12元Schema校验，本地registry跨Schema解析正常。
- 23组Schema正反fixture通过，含原14组及9组manifest有效结构、非法hash格式、缺Prompt、额外凭证字段、调用预算/本地读上限、非法模型参数检查。
- 40个任务均含依赖、验收、验证和“实际记录：未执行”；任务引用完整，依赖图无环。T35–T37在T20前、T38在T32前、T39在最终演示/审计前。

语义交叉审阅明确：模型动态行动与Harness硬约束分离；关键上下文不由LLM改写；manifest在同run不可变；UNKNOWN预占不在恢复后清零；回放逻辑ID与实验存储隔离；历史未覆盖或多版本歧义明确INCOMPLETE；精确计费不能由估算token保证。

最终复核补清：排队deadline与120秒调查窗口分别持久化，恢复不延长期限；回调投递与模型调查预算分开；工具模型excerpt上限与原始网络响应上限分开；GH在T38、完整消融在T39/G6，避免交接模型误判阶段顺序。

限制：本轮Schema fixture验证结构和范围，不验证真实manifest内容hash、provider能力或跨字段预算关系；这些语义测试明确归T35。H系列、GH、回放网络隔离、C0/C1/C2、真实模型效果均为待实现验收，未运行。文档检查不能替代未来代码测试，14项简历证据当前全部是计划。

## v1.2个人项目收缩检查（2026-09-18）

用户确认以个人技术亮点为目标，不做公司级平台。本轮仅修改规格、范围、实施任务与模型交接，未修改业务代码、Schema/OpenAPI、fixture、测试或依赖锁；未改数据库、未提交/推送。

范围变更：仅保留退款；Gateway/Case/Commerce与Python Agent；Fulfillment/补发/库存/跨动作权益不在核心部署；Harness保留动态决策、上下文、预算、恢复与选定轨迹strict回放。反事实/world、全量消融与完整观测配套退出门槛。用户已确认的保留范围内权限和金额不变量继续强制。

当前新任务为C00–C13，旧T00–T02成果保留，T03–T39不按旧顺序继续。旧plan/todo完整内容已归档至tasks/archive；本轮逐内容核对（归一化换行后）与修改前一致。旧contracts文档继续供既有T02路由测试读取，核心目标另列core-contracts；代码迁移归C00，尚未执行。

实际检查与命令：

- 文档脚本：26份Markdown、53个本地链接及代码围栏检查通过；14个C任务都有依赖/验收/验证/未执行记录，依赖引用完整且无环。
- git diff --check：通过，无空白错误。
- .\\agent\\.venv\\Scripts\\python.exe -m pytest agent/tests/unit -q：155 passed，10.53秒；1个既有Starlette/AnyIO弃用警告，未为文档任务修改依赖。
- .\\agent\\.venv\\Scripts\\python.exe scripts/contracts_freeze.py --check：32个正向fixture验证、58个非法fixture拒绝，frozen expectations match the corpus。
- Git变更范围检查仅含Markdown；历史任务归档没有删除原有实际记录。

本轮未运行Java构建、Docker全栈smoke、业务故障/性能/live模型评测，因未改对应代码且核心实现尚未开始；不据Python通过宣称整个系统已正确。核心任务均仍待执行，未来简历指标仍须实际报告。

## v1.3 AgentScope迁移文档检查（2026-09-25）

用户批准框架替换，其他范围和技术深度不变。本轮新增agentscope-migration规格/DSH首轮提示词，同步入口、架构、Agent/恢复/上下文/回放约束、版本依据、AS任务及C07–C10承接。旧交接标明历史，修正README/AGENTS等“从C00开始”的过时入口；历史C00–C06记录保留。

设计检查重点：唯一AgentScope循环；动作ABI/批次/终止映射；模型与工具调用前硬拦截；最终输入与输出预占；PG快照/fence/调用账事务；旧响应复用与UNKNOWN计费；manifest旧字段兼容；SDK与领域逻辑共同strict回放；不引入公司级平台。AS01先验证，用户审阅后AS02切换，不能把候选版本或历史LangGraph证据当作AgentScope已通过。

实际验证（2026-09-25）：

- 内联PowerShell文档检查：23份新增/修改Markdown、66个本地链接目标与代码围栏配对通过；按C00标题至C07标题提取内容，归一化换行后与HEAD比较，C00–C06历史记录完全一致。检查脚本首次因正则字符串引号拼接错误未执行，修正脚本后重跑通过，未因此修改业务文件。
- `git diff --check`：通过。
- `$migrationContractTests = @(rg --files agent/tests/unit -g 'test_contracts*.py'); & .\agent\.venv\Scripts\python.exe -m pytest @migrationContractTests -q`：549 passed、9 skipped，20.53秒；使用现有环境，未改锁。跳过项不视为通过。
- 修订前记录的8个非文档未提交文件逐一`Get-FileHash -Algorithm SHA256`复核全部一致；其余本轮新增/修改均为Markdown。未改业务代码、依赖锁、Schema/fixture或数据库。

未运行：AgentScope安装/AS01探针、Java构建、Docker全栈smoke、Agent业务故障/性能/live评测；这次是文档交付，不能据契约回归宣称框架迁移成功。不执行付费API、不提交或推送。AS00–AS02全部保持未完成。
