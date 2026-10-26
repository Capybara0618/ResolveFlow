# 后端四项技术点：开发方案 v1.1

2026-10-26。依据用户确认的七条简历结构，本方案只覆盖第1、4、5、7条；第1条原简历文字保持，第4、5、7条以用户认可的凝练版为目标。配套[评测方案](backend-resume-evaluation-v1.md)固定如何验证和填数。

2026-10-26修订：用户确认第7条加入Redisson分布式锁，明确以双Commerce实例的评价热点缓存重建为落点，替代原D4“测后决定是否合并同实例加载”的可选方案。第1、4、5条不变，Agent侧三条保持冻结。本次只更新方案；Redisson尚未引入，新增对照及故障矩阵尚未执行。

执行进度仍只在[tasks/todo.md](../tasks/todo.md)顶部维护，实施按[交接约定](../tasks/handoff-current.md)保持唯一写入者。D0运行入口、冻结构建及真实基础链路已完成，实际命令、失败修正和证据见[D0报告](../reports/backend-resume-v1/README.md)；后续功能及正式矩阵分别验收。

## 1. 目标正文

第1条“多租户电商微服务”保持用户现有简历原文，本批不改写。实现核对关注服务职责、数据归属、跨店本人访问和商家资源范围；不为凑服务数量继续拆分。

- **4．多商家交易与并发一致性：**实现按店购物车与多商品结算，通过版本校验和行锁处理并发修改，下单时复核价格与商品状态；付款请求幂等处理，订单与账本同事务生成，响应丢失后查询原付款结果。在【并发数】并发、【轮次】轮竞争测试中，重复订单与重复模拟扣款均为【数量】笔。
- **5．版本化授权与异步可靠退款：**审批授权绑定材料版本，补证后旧授权自动失效；通过 RocketMQ、Outbox/Inbox 和操作幂等处理重复消息与服务中断，预留金额防止超退，结果未知时保留占用并按原操作对账。在【类别数】类【次数】次故障测试中，重复退款与超额退款均为【数量】笔。
- **7．SQL查询与Redis缓存优化：**通过复合索引、游标分页和批量查询优化工作台与商城列表，使用Redis缓存审核队列及评价，结合Redisson分布式锁减少热点缓存重建时的重复查询，并通过Lua账号限流与有界回源保护数据库。在【工单数】工单、【并发数】并发下，接口p95由【优化前】ms降至【优化后】ms，数据库查询量减少【比例】%。

这三条是交付目标。占位结果不预设为0或某个提升比例，正文中的工作台、商城列表等范围最终与对应评测逐一关联。

## 2. 范围与职责

| 组件 | 本批职责 | 数据所有者 |
| --- | --- | --- |
| Gateway | 公共HTTP入口、原有路由与身份头处理 | 不持有业务数据库 |
| Case | 身份/买家店铺映射、售后材料、修订号、审批授权、命令Outbox和退款结果投影 | case_db |
| Commerce | 商品/购物车/结算/订单/模拟付款、评价、资金账本、退款执行与结果Outbox | commerce_db |
| Python Agent | 保留已有服务边界；本批用明确合成的建议/资格来源准备后端场景 | 本批不改PG运行逻辑或模型循环 |

购物和退款为模拟交易。沿用Java21、Spring、MyBatis/JdbcTemplate、MySQL、Redis、RocketMQ及现有锁定依赖；按本次用户授权仅追加Redisson所需依赖并锁定兼容版本，不升级既有框架或更换Redis部署。不新增库存、补发、跨动作Saga、真实支付、新MQ或微服务。不更换现有Agent/RAG/Harness实现，不产生收费模型请求，不修改桌面简历。

资金与事务约束：同一订单行最多一次成功退款；整单已退+预留不超过支付额；UNKNOWN不释放占用、不换ID重付。授权消费后不修改材料或取消。Inbox、业务效果和本地事件在本地事务提交，外部网络调用在事务外。

## 3. 已有基础与明确缺口

本次只读核对发生在仓库c3aaf9c之后、97cacb2时点；两个提交属于另一批Agent评测。真正实施前重新记录源码/构建hash，不把此时点当最终实验基线。

| 范围 | 已有实现 | 本批处理 |
| --- | --- | --- |
| 交易 | [CartService](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/CartService.java)、[MultiCheckoutService](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/MultiCheckoutService.java)、[CheckoutPayments](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/CheckoutPayments.java) | 保留版本、幂等、快照与短事务；先补竞争反例，再修暴露的通用问题 |
| 付款恢复 | [CheckoutRecoveryService](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/CheckoutRecoveryService.java)及已有调度 | 验证原attempt、收据已存/订单未发布、到期竞争及重启；不重做V18迁移 |
| 付款提供方 | [SimulatedCheckoutProvider](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/SimulatedCheckoutProvider.java)以REQUIRES_NEW事务存收据 | 本机模拟器，与退款SQLite provider不同；HTTP响应丢失通过独立代理制造，不称真实外部支付 |
| 授权/退款 | 已有revision、授权消费、双向Outbox/Inbox、操作幂等、预留与对账 | 复用生产链路，补当前版本整链、MQ停机恢复及关联诊断 |
| 订单列表 | [PurchaseReads.list](../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/PurchaseReads.java)先取ID再逐条read；[BuyerPurchaseService](../java/case-service/src/main/java/com/resolveflow/caseservice/shopping/BuyerPurchaseService.java)按店分页归并 | 明确存在逐订单组装；优先改Commerce批量读取，保持Case跨店合并与游标语义 |
| 商品/缓存 | 商品列表已有批量SKU；工作台2秒缓存、评价30秒epoch缓存、Lua限流、有界回源；尚无Redisson | 复用现有能力，新增双Commerce实例热点重建锁及对照；保留锁关闭条件，分别测缓存、锁的收益 |
| 旧评测 | [退款脚本](../scripts/resume_refund_benchmark.py)、[查询脚本](../scripts/resume_review_benchmark.py)、[隔离验收驱动](../scripts/backend_deepening_acceptance.py) | 复用逻辑前参数化新库、端口、运行标识；旧退款脚本固定历史库名，不能直接运行 |

已有[后端深化报告](../reports/backend-deepening-v1.md)和[历史量化报告](../reports/resume-quantification-v1/README.md)作为实现/实验参考；新结果另建目录，不覆盖旧结果或继承旧延迟。

## 4. 开发子步与验收

通常每步3–5个核心文件；若触及API合同、共享类型或fixture，单独拆成同步子步。每步先失败测试、实现、相关验证、记录、精确commit/正常push；失败保留原因，不删除断言。独立步骤如下。

### D0：隔离运行与基线冻结

1. 接管后核对分支、未提交改动和原服务；保存本批文件清单，保留四个历史脏文件。
2. 复用已有容器镜像与初始化文件，创建独立label/项目名的MySQL、Redis、RocketMQ及模拟退款provider；端口只绑定loopback，数据库账号只给新实验库权限。
3. Gateway、Case、Commerce用当前源码构建；不启动收费Agent worker。预置合成材料/人工方案，之后真实走审批、消费、MQ与provider。
4. 参数化运行标识、schema、端口、topic/group、输出目录，验证名称/label/PID命令归属和占用拒绝；任何缺失参数不回落到旧实验库。
5. 建立prepare、exercise、resume、verify、stop生命周期；此为待开发能力，不是现有通用CLI。resume复用原资源/幂等键，仅执行缺失步骤；stop保留容器与卷。

完成标准：隔离链路冒烟通过；能核对Gateway→Case→Commerce路径、消息topic/group、提供方持久结果；从头到停止不触碰原业务数据。冻结优化前JAR、配置、数据生成器和实际查询/接口基线。

### D1：交易竞争与付款恢复

先为购物车同revision竞争、同key不同内容、结算时变价/下架/规格变化、同草稿付款重放与多key竞争、收据后崩溃、付款/到期竞争增加反例。需要确定先后顺序时使用屏障和故障门控，不用sleep猜测竞争窗口。

优先复用现有唯一键、行锁和状态条件；明确付款涉及两个提交边界：提供方收据持久化，随后本地订单/行/退款槽/账本原子发布。失败恢复查询原attempt，不能依靠新key绕开PAYMENT_PENDING。

故障门控只放在测试配置或进程外代理；正式入口不能开放任意改状态、扣款或清库接口。通过只读数据库/提供方记录核对唯一业务结果。具体场景与分母见评测方案T01–T08。

完成标准：相关购物车/付款/多行/恢复测试通过；正确拒绝过期版本/非法key重用；付款结果能够在原ID上恢复，整笔订单行金额之和与账本一致。

### D2：版本授权与可靠退款

接现有授权矩阵，验证材料更新、人工核验、撤销、消费与输入修改的两个提交顺序。将不同概念分开：input_revision控制授权有效性，资源version检测并发修改，event_id去重消息，operation_id保证业务幂等。

参数化旧退款故障执行器，实际运行Case命令Outbox→RocketMQ→Commerce消费/预留/执行→结果Outbox→Case投影。普通整链启用自动投递；为固定故障窗口临时暂停自己的投递器，并在报告标明，不伪造生产事件。

补最小只读诊断：由operation_id关联case/authorization、revision、command/result event、Outbox状态及重试时间、Inbox投递次数、账本预留、provider结果和最近安全错误。优先实验报告/只读CLI，不新增通用管理平台；若必须新增业务API，另同步权限、合同和测试。

完成标准：过期授权无执行命令；消费后更新/取消拒绝；重复消息和不同event_id同操作均只形成一次业务效果；UNKNOWN保留占用；服务/消息依赖恢复后能按原记录继续。F01–F07为正式故障范围。

### D3：订单列表批量读取

1. 在真实MySQL/JDBC执行点计数，先记录1/24/48条页面及1–3行订单的实际SQL，包含新草稿、新已付订单与历史订单。
2. 保留候选ID查询，按页批量读取草稿、最新付款尝试、草稿行、历史订单行、店铺与退款汇总；用Map组装DTO，避免逐订单调用read/snapshot/refundStatus。
3. 批量条件带可信merchant/customer；保留未付款/UNKNOWN/已付/取消/到期、退款占用汇总、行排序、时间相同排序、limit+1与cursor语义。
4. 只读快照覆盖这一页各批查询；不把Redis或HTTP等待包进数据库事务。详情入口继续读权威数据。
5. 优化前保留固定fixture的预期投影；优化后逐项对比，并测试跨买家/跨店、历史兼容、边界分页。不要用同一份新组装代码自比验证。

完成标准：非空页SQL不再随订单数线性增长，1/24/48页结果与原合同一致；实际常数及执行计划以测量记录，不预先硬写成两条。跨店HTTP请求数单列；本步不把Case店铺扇出自动改成并发或全平台跨域查询。

### D4：工作台SQL与Redis保护

| 项目 | 开发动作 | 验收 |
| --- | --- | --- |
| 工作台索引 | 对正式workspace各主筛选、搜索和游标执行EXPLAIN ANALYZE；仅为有证据的瓶颈追加索引迁移 | 前后行数/扫描/排序及HTTP正确性；不机械复制旧list索引 |
| 已有缓存 | 保留2秒展示缓存和30秒评价epoch，校验身份/过滤/游标隔离 | 公共输出无私有字段；权限/金额/资格不取缓存 |
| 缓存指标 | 真实记录hit/miss/error/DB调用/inflight/拒绝，Redis I/O在DB事务外 | 指标在真实调用点增长；命中仍查epoch明确计入DB次数 |
| Redisson热点重建 | 双Commerce实例按评价商品/epoch共享RLock；获取后再次检查缓存，仍缺失才重建 | 同key正常重建跨实例互斥、不同key独立、等待有界；异常/宕机后锁可恢复，旧epoch不污染新代 |
| Lua限流 | 保留WRITE/REPLY每账号各6次/60秒 | 两Case实例共用Redis，窗口合计6放行，其他账号/动作隔离；429/503在Commerce写入前返回 |

Semaphore=8/100ms为单服务实例DB门控；双Commerce实例总上限可以为16，不能宣称全局8。Redis读故障可有限回源，账号写限流故障503；固定窗口允许边界突发，实验分别记录。新增Redisson用于重建协调，Spring Data Redis继续执行缓存读写和Lua限流。热点商品详情缓存、多级缓存与资金路径分布式锁不在本批范围。

#### D4.1：依赖与开关

先核对锁定的Boot4/Spring Data Redis/Netty版本，在最小集成测试中验证Redisson同步RLock、超时、连接关闭与序列化边界；固定可用版本并记录dependency tree，不直接引入会替换现有Redis配置的starter。两个客户端显式指向同一自有Redis，连接池规模、命令超时、客户端重试和关闭生命周期均记录。保留独立重建锁开关，便于在同一候选构建上比较缓存开但锁关/缓存开且锁开。

#### D4.2：重建流程与失败策略

仅对已缓存的公开评价默认首页和统计启用，锁key含namespace、product_id和epoch，与缓存key一一对应；不同商品/代际不共享锁。沿用数据库公开可见性与epoch校验，缓存命中直接返回，不获取锁。

1. 缓存miss后尝试获取RLock，初始锁等待100ms、显式租约2秒。显式leaseTime意味着本方案不依靠watchdog续期；租约与数据库查询预算需在冒烟中核对后冻结。
2. 获取锁后再次读缓存；已由其他实例填好则返回。仍miss才申请原DB门控，执行只读快照查询，在事务结束后写入原epoch缓存key。
3. 未获得锁时在等待结束后再读一次缓存；仍miss返回可重试503，不让所有等待者直接查库。限制客户端重试，不循环续等，不持有DB许可或事务等待Redis锁。
4. 重建异常仍在finally释放自己持有的锁；租约已过期时不得误解锁新持有者。数据库查询设置有界statement/事务预算；获取、等待、超时、租约丢失、重建开始/结束和异常解锁单独计量。
5. Redis连接/命令异常时走原有单实例受限DB回源，不继续依赖失效的重建锁；此分支不宣称跨实例互斥。缓存/锁的失败路径共享原DB门控，避免双重释放许可或额外无界查询。
6. owner暂停超过租约时，另一个实例可能合法获取锁，已经发出的SQL未必能取消，因此恢复期允许短暂重叠。旧owner不得绕过epoch写入新代，释放只能作用于原owner；正常持锁峰值与租约失效窗口分别测量。此锁减少重复重建，不承担订单/资金正确性。

仍由MySQL中的事务epoch负责评价修改与缓存版本关联，Redisson锁负责相同版本重建互斥；锁不替代数据库唯一约束、付款/退款行锁、操作幂等或Agent fence。工作台继续沿用原短期缓存，不把评价收益套给工作台。

#### D4.3：失败测试和完成标准

先用两个实际Commerce实例验证同key冷缓存/TTL到期、不同key、重建异常、owner进程退出、超过租约停顿、重建期间评价修改及Redis断连。测试点在真实DB查询/缓存写入/锁owner处取证，不能只mock RLock为成功。

完成标准：正常有效租约下同key实际并发重建峰值为1；等待者缓存命中或有界拒绝；异常后正常请求可继续填充；进程退出后租约到期可恢复；旧owner不释放新owner锁，旧代回填不影响新代；Redis异常仍受原DB门控保护。性能收益由P3和R矩阵独立对照，不预设下降比例。

### D5：正式评测与归档

功能稳定后按评测方案锁定代码、JAR、配置、种子和评分器。冒烟与正式输出分开；正式批不边测边改。失败先保留原记录，修复后新版本重跑规定范围，不挑成功样本拼成绩。

交付：实现/测试、执行manifest、脱敏逐请求与逐轮结果、SQL计划与计量、故障快照、报告及简历填数表。指标按技术点4/5/7分别归属。重要取舍更新[架构演进](architecture-evolution.md)，仅在接管共享文件后追加；日常进度仍只在todo顶部。

## 5. 验证入口与本次文档记录

可复用的针对性入口：java目录用JDK21执行Maven wrapper，购物车/交易类为CartDatabaseTest、CartApiTest、CheckoutPaymentDatabaseTest、MultiCheckoutDatabaseTest、CheckoutRecoveryDatabaseTest、CheckoutRecoveryLoopTest；权限类为CaseScopeEnforcementTest、InternalScopeEnforcementTest；评价类为ProductReviewCacheIntegrationTest、ReviewWriteLimiterRedisTest。名称与源码都已核对，真正执行时按子步选择，不把本名单当本次已运行。

新脚本按现有Python venv运行pytest/Ruff；API/类型有变化时再跑对应契约与前端测试/构建。只改查询时不为凑数量启动收费Agent质量评测。

2026-10-26原文档准备：已读核心范围/当前记录，检查PurchaseReads、BuyerPurchaseService、CheckoutPayments、CheckoutRecoveryService和SimulatedCheckoutProvider，以及旧查询/退款评测器和报告。确认订单逐条组装与旧脚本固定库名是直接代码事实；当时热点合并为待测可选项。v1.1按用户确认纳入Redisson双实例重建方案，评测同步追加独立对照与失败窗口；此修订未修改业务实现或运行新性能测试。
