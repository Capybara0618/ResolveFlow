# 后端深化验证记录

## B1.1 正式工作台缓存（2026-10-22）

文档与三张静态预期图提交 5f55049 已正常推送 origin/main，远端 SHA 已核实。实现根据 docs/backend-deepening-v1.md，保留四个历史脏文件、原数据和冻结实验。未调用模型、未启动正式业务服务。

现象：网页带 view/query/scope，Controller 选择 workspace，原 Redis 缓存只在 list 使用。修复：两条读路径共享 cache-aside 与 8 并发/100ms 回源门控；workspace 键包含人员/商家/阶段/归属/搜索/游标/页大小，先校验权限和游标；缓存读取/写入在只读 REPEATABLE_READ 数据库事务外。旧 list 行为保留。展示缓存仍 2 秒 TTL，写动作继续查权威状态。

关键失败测试先跑：首轮缺嵌套异常 import 编译失败；修正后4项为3失败/1错误，其中游标异常类型断言不符，另3项证明缓存未调用、重复查询和指标缺失。将游标断言纠正为实际 InvalidCursorException，实施缓存并增加事务边界测试后7项通过。真实 Redis 增加正式 workspace 请求命中/筛选与人员隔离检查。

实际环境 Java21（C:/Users/hjn/.jdks/jdk-21.0.12.1+1），Docker Testcontainers 独立 MySQL8.4/Redis7.4，不操作演示数据库。java 目录命令：

```powershell
$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'
./mvnw.cmd -B -pl case-service -am test '-Dtest=WorkspaceQueueCacheTest' '-Dsurefire.failIfNoSpecifiedTests=false'
./mvnw.cmd -B -pl case-service -am spotless:apply '-DspotlessFiles=.*ReviewQueueService.java,.*WorkspaceQueueCacheTest.java,.*RedisReviewQueueCacheIntegrationTest.java' test '-Dtest=WorkspaceQueueCacheTest,ReviewQueueBackpressureTest,ReviewQueueCacheTest,RedisReviewQueueCacheIntegrationTest,MerchantWorkspaceApiTest,ReviewQueueApiTest' '-Dsurefire.failIfNoSpecifiedTests=false'
```

最后30项通过/0失败/0跳过（48.610秒），包含当前工作台HTTP实库5项、真实Redis5项、旧队列HTTP11项、旧缓存2项、回源保护2项、新workspace5项。原始日志仅忽略tmp/backend-b1-*.log。格式命令曾误用glob导致regex错误、再用管道正则被Windows cmd解释，最终使用逗号分隔的无管道正则成功，只格式化本步3文件。git diff --check 通过。

未运行：正式页面压测/延迟收益、新功能页面。另发现正式本机复用的 reviewer_demo 启动固定禁用缓存，独立 Compose 尚无 Redis；后续 B1.3 需要增加本项目 Redis 与启动接线，当前不能称日常启动已启用。商品批量查询 B1.2、评价 B2、付款恢复 B3 均未完成。旧实验报告不重算或修改hash。
