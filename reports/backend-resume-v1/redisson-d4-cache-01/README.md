# D4.2：评价缓存重建锁接线

2026-10-26。ProductReviewReadCache默认首页先权威publicEpoch，再读原epoch缓存。命中不加锁；miss用ReviewRebuildLock的RLock(100ms等待/2000ms租约)，owner二次查缓存，仍缺失才用原8/100ms本机DB门控；waiter再读一次仍空则ReadBusy映射503，不旁路查库。Redis读/加锁异常走原门控回源，业务异常原样传播。epoch和page调用分别计数，inflight/peak与重建/锁结果、等待计时及DEBUG起止事件在实际调用点记录。

重建事务显式1秒预算，事务及本机DB许可释放后才检查锁owner和写30秒缓存；失去租约跳过回填，finally只释放当前持有者。旧epoch不回填新代。100ms等待不是含网络所有开销的严格端到端上限；Redis失败回源也不宣称跨实例互斥。缓存/锁开关独立，保留锁关闭B条件。

新增测试先缺ReviewRebuildLock编译失败；首实现因兼容构造器null重载歧义编译失败，显式类型修复。16相关测试通过（3现有真实MySQL+Redis缓存、7评价数据库、5缓存单元、1真实Redis兼容），再加过期owner不写/不误解锁测试后的单元6通过，独立用例合计17，重复执行单列。Spotless通过。只Testcontainers临时资源，无原业务/模型/费用。

路径：tmp/backend-d4-cache-before.log / after.log / after-02.log / unit-final.log；java目录mvnw.cmd -B -pl commerce-service -am test -Dtest=ProductReviewReadCacheTest,ProductReviewCacheIntegrationTest,ProductReviewDatabaseTest,ReviewRebuildRedisTest -Dsurefire.failIfNoSpecifiedTests=false。本步尚不等于真实双进程R矩阵或D4完成。
