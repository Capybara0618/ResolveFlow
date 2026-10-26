# D4.1：Redisson兼容与显式租约

2026-10-26。独立org.redisson:redisson:4.7.0，不使用starter，Spring Data Redis/Lettuce继续缓存和Lua。前后依赖树证明Boot4.0.8、Lettuce6.8.2.RELEASE、Netty4.2.17.Final保持；新增Redisson传递依赖单列，不重选现有栈。

新ReviewRebuildRedisTest先缺配置类编译失败，补实现后1通过/0跳过，真实Testcontainers Redis7.4、两个独立RedissonClient及Lettuce连接。验证同key排斥、有界等待、2秒显式租约到期、旧owner解锁被拒且新owner仍持有、Spring Data Redis读写共存及两个客户端显式关闭；不是两个业务进程或R01–R06矩阵。

配置独立Bean仅cache+lock同时启用创建，lazy连接、100ms连接/命令、零重试、数据池1/4、订阅池1/2、两个工作及Netty线程。原cache默认关闭保持；缓存开启时新锁开关默认true，业务接入尚待下一步。生命周期destroyMethod shutdown。

实际java目录Java21：mvnw.cmd -B -pl commerce-service -am test -Dtest=ReviewRebuildRedisTest -Dsurefire.failIfNoSpecifiedTests=false，日志tmp/backend-d4-compat-before.log / after.log；dependency:tree前后及限定Spotless通过。只临时Redis，自动回收，无原库/模型/费用。第4/5冻结和四历史脏文件保持。

参考：[官方4.7.0发布](https://github.com/redisson/redisson/releases/tag/redisson-4.7.0)、[配置](https://redisson.pro/docs/configuration/)、[锁语义](https://redisson.pro/docs/data-and-services/locks-and-synchronizers/index.html)。实际版本/API以本锁定构建验证为准。
