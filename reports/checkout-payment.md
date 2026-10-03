# 第三批模拟付款验证

2026-10-03。正式协议见[付款与本人交易](../docs/simulated-checkout-payment.md)。Commerce领域及Case/Commerce接口已完成，正式页面仍在集中验证，不能据本段接口结果宣称第三批网页验收完成。

文件：CheckoutWire、V11__checkout_payment.sql、CheckoutPayments、SimulatedCheckoutProvider、ShoppingService、CheckoutPaymentDatabaseTest。追加V11，保留旧迁移、订单、退款及Agent锁；本地持久模拟收据，无真实支付、模型调用或演示库写入。

实际命令（Java21、真实MySQL8.4 Testcontainers）：`java/mvnw.cmd -f java/pom.xml -pl commerce-service -am -Dtest=CheckoutPaymentDatabaseTest,ShoppingDatabaseTest,OrderLineReadServiceDatabaseTest -Dsurefire.failIfNoSpecifiedTests=false test`。最终33 passed/0 skipped（新付款13、原草稿8、原订单读取12）。定点Spotless apply与git diff --check通过。

覆盖：同key/并发付款一次、原金额/名称/数量、paid_at与收据一致、0已退/预留与FREE槽、无物流、付款/取消竞争、取消幂等、到期拒绝、UNKNOWN调用前中断原键恢复、收据持久后丢响应仅查询恢复、明确失败再付与过期失败拒绝、篡改收据金额不发布、跨复合归属拒绝、发布中途主键冲突整事务回滚后复用原尝试。测试还检查provider调用时没有包围它的业务事务。

失败与修复：初始未实现领域的有效RED为11失败（2断言失败/9未实现异常）；V11实库迁移通过。首实现将MySQL DATETIME对象误当Timestamp，改为显式UTC转换LocalDateTime后新13/旧草稿8通过。组合回归发现新测试留下成功订单污染原商家全量读取断言（2失败）；在可丢弃测试库按本类独立customer范围清理自身夹具后33全部通过，原断言未删改。原始日志保留忽略目录tmp/checkout-payment-*.log，不提交。

后续接口子步：新增付款/原尝试查询/取消/本人列表/详情，Case/Commerce各5核心路由（总49/17，Agent仍7）。当前买家/启用复合绑定，Agent/Case普通读凭证禁止访问私有交易；严格空公共请求不能注入金额、归属或provider结果。新旧订单按draft:/order:命名空间合并、已发布只出现一次；跨店游标绑定buyer、归属与筛选，一个店故障拒绝整页。历史名称/单价/插画缺失保持null。共享wire、两个OpenAPI及fixture同步。

实际最终接口回归：Maven指定CheckoutApiTest、CheckoutPaymentDatabaseTest、ShoppingDatabaseTest、ShoppingApiTest、ShopApiTest、CheckoutBuyerApiTest、BuyerPurchaseServiceTest、CommerceShoppingClientTest、OrderLineReadServiceDatabaseTest，9类51 passed/0 skipped；Python core_routes/platform_buyer/shopping/checkout_payment四文件108 passed。定点Spotless apply通过，原断言保留。首次新API有效RED为2个404；契约片段错误放到paths外、缺operationId及时间fixture零微秒被Java正规化、URI冒号编码断言错误已修复复跑，未删除对应检查。

未运行：正式浏览器付款、保留演示库升级与集中真实HTTP/桌面全链验收；下一子步继续现有未提交前端。第四批购物车/多行、第五批履约/未发货退款政策未开始。
