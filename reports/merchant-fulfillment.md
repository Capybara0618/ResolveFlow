# 第五批：商家模拟履约与购物政策验证

2026-10-03，依据[第五批规格](../docs/merchant-fulfillment.md)，复用第四批5884d80/fbd5c73/c97685e及资金74df827。本文记录证据，当前进度只看tasks/todo.md顶部；第五批尚未整批完成。

## 履约领域子步

追加V14 order_fulfillment及仅已有已付checkout、所有行无旧物流的NOT_SHIPPED初始化；六个旧政策、原历史物流/事件和账本不更新。CheckoutPayments成功发布同事务创建每行NOT_SHIPPED/UNKNOWN、ORDER_PAID与履约头；付款UNKNOWN仍不发布任何订单。MerchantTradeService提供商家范围、真实全行投影、状态过滤/keyset游标绑定、本人履约及首次整单模拟发货领域。FulfillmentWire、两份core OpenAPI新增七个共享闭合Schema/fixture；本子步没有新增HTTP路由（Case53/Commerce21/Agent7保持）。

发货锁序账本→履约头→排序行槽，全行事件与IN_TRANSIT/version2原子写入。占用/已退/缺槽/异常物流拒绝；原key/actor/expected_version重复返回原结果，异内容或再次发货拒绝；不生成签收/丢失或真实运单，不改Case输入、审批权限或金额。原付款/多行测试只追加新子表测试清理及明确新未发货事实断言，保留原资金/失败/UNKNOWN断言。

实际命令（Java21，C:/Users/hjn/.jdks/jdk-21.0.12.1+1）：

```powershell
./java/mvnw.cmd -f java/pom.xml -pl commerce-service -am '-Dtest=FulfillmentDatabaseTest,CheckoutPaymentDatabaseTest,MultiCheckoutDatabaseTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./java/mvnw.cmd -f java/pom.xml '"-DspotlessFiles=.*(FulfillmentWire|MerchantTradeService|CheckoutPayments|FulfillmentDatabaseTest|CheckoutPaymentDatabaseTest|MultiCheckoutDatabaseTest)\.java"' spotless:apply
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_fulfillment.py agent/tests/unit/test_contracts_cart_checkout.py agent/tests/unit/test_contracts_core_routes.py -q
agent/.venv/Scripts/python.exe -m ruff check agent/tests/unit/test_contracts_fulfillment.py
git diff --check
```

实际Java三类33 passed/0 skipped（履约8、原付款14、多行11），真实MySQL/Flyway14。八项履约覆盖首次/重放/异actor与key、跨店/本人/历史已签收、占用/已退/旧版本、多行第二事件失败全回滚及原键恢复、并发原键只有一套事件、账本锁等待后见退款占用、缺槽/异常版本、状态/商家游标与全部商品。退款竞争测试以真实短事务在相同账本锁上写合成预留，领域测试之外不产生真实Case授权，不能宣称退款全链已验收。Python三文件97 passed，九项新协议覆盖严格成员、模拟标识、缺失历史与不接受自报主体；Spotless/Ruff/diff通过。

失败与修复：RED为新类未实现编译失败。首轮28项2失败/13错误，因旧测试清理未删除新增shipment依赖、旧“新订单没有shipment”断言和JDBC Map DATETIME为LocalDateTime；修正限定测试范围清理、明确断言NOT_SHIPPED/UNKNOWN/ORDER_PAID、UTC转换。第二轮33项31通过/2失败，其中并发原键返回过期NOT_SHIPPED揭示RR在归属读取后建立旧快照；发货短事务改READ_COMMITTED，在账本/履约/槽锁下读最新事实，修复预留与原回执可见性，不去掉并发或资金断言。最终33项通过。第一次定点格式命令被cmd拆分管道，改给mvnw保留参数外双引号；Ruff长行已折行。所有故障仅临时Testcontainers，不触碰原演示库。

首次暂存检查还揭示新fulfillment.json在Windows写出CRLF，git将其报为尾部空白；9fea0ec之后单独规范为LF并正常修复提交，不amend/重写历史。公开JSON内容不变，diff检查通过后才一同正常push。

未运行/尚未实施：本子步未接Case/Commerce新增管理员/本人HTTP、网页M09–M11、购物政策导入/索引及新调查规则，未部署V14到演示库、无浏览器发货/新购买/退款/工单/模型调用。仍保留上一批5174只读演示。领域验证后独立精确commit/正常push，再继续本批接口与政策、网页、保留数据集中验收；旧工程/verify/Commerce退款测试/草图/历史日志不夹带。

## 管理员交易与本人履约接口子步

2026-10-03，领域9fea0ec及LF修复b8887b6已正常推送。新增Case四条公共接口与Commerce四条私有接口，core路由Case57/Commerce25/Agent7。商家管理员可按状态分页、读完整订单、按观察版本与原键首次整单模拟发货；平台买家只读本人已付交易履约。持久身份决定merchant/customer/actor，不能以请求自报主体跨店。专员、旧客户和Agent均不能使用管理员发货接口；新增commerce:fulfillment只给Case，Agent原tool credential保持两个只读scope。本人履约使用Case checkout范围，服务故障503，未找到404而非空结果。共享wire严格拒绝小数、字符串及溢出版本号，不修改全局Jackson设置。

实际命令（Java21）：

```powershell
./java/mvnw.cmd -f java/pom.xml -pl commerce-service,case-service -am '-Dtest=MerchantTradeApiTest,FulfillmentDatabaseTest,CheckoutPaymentDatabaseTest,MultiCheckoutDatabaseTest,CartApiTest,CartBuyerApiTest,CheckoutBuyerApiTest,CommerceShoppingClientTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./java/mvnw.cmd -f java/pom.xml -pl case-service -am '-Dtest=CommerceShoppingClientTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./java/mvnw.cmd -f java/pom.xml -pl commerce-service,case-service -am '-Dtest=MerchantTradeApiTest,CommerceShoppingClientTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./java/mvnw.cmd -f java/pom.xml '"-DspotlessFiles=.*(MerchantTradeController|MerchantTradeApiTest|CommerceShoppingClient|CommerceShoppingClientTest|ServiceTokenFilter|ServiceScopes|FulfillmentWire)\.java"' spotless:apply
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_fulfillment.py agent/tests/unit/test_contracts_cart_checkout.py agent/tests/unit/test_contracts_cart.py agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_checkout_payment.py -q
agent/.venv/Scripts/python.exe -m ruff check agent/tests/unit/test_contracts_fulfillment.py agent/tests/unit/test_contracts_core_routes.py
git diff --check
```

首轮Java九类56 passed/0 skipped，追加客户端第七项后7 passed；共57个不同测试。严格版本补强后接口与客户端14项复测通过。Commerce临时MySQL真实付款/发货与安全过滤、Case真实持久登录和模拟私有依赖、客户端真实HTTP序列化分别验证，不冒充正式网页链路。覆盖管理员可信绑定、异店/异买家拒绝、非管理员禁止、原键恢复、无效版本/自报字段拒绝、依赖503，以及全部新RPC的令牌subject/scope和类型。Python首轮115 passed/2 failed因两条本人履约路由缺少规格Authority文本；补齐来源描述，保留旧deferred guards仅排除已实现的两条精确路径，最终117 passed。定点Spotless、Ruff和差异检查通过。

未运行：尚未部署V14/接口到保留数据演示，未改M09/M10/M11，未追加/导入购物政策与索引、未做未发货建议的当前事实复核或新购物退款网页闭环。演示仍第四批版本，原数据/预算未触碰，无新付款/发货/工单/退款/模型调用。下一步同一第五批先购物政策与复核，再网页接线及集中验收；第六批仍待执行。
