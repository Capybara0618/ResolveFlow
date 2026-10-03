# 商品与直接购买验证

2026-10-03，第二批已集中完成。正式规格见[商品与草稿](../docs/catalog-checkout.md)，对应目标M01–M04/M06；公共目录、SKU报价、可信平台买家创建/本人读取独立待支付草稿已实现，无支付发布或新退款。桌面页面按目标图的结构与字体实现，商品采用固定SVG插画；不是逐像素复刻生成摄影。模拟付款及多行尚未实施。

## 本次实际命令

- Java21：`java/mvnw.cmd -f java/pom.xml -B -ntp -pl commerce-service,case-service -am -Dtest=CommerceShoppingClientTest,ShopApiTest,ShoppingApiTest,ShoppingDatabaseTest,InternalScopeEnforcementTest,PlatformBuyerApiTest,JwtCodecTest -Dsurefire.failIfNoSpecifiedTests=false test`：7类48 passed/0 skipped（共享16、Commerce17、Case15）。日志仅保留忽略目录`tmp/shopping-final-java.log`。
- `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_platform_buyer.py agent/tests/unit/test_contracts_shopping.py -q`：97 passed。旧路由/权限/订单schema断言保留；仅增加正式授权的7条Case/7条Commerce路由和5条匿名目录例外。
- 本批Java文件定点Spotless apply，两个Python文件Ruff通过。前端116 passed/17文件及vue-tsc/Vite build通过；最终CSS修复后再次验证。

## 覆盖与失败

真实MySQL迁移V10和数据库测试覆盖两店目录、字面搜索、分页、SKU/数量、店铺不匹配、改价、下架、同键重放/异载荷冲突、并发仅一草稿、到期以及无订单/账本发布。Case HTTP验证公共目录、当前买家/旧客户/管理员边界、可信复合映射、客户端金额拒绝、本人草稿404；客户端测试检查实际服务JWT专用scope以及共享fixture序列化往返、409与503区分。

第一条失败回归在目录不存在时404。初次权限测试误用默认MOCK上下文，过滤器未执行而收到400；改为与已有InternalScopeEnforcementTest一致的真实随机端口，验证Agent凭证403。新增YAML片段分别dump复用锚点导致解析失败，改为无锚点输出，复跑；其后旧匿名断言与内部401/403声明各一失败，补精确目录白名单及所有内部拒绝声明，97项复跑通过。没有删除权限断言。创建事务使用READ_COMMITTED，避免首次幂等查询建立旧快照后误用锁前价格。

## 未运行及边界

未运行收费模型、模拟支付、取消/支付竞争、多行资金、购物车、发货/未发货退款、全商城最终视觉与全仓评测。草稿15分钟到期是读取投影，不承诺已开发支付后台或自动过期任务。现有用户/已支付订单/资金/政策/Agent不因本批规格改变。商品为明确标记的合成目录，没有真实销量/库存或上游交易主张。

## 真实网页与历史保留

实际执行`demo.ps1 stop`及`demo.ps1 -NoBrowser`，三个JAR构建、原隔离卷保留、V10迁移、只读Agent和5174页面启动通过。浏览器最初在重启尚未结束时连接拒绝，恢复服务后旧标签停留错误页，使用同一浏览器的新标签恢复，未改变防火墙或安全设置。

正式页面访客浏览→耳机详情→登录demo-buyer后返回商品→两件报价65800分→提交草稿；再经台灯搜索→拾光家居→台灯报价12900分→提交第二草稿。两份均WAITING_PAYMENT，没有已支付订单/账本/退款。真实接口27项覆盖匿名目录、分类/搜索、数量/参数、旧报价409、客户端金额400、旧客户/管理员403、本人读取/同键重放/冲突及内部异归属404、Agent读及伪checkout部署403，见[脱敏证据](catalog-checkout/verification.json)。初次保留检查试图排序dict失败，改为规范JSON排序后全部重跑通过，不算业务失败。

原34工单/5负责人/34政策钉住/6政策/17授权/9退款操作/36账本/92run/14账号/36订单全部逐行状态、版本、hash、归属及资金不变（run校验状态/version/fence，不把未捕获的旧budget_spent当核对项）。未调用收费模型。只新增两份合成草稿，未重置或删除。

六视图（首页、搜索、店铺、商品、确认、草稿）×1280/1440/1680共18组无水平溢出，指定主事实均≥16px，价格27–34px，见[桌面测量](catalog-checkout/desktop-layout.json)。实际发现旧工作台强样式将商品价格降至14px、数量label13px及分类按钮误染蓝色，限定商城样式后复测修正；原售后组件不继承商城button样式。截图：[首页](catalog-checkout/home.png)、[搜索](catalog-checkout/search.png)、[店铺](catalog-checkout/store.png)、[商品](catalog-checkout/product.png)、[确认](catalog-checkout/checkout.png)、[待付款](catalog-checkout/draft.png)。原订单/售后入口可读取，尚未包含草稿聚合列表，第三批接入。店铺筛选保留本店范围，页面切换清除旧目录，访客登录返回原商品；迟到响应及未知创建沿原键恢复有前端回归。
