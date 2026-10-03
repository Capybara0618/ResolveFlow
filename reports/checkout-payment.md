# 第三批模拟付款验证

2026-10-03。正式协议见[付款与本人交易](../docs/simulated-checkout-payment.md)。当前仅完成Commerce领域子步，尚未接付款HTTP入口、本人交易列表或正式页面，不能据本报告宣称第三批完成。

文件：CheckoutWire、V11__checkout_payment.sql、CheckoutPayments、SimulatedCheckoutProvider、ShoppingService、CheckoutPaymentDatabaseTest。追加V11，保留旧迁移、订单、退款及Agent锁；本地持久模拟收据，无真实支付、模型调用或演示库写入。

实际命令（Java21、真实MySQL8.4 Testcontainers）：`java/mvnw.cmd -f java/pom.xml -pl commerce-service -am -Dtest=CheckoutPaymentDatabaseTest,ShoppingDatabaseTest,OrderLineReadServiceDatabaseTest -Dsurefire.failIfNoSpecifiedTests=false test`。最终33 passed/0 skipped（新付款13、原草稿8、原订单读取12）。定点Spotless apply与git diff --check通过。

覆盖：同key/并发付款一次、原金额/名称/数量、paid_at与收据一致、0已退/预留与FREE槽、无物流、付款/取消竞争、取消幂等、到期拒绝、UNKNOWN调用前中断原键恢复、收据持久后丢响应仅查询恢复、明确失败再付与过期失败拒绝、篡改收据金额不发布、跨复合归属拒绝、发布中途主键冲突整事务回滚后复用原尝试。测试还检查provider调用时没有包围它的业务事务。

失败与修复：初始未实现领域的有效RED为11失败（2断言失败/9未实现异常）；V11实库迁移通过。首实现将MySQL DATETIME对象误当Timestamp，改为显式UTC转换LocalDateTime后新13/旧草稿8通过。组合回归发现新测试留下成功订单污染原商家全量读取断言（2失败）；在可丢弃测试库按本类独立customer范围清理自身夹具后33全部通过，原断言未删改。原始日志保留忽略目录tmp/checkout-payment-*.log，不提交。

未运行：正式浏览器付款、保留演示库升级、HTTP鉴权/契约/本人分页与全链验收；接下一个子步完成。第四批购物车/多行、第五批履约/未发货退款政策未开始。
