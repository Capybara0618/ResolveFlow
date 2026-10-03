# 第四批：持久购物车与多行结算

2026-10-03。本批依据[正式规格](../docs/cart-multiline-checkout.md)，复用已验证的[行级资金前置](multiline-refunds.md)。第四批已完成；下文两个后端小节保留阶段性失败和当时尚未部署的记录，不代表当前状态。

## 正式网页与保留数据集中验收

购物车后端fbd5c73、多行后端c97685e已正常推送。正式MarketplaceWorkspace加入真实购物车导航/商品加入，CartWorkspace实现M05本人分店选行、数量、删除与M06全部选行服务器报价/提交；shop-client同步协议，cart-pending按buyer_id在当前浏览器会话保存原键及绝对请求。结果不确定时冻结输入并显式原请求重试，刷新页面不自动写入；401退出后保留该买家待确认请求。版本冲突刷新事实、重新确认报价，下架/停用条目不伪装消失。BuyerOrders保留全部不可变行，并显示独立退款汇总而不改PAID付款事实。

实际命令：

```powershell
agent/.venv/Scripts/python.exe scripts/multiline_money_acceptance.py snapshot --baseline tmp/cart-before.json
.\demo.ps1 stop
.\demo.ps1 -NoBrowser
pnpm --dir web test
pnpm --dir web build
agent/.venv/Scripts/python.exe scripts/cart_checkout_acceptance.py
agent/.venv/Scripts/python.exe -m ruff check scripts/cart_checkout_acceptance.py
git diff --check
```

保留原resolveflow-review-demo卷，重建三个Java JAR并追加V12/V13，Agent保持只读；未清库或启动Live。Java61项和Python125项后端结果见下文；前端19文件138 passed，vue-tsc/Vite build通过。CartWorkspace十项测试覆盖按店选行、多行报价、版本冲突、未知提交/数量原键恢复、刷新恢复、401及旧回调；Marketplace新增两个加入/未知结果回归。页面截图发现公共按钮padding优先级导致“移除”换行，已修正购物车按钮选择器并复跑138/build，最终浏览器确认为10px 0px padding及nowrap。

浏览器用正式API创建且支付两个新合成订单：松间数码耳机1件329元＋键盘2件398元，共727元；拾光家居台灯129元＋保温杯89元，共218元。第一店结算后未选鼠标1件和第二店两件商品保持，第二店结算后仅鼠标仍在购物车。付款页和跨店“我的订单”展示两笔PAID及每笔全部两行。付款成功前不显示订单行ID，成功后与原订单API、总账及每行FREE槽一致。没有提交新售后、产生新退款或调用模型。

实际HTTP24项通过：匿名/旧客户/管理员拒绝、本人购物车持久、外部Agent即使持checkout scope仍拒绝、原成功付款键重放、原订单全行可读、各行上下文与槽、已付款取消409，以及可信内部边界的异客户复合归属404。验证驱动初次尝试不存在的demo-buyer-2登录返回401；没有新建账号或改密码，改用既有可信内部异客户读取核验。公共不同buyer隔离由Case真实API测试覆盖，本轮没有第二平台买家网页登录。基线和付款键只在忽略目录/进程内，公开报告不包含凭据。

按原ID逐条比较快照所选原字段：34工单/5负责人/34政策绑定/6政策/17授权/9退款操作/38账本/38订单/6草稿/38槽、92run及预算、14账号均不变；迁移新增字段不冒充旧全列快照。仅追加2草稿、2已付订单及总账、4订单行及FREE槽和本人的购物车/付款请求记录。完整保护结果见[verification.json](cart-checkout/verification.json)，网页样本见[samples.json](cart-checkout/samples.json)。旧UNKNOWN和其他历史样本未改变。

桌面购物车/确认订单/订单列表在1280、1440、1680三个宽度分别验证无横向溢出，主要事实字体购物车≥16px、其他≥17px。初次结算宽度记录重复1280，另补实际1440报价只读验证；最后按钮修正后再验证三宽购物车，共13条原始记录，详见[desktop.json](cart-checkout/desktop.json)。临时浏览器尺寸已恢复，不增加移动端实现。

| 截图 | 实际内容 |
| --- | --- |
| [cart.jpg](cart-checkout/screenshots/cart.jpg) | 第一店选耳机/键盘、不选鼠标及第二店商品；按钮修正前保留为过程证据 |
| [checkout.jpg](cart-checkout/screenshots/checkout.jpg) | 第一店727元完整两行报价 |
| [after-first-store.jpg](cart-checkout/screenshots/after-first-store.jpg) | 首店付款后未选/另一店保留；按钮修正前 |
| [paid-multi-M1001.jpg](cart-checkout/screenshots/paid-multi-M1001.jpg)、[paid-multi-M1002.jpg](cart-checkout/screenshots/paid-multi-M1002.jpg) | 两家店各自成功付款及全部商品 |
| [orders.jpg](cart-checkout/screenshots/orders.jpg) | 两笔多行PAID及原交易共存 |
| [cart-final.jpg](cart-checkout/screenshots/cart-final.jpg) | 结算后只剩未选鼠标，移除按钮修正后 |

未运行：真实支付、库存/物流、Live模型质量、原演示库UNKNOWN/FAILED故障注入、新购物到退款全链。UNKNOWN、半单回滚、并发及改价/下架在隔离真实MySQL和组件测试覆盖，不声称浏览器故障演示。下一步按原第五批实施模拟履约、未发货及当前日期不可变政策，再在第六批集中验证购物→申请→人工审批→模拟退款。已有售后五批、前三批及资金前置不重做；独立一步仅提交本批网页/驱动/公开证据与文档，历史工程/verify/退款测试/草图/敏感日志不夹带。

## 持久购物车后端

已追加V12购物车/条目/请求回执三表；旧订单、草稿、账本和退款槽不更新。每店本人购物车单独持久版本，空车也保留版本，避免删除再加入后旧请求覆盖。写入使用绝对数量、原Idempotency-Key及expected_revision；同键同载荷返回原回执，同键异载荷409；并发不同写入仅一个成功。每店20个SKU，数量校验当前上限，改价/下架/店铺停用/超限条目仍展示真实当前价与不可售原因，可删除。

Case只接受当前平台买家，由持久BuyerScopes解析可信商家/客户，不接受自报主体；GET组合两店，任一店不可用拒绝整页，不显示假空车。Commerce购物车读写均要求case-service部署身份及commerce:checkout，Agent持同名scope仍不能访问。公共返回不泄露客户、买家、请求键或hash。

实际命令（JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1）：

```powershell
./java/mvnw.cmd -f java/pom.xml -pl commerce-service,case-service -am '-Dtest=CartDatabaseTest,CartApiTest,CartBuyerApiTest,ShoppingDatabaseTest,ShoppingApiTest,ShopApiTest,CommerceShoppingClientTest,CheckoutBuyerApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./java/mvnw.cmd -f java/pom.xml -pl case-service -am '-Dtest=CommerceShoppingClientTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_cart.py agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_shopping.py agent/tests/unit/test_contracts_checkout_payment.py agent/tests/unit/test_contracts_multiline_money.py -q
```

真实MySQL Testcontainers第一条8类32 passed/0 skipped，客户端追加协议round-trip后第二条5 passed，共33项独立测试。六个购物车领域场景覆盖隔离、改价、下架、空车版本、上限、并发重放/竞争及不生成付款；HTTP覆盖匿名/三个商家角色拒绝、可信归属、未知店/私有字段/缺键、服务故障，以及Agent即便持checkout scope也被拒绝。旧目录/单SKU草稿/付款facade回归保留。Python五文件116 passed，core路由Case51/Commerce19/Agent7，wire/严格Schema/6份fixture同步。

失败记录：首次协议运行87 failed/21 passed，原因为局部YAML生成复用了已有anchor名称；新片段改为无alias输出，未重写原文档。第二次107 passed/1 failed揭示上一资金子步遗漏的旧“所有LineContext成员必填”断言；改成原14项必填+仅两个明确定义的可选扩展，并断言槽依赖整单支付额，未删除原必填/金额/安全断言。最终116通过。定点Spotless通过，Ruff与git diff检查通过。原未提交Commerce退款测试、工程/verify脚本、草图与历史日志未纳入本子步。

本子步未重启演示环境、迁移演示库、编辑前端、调用模型或模拟付款。V12已在临时测试库实测。购物车尚未接正式网页，多行报价/不可变草稿/支付发布和M05/M06尚待继续；第四批没有完成。后续先多行发布，再按功能批次保留数据部署与集中网页验证。

## 多行草稿与付款后端

购物车后端fbd5c73已确认正常推送，继续同批。追加V13扩展SINGLE/MULTI头、不可变checkout_draft_line及checkout_payment_line映射；原V10/V11/V12不修改，旧SINGLE金额约束保留。新MULTI最多20个不同SKU、CNY整数分及整单1,000,000,000分上限。报价只读取本店本人选中购物车项；创建按SKU排序规范化请求hash，先找原键、再锁购物车与商品权威复核数量/当前价格版本；草稿、全部快照及选行删除同事务，未选/其他店保留。同键即便下架仍回原订单，重放不删除新加条目；单SKU和MULTI同键异模式409。

原支付reserve→事务外持久模拟收据→settle继续使用。MULTI在reserve中提前持久全部line_id映射，UNKNOWN和发布失败沿原attempt恢复；成功在一个事务发布一个订单/总账、全部订单行和各行FREE槽，任一行失败全部回滚，收据仍可查并完成原尝试。PurchaseReads返回全部不可变行，未成功付款不暴露预分配行ID。旧单行协议/读写兼容保留；独立可选refund_status由本人的真实订单账本投影NONE/IN_PROGRESS/PARTIALLY_REFUNDED/REFUNDED，PAID仍是付款事实；旧fixture无该字段仍可读，新协议只允许已付订单带退款汇总。

实际集中验证：

```powershell
./java/mvnw.cmd -f java/pom.xml -pl commerce-service,case-service -am '-Dtest=MultiCheckoutDatabaseTest,CheckoutPaymentDatabaseTest,ShoppingDatabaseTest,CartDatabaseTest,CartApiTest,CartBuyerApiTest,ShopApiTest,CommerceShoppingClientTest,CheckoutBuyerApiTest,CheckoutApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./java/mvnw.cmd -f java/pom.xml -pl commerce-service -am '-Dtest=MultiCheckoutDatabaseTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_cart_checkout.py agent/tests/unit/test_contracts_cart.py agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_shopping.py agent/tests/unit/test_contracts_checkout_payment.py agent/tests/unit/test_contracts_multiline_money.py -q
```

首轮领域37 passed后补齐API/独立退款汇总，10类60 passed/0 skipped（Commerce41、Case19），再追加确定失败新尝试及旧ID不发布测试，多行11项复测，共61项独立Java。Python六文件125 passed；定点Spotless/Ruff/diff通过，core路由Case53/Commerce21/Agent7及六份多行fixture/共享wire同步。九类多行场景与后续两个补充测试覆盖canonical重放、改价/下架、跨店/同店未选保留、金额上限、UNKNOWN原ID、半单回滚、删除失败原子性、并发发布、不完整快照、失败新尝试以及付款/退款分开。退款汇总测试在隔离库直接设置合成账本组合，仅验证投影，不作为真实退款写链新验收。

失败记录：首轮测试编译因两个Line通配导入歧义失败，显式选择CheckoutWire.Line；第二轮35 passed/2 errors是临时MySQL账号无创建TRIGGER权限。改成只在JdbcTemplate spy的第二行INSERT/DELETE处注入DataIntegrityViolationException，实际数据库事务/其余SQL仍真实执行，不放宽生产数据库或依赖锁；37项复跑通过，再补充API/汇总及失败重试验证。不在原演示库注入故障，不关闭断言。前端已在工作区接线，138项/build通过但此后端子步尚未提交页面或进行正式浏览器验收；演示库仍旧版，下一步精确提交推送本后端后保留数据部署、M05/M06与两店付款集中验收。收费模型调用0，第四批暂未收口。
