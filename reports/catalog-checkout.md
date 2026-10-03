# 商品与直接购买验证

2026-10-03，第二批后端已完成。正式规格见[商品与草稿](../docs/catalog-checkout.md)，对应目标M01–M04/M06；公共目录、SKU报价、可信平台买家创建/本人读取独立待支付草稿已实现，无支付发布或新退款。前端与真实演示环境的验证接续同一功能批次，未验证项不算完成。

## 本次实际命令

- Java21：`java/mvnw.cmd -f java/pom.xml -B -ntp -pl commerce-service,case-service -am -Dtest=CommerceShoppingClientTest,ShopApiTest,ShoppingApiTest,ShoppingDatabaseTest,InternalScopeEnforcementTest,PlatformBuyerApiTest,JwtCodecTest -Dsurefire.failIfNoSpecifiedTests=false test`：7类48 passed/0 skipped（共享16、Commerce17、Case15）。日志仅保留忽略目录`tmp/shopping-final-java.log`。
- `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_platform_buyer.py agent/tests/unit/test_contracts_shopping.py -q`：97 passed。旧路由/权限/订单schema断言保留；仅增加正式授权的7条Case/7条Commerce路由和5条匿名目录例外。
- 本批Java文件定点Spotless apply，两个Python文件Ruff通过。前端初轮116 passed/17文件及vue-tsc/Vite build通过，真实浏览器与最终修改后的前端验证待接续。

## 覆盖与失败

真实MySQL迁移V10和数据库测试覆盖两店目录、字面搜索、分页、SKU/数量、店铺不匹配、改价、下架、同键重放/异载荷冲突、并发仅一草稿、到期以及无订单/账本发布。Case HTTP验证公共目录、当前买家/旧客户/管理员边界、可信复合映射、客户端金额拒绝、本人草稿404；客户端测试检查实际服务JWT专用scope以及共享fixture序列化往返、409与503区分。

第一条失败回归在目录不存在时404。初次权限测试误用默认MOCK上下文，过滤器未执行而收到400；改为与已有InternalScopeEnforcementTest一致的真实随机端口，验证Agent凭证403。新增YAML片段分别dump复用锚点导致解析失败，改为无锚点输出，复跑；其后旧匿名断言与内部401/403声明各一失败，补精确目录白名单及所有内部拒绝声明，97项复跑通过。没有删除权限断言。创建事务使用READ_COMMITTED，避免首次幂等查询建立旧快照后误用锁前价格。

## 未运行及边界

未运行收费模型、模拟支付、取消/支付竞争、多行资金、购物车、发货/未发货退款、全商城最终视觉与全仓评测。草稿15分钟到期是读取投影，不承诺已开发支付后台或自动过期任务。现有用户/已支付订单/资金/政策/Agent不因本批规格改变。商品为明确标记的合成目录，没有真实销量/库存或上游交易主张。
