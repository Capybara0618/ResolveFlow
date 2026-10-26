# D4：工作台查询、Redis保护与Redisson重建

2026-10-26。按[开发方案v1.1](../../../docs/backend-resume-development-v1.md)完成D4功能实施与验收；第4/5条[冻结正文](../../../docs/resume-backend-trade-refund-frozen-20261026.md)、Agent/RAG/Harness及个人PDF保持。D5的正式R120及HTTP性能矩阵尚未执行，不提前给第7条填p95或缓存降幅。

## 已交付行为

- 独立Redisson core4.7.0客户端，未引入starter或替换Spring Data Redis。依赖树保留Boot4.0.8、Netty4.2.17.Final、Lettuce6.8.2；两个客户端指向同一Redis数据库。仅缓存及锁均开启才创建，lazy启动，100ms连接/命令、零客户端重试、小连接池，正常关闭回收。
- 公开评价默认10条首页继续先读MySQL权威epoch，命中不加锁；miss按namespace/product/epoch获取RLock，等待100ms、显式租约2秒。owner二次查缓存后才申请本机8许可/100ms的DB门控；waiter再查仍空则503，不绕过锁各自查库。
- 只读publicPage/独立publicEpoch事务均设1秒预算；这是Spring事务/JDBC查询预算，不承诺任意进程冻结时硬中止SQL。Redis读写与锁等待均在业务数据库事务外，回填也在本机DB许可释放之后。失去租约不回填、不误解锁新owner，旧epoch不能污染新代。
- Redis异常走原本机门控回源，业务404/数据库错误不被宽泛catch当成缓存异常重读；锁获取/等待/拒绝/lease_lost/异常释放、缓存二查、epoch/page调用、DB及重建inflight/peak在实际调用点计量，DEBUG记录重建起止。database.reads/calls是业务方法调用数，不能当SQL执行数；命中仍有epoch查询，正式D5应另在JDBC计SQL。
- 资金/授权路径不使用该锁。实例各8许可，总许可最多16；Redis故障或租约过期可以出现重建重叠，不宣称全局互斥、全局8或资金锁。

[D4.1客户端兼容](../redisson-d4-compat-01/README.md)及[D4.2缓存接线](../redisson-d4-cache-01/README.md)已分别提交fb01f141、a7e1885a并正常推送，本报告补实际双业务进程与工作台证据。

## 两个Commerce进程的实际证据

两个独立Java进程共用新Testcontainers MySQL8.4/Redis7.4，真实生产Controller、服务JWT、缓存、查询、Spring事务及RLock。进程启动器、指标读入口和查询完成后的门控只在test classpath；打包检查确认正式JAR没有LabProcess或故障路由。门控位于publicPage事务完成后、缓存写入前，不持业务事务，但为固定实验窗口会延长业务DB许可占用。记录的business_load_window峰值包含这个人为停顿，不能叫实际SQL同时执行峰值。

B=缓存开/锁关，C=缓存开/锁开。开发验收共16个条件场景（两条件各8种），不称为预冻结正式120轮，也不把一次功能结果推成总体故障成功率。

| 窗口 | 实际结果 |
| --- | --- |
| 冷缓存 | B两个进程均进入加载，峰值2；C仅一个加载，另一进程503，释放owner后命中 |
| TTL到期/30请求突发 | 实际等31秒且Redis key已过期；B为30个200，26次到期后加载；C为1个200/29个503，仅一次到期后加载，随后10次读均正常 |
| 不同商品 | 第一商品owner仍被门控阻塞时，另一个商品已成功返回，锁不按全站串行 |
| 查询后的明确异常 | 首次500保留，finally释放后另一实例成功重建；不是生产SQL坏句模拟 |
| owner真实退出 | 仅终止本轮启动并记录的PID；B恢复约51ms，C约1746ms（原租约到期），未重启Redis或手动删锁 |
| 超租约暂停 | NtSuspendProcess暂停实际owner，超过2秒后另一实例获得锁，再恢复旧进程；C旧owner返回后新锁仍存在，旧回填及误解锁均未发生 |
| 评价修改 | 旧查询快照完成后暂停，通过生产reviews.reply提交回复推进epoch；另一实例读到新回复，旧owner再回填不影响新代读取 |
| Redis命令超时 | CLIENT PAUSE后32请求加原owner，两个实例许可峰值各8、结束归零；本组全部33个200，记录超时降级，不虚构503；解除后恢复 |
| Redis断连 | 实际停本轮Redis容器，应用继续权威有限回源；按原端口启动后，5秒观察上限内重新填充缓存并归零 |

TTL组的26→1是本次**受控阻塞**下的加载次数变化，不能只写“减少96%”：C的29个503必须同时展示。它证明互斥和有界等待，正式性能结论还需无故障热态、冷启动成功率及拒绝率配对。恢复单次耗时只用于解释显式租约，不作为p95或生产SLA。

[离线审计](summary.json)从两个进程实际page_start/end事件合并计算窗口：冷态B/C为2/1；TTL组包括初次预热填充的总加载27/2，窗口峰值14/1。Redis故障回源不计为“锁协调重建成功”；DB许可峰值仍需单独看gauge。数据与原失败都保留，不把非预定窗口称R120正式通过。

## 两个Case进程的Lua窗口

两个实际Case JVM共用新的Case MySQL和Redis，走正式身份校验、Controller与ReviewWriteLimiter；接收端验证服务JWT并记录真实到达的Commerce HTTP。接收端返回明确合成评价响应，因此证明的是入口限流与下游调用边界，不称真实Commerce评价写库或完整跨服务业务验收。

同一买家WRITE、同一商家REPLY各12请求，同时均分两个Case；每种动作每窗口合计6个200/6个429。实际等待61秒过期后重复，总共三个真实60秒窗口：72请求中36放行/36限流，下游只收到36次；另一商家账号正常放行独立计2次。Redis PAUSE时503且下游计数不增，解除后可继续。没有删限流key或缩短生产窗口刷次数。

WRITE与REPLY在HTTP层对应不同合法角色/账号，并非同一个账号能执行两种动作；动作key隔离另由已有同principal组件检查验证。另一账号控制与Redis故障不并入36/36的窗口分母。[summary](summary.json)同时保留38次实际下游调用。程序当前串行建立两种动作的各自并发突发，不宣称两种动作都在同一个起跑屏障。

## 工作台SQL及索引取舍

实际正式workspace服务路径，独立Case MySQL生成20000条合成工单/两商家/4000待审；同时间戳、分配/未分配、状态、精确及文字查询。七组：待审PUBLIC首页/下一页、MINE、UNCLAIMED、SEARCH、第二商家、ALL。每组20行及counts/动作/归属按生产读取核对；每页业务Mapper实际执行3次（汇总、页面、按页动作），另对每次语句增加EXPLAIN ANALYZE诊断，因此试跑的数据库总执行还包含3次EXPLAIN，不能称整个试跑只执行3条SQL。

实际待审首页和下一页命中原idx_case_review_queue(merchant,status,updated_at DESC,case_id DESC)，无需复制旧list索引。计数仍读取本店匹配数据；MINE及ALL可排序，模糊LOCATE仍有扫描。当前未增加迁移或强制索引；A/B没有新增工作台索引差异，D5 P1应如实将SQL A/B视为同一路径，仅评估缓存增益，不能用无关劣质基线制造提升。已有Redis工作台键隔离/真实TTL/断连与队列API权限回归单列验证。

## 验证、失败及保留范围

最终Commerce评价/API/缓存/数据库/真实Redis兼容20项通过；Case限流双进程及原工作台缓存/背压/Lua11项通过；真实Redis工作台与队列API另16项通过；工作台SQL1项、两个Commerce方法各1项通过，此前共50个独立用例（重复冒烟不重复加总）；收尾另加原商城8项，共58个独立用例。新增三个离线篡改检查拒绝许可峰值9、限流放行过量、旧owner误释放新锁；0真实模型/费用。

开发失败记录保留：双进程首次编译因测试基类MYSQL访问权限及Path.isDirectory误用失败；下一次冷连接预热失败，仍未到业务窗口，根因未证明；改显式loopback、ActiveProcessorCount=2和有截止预热后正常。随后合成商品INSERT未列出列名碰到新增version列而失败，补明确列清单；扩展组Windows PowerShell引号丢失导致暂停辅助编译失败，改UTF-16LE EncodedCommand后实际暂停成功。原failure/已完成场景保留，均为开发试跑，不重写为通过。

收尾为防止共享Testcontainers JVM内新商品/2万工单污染后续测试，增加仅本类显式合成ID/商家的fixture清理，不连接原库；并将两个Commerce验收方法与原商城目录测试同批检查，两个Commerce方法与商城8项合计10通过，原目录测试未被污染；工作台清理独立回归在同一生产读取路径复核。一次离线脚本未显式UTF-8读取被Windows默认GBK拒绝、一次Ruff闭包绑定报错均已修正；不影响原实验字节。

实际执行入口：java目录JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1。

```powershell
./mvnw.cmd -B -pl commerce-service -am test '-Dtest=ReviewCacheDualProcessTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dresolveflow.d4.output=E:/Code/Agent+Backend/tmp/d4-dual-faults-02'
./mvnw.cmd -B -pl commerce-service -am test '-Dtest=ReviewCacheDualProcessTest#realTtlDifferentKeysBurstAndRedisDisconnectRecover' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dresolveflow.d4.extra=E:/Code/Agent+Backend/tmp/d4-dual-extra-01'
./mvnw.cmd -B -pl case-service -am test '-Dtest=ReviewLimiterDualProcessTest,WorkspaceQueueCacheTest,ReviewQueueBackpressureTest,ReviewWriteLimiterRedisTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dresolveflow.d4.limiter=E:/Code/Agent+Backend/tmp/d4-limiter-01'
./mvnw.cmd -B -pl case-service -am test '-Dtest=WorkspaceSqlPlanDatabaseTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dresolveflow.d4.workspace=E:/Code/Agent+Backend/tmp/d4-workspace-sql-01.json'
./mvnw.cmd -B -pl case-service -am test '-Dtest=RedisReviewQueueCacheIntegrationTest,ReviewQueueApiTest' '-Dsurefire.failIfNoSpecifiedTests=false'
```

旧输出已存在时脚本拒绝覆盖，复核必须使用新目录。测试main在test classpath，不是正式启动脚本。最终限定Spotless、Commerce/Case package通过，package显式跳过测试不重复计为通过；正式JAR无测试门控。构建、源码、依赖和各次日志hash见归档manifest；执行快照是开发过程事后保存，未冒充正式预冻结。

D4功能完成后进入D5：按原评测协议先冻结数据、JAR、参数和评分器，再执行R01–R06两条件120轮及48正常/15故障HTTP窗口等正式矩阵。D4当前16个开发条件场景及诊断延迟不代替这些数字，第7条性能值仍留空。

## 功能验收收尾

带本类夹具清理的两个Commerce方法与原商城8项合计10通过/0跳过（204秒），结果新存d4-extra-final-01、d4-dual-final-01，旧开发数据不替换。它们是修正测试隔离后的复核，不追加到16个开发场景或正式R120分母。工作台也仅清理本类D4-WS1/WS2工单，保留原Testcontainers数据及其他夹具；所有清理仅针对自有临时库，不授权也未连接原业务库。

[原字节证据包](evidence.tar.xz)及[逐文件hash](archive-index.json)保留成功/失败开发输出、SQL计划、进程PID/事件、源码快照和manifest；原JVM日志仅本机tmp留存并记录hash，不提交原始日志/数据库/令牌。证据包解压到新的tmp目录后，完整离线审计与summary一致；三个内存篡改反例均被拒绝。源码格式化、版本、构建与最终停机核验另见manifest/stopped.json。

最终工作台清理回归1项通过（98秒），七组完整投影与首轮一致。收尾合计58独立Java用例及3个离线反例检查通过，限定Spotless/两服务构建通过；未跑全项目或正式性能矩阵。211个结构化文件压缩后逐字节校验、解压完整审计一致。首次解压结果比较因Python状态计数字典的整数key与JSON字符串key不同而失败；按JSON序列化规范归一后通过，原文件字节未改，首包保留tmp/d4-archive-first-roundtrip.tar.xz，不把这次打包检查失败隐去。

[最终manifest](manifest.json)关联58用例来源、实际日志hash/构建hash、前后源码与镜像ID；[停机核验](stopped.json)确认无带本轮标识的Java进程、31个已观察应用端口关闭，核验时无运行容器。临时Testcontainers已回收，原业务环境未启动/卷保持；原四历史脏文件未夹带。独立候选Case/Commerce JAR留tmp/backend-resume-candidates/d4-functional-01/，后续正式评测需先冻结最终环境与输入。

离线复核（从仓库根目录，先将evidence.tar.xz解压到新的自有tmp目录）：

```powershell
agent/.venv/Scripts/python.exe reports/backend-resume-v1/d4-functional-01/audit.py <解压目录> tmp/d4-new-audit-output.json
agent/.venv/Scripts/python.exe reports/backend-resume-v1/d4-functional-01/verify_audit.py <解压目录> tmp/d4-new-mutation-checks.json
```
