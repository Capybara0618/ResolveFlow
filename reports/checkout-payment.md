# 第三批模拟付款验证

2026-10-03。第三批M07–M09已完成，正式协议见[付款与本人交易](../docs/simulated-checkout-payment.md)。以下领域/API子步记录保留，正式网页和保留数据集中验收见末节。第四批购物车/多行与第五批模拟履约尚未完成。

领域子步文件：CheckoutWire、V11__checkout_payment.sql、CheckoutPayments、SimulatedCheckoutProvider、ShoppingService、CheckoutPaymentDatabaseTest。追加V11，保留旧迁移、订单、退款及Agent锁；本地持久模拟收据。该隔离测试子步没有演示库写入；后续网页验收追加的合成购买见末节。

实际命令（Java21、真实MySQL8.4 Testcontainers）：`java/mvnw.cmd -f java/pom.xml -pl commerce-service -am -Dtest=CheckoutPaymentDatabaseTest,ShoppingDatabaseTest,OrderLineReadServiceDatabaseTest -Dsurefire.failIfNoSpecifiedTests=false test`。最终33 passed/0 skipped（新付款13、原草稿8、原订单读取12）。定点Spotless apply与git diff --check通过。

覆盖：同key/并发付款一次、原金额/名称/数量、paid_at与收据一致、0已退/预留与FREE槽、无物流、付款/取消竞争、取消幂等、到期拒绝、UNKNOWN调用前中断原键恢复、收据持久后丢响应仅查询恢复、明确失败再付与过期失败拒绝、篡改收据金额不发布、跨复合归属拒绝、发布中途主键冲突整事务回滚后复用原尝试。测试还检查provider调用时没有包围它的业务事务。

失败与修复：初始未实现领域的有效RED为11失败（2断言失败/9未实现异常）；V11实库迁移通过。首实现将MySQL DATETIME对象误当Timestamp，改为显式UTC转换LocalDateTime后新13/旧草稿8通过。组合回归发现新测试留下成功订单污染原商家全量读取断言（2失败）；在可丢弃测试库按本类独立customer范围清理自身夹具后33全部通过，原断言未删改。原始日志保留忽略目录tmp/checkout-payment-*.log，不提交。

后续接口子步：新增付款/原尝试查询/取消/本人列表/详情，Case/Commerce各5核心路由（总49/17，Agent仍7）。当前买家/启用复合绑定，Agent/Case普通读凭证禁止访问私有交易；严格空公共请求不能注入金额、归属或provider结果。新旧订单按draft:/order:命名空间合并、已发布只出现一次；跨店游标绑定buyer、归属与筛选，一个店故障拒绝整页。历史名称/单价/插画缺失保持null。共享wire、两个OpenAPI及fixture同步。

实际最终接口回归：Maven指定CheckoutApiTest、CheckoutPaymentDatabaseTest、ShoppingDatabaseTest、ShoppingApiTest、ShopApiTest、CheckoutBuyerApiTest、BuyerPurchaseServiceTest、CommerceShoppingClientTest、OrderLineReadServiceDatabaseTest，9类51 passed/0 skipped；Python core_routes/platform_buyer/shopping/checkout_payment四文件108 passed。定点Spotless apply通过，原断言保留。首次新API有效RED为2个404；契约片段错误放到paths外、缺operationId及时间fixture零微秒被Java正规化、URI冒号编码断言错误已修复复跑，未删除对应检查。

上述API子步时尚未运行正式浏览器与演示库升级，现已按下节完成；不是未完成项继续重做的指令。

## 正式网页与保留数据集中验收

2026-10-03。复用前两批目录、报价、平台买家与原售后，新增BuyerOrders及类型/API方法、桌面样式、Marketplace路由和Customer直接申请入口。付款页支持待付/成功/取消/到期/结果待确认；明确失败允许显式再付，网络不确定保留当前buyer+draft的原请求键。刷新/重挂载不自动付款，UNKNOWN没有原键时只允许查询；取消响应不确定也先读取确认。付款成功后的订单详情逐行读取原服务端资格，直接申请路径再次核验；旧账号及旧售后列表保留。历史缺失图片/单价不补造。

浏览器实际操作：`demo-buyer`浏览松间数码，购买2件黑色耳机，658元模拟付款；拾光家居购买1件台灯，129元模拟付款；另一份89元保温杯订单经确认弹窗取消；另留一份59元靠枕待付款。我的订单显示4份本批交易、2份前批已到期草稿、2份原本人已支付订单，共8份且成功草稿不重复出现。按松间数码+已付款筛选返回新658元和旧329元两份；打开658元详情后进入原售后申请表，确认原数量2/整行658元，未提交申请。四份公开合成定位见[samples.json](checkout-payment/samples.json)，等待样本会按真实时钟到期，不是固定截图状态。

正式页面21项桌面检查（7个视图×1280/1440/1680）全部通过，无横向溢出，测量订单主要标题/金额/名称/规格/状态/按钮及折叠编号入口至少16px。七个视图为订单列表、待付款、付款成功、订单详情、已取消、已到期和空筛选；不测移动端。结果见[desktop-layout.json](checkout-payment/desktop-layout.json)。截图：[待付款](checkout-payment/waiting.png)、[成功](checkout-payment/success.png)、[订单列表](checkout-payment/orders.png)、[详情](checkout-payment/detail.png)、[取消](checkout-payment/cancelled.png)、[到期](checkout-payment/expired.png)、[空态](checkout-payment/empty.png)，均为正式网页/真实本机合成数据；不把静态预期图或组件mock截图当实际验收。

实际命令及结果：

```powershell
pnpm --dir web test
pnpm --dir web build
agent/.venv/Scripts/python.exe -m ruff check scripts/checkout_payment_acceptance.py
.\demo.ps1 stop
.\demo.ps1 -NoBrowser
agent/.venv/Scripts/python.exe scripts/checkout_payment_acceptance.py verify
git diff --check
```

前端18文件126 passed，vue-tsc/Vite build通过，新增10项组件回归覆盖付款丢响应、原请求重挂载/查询恢复、取消不确定、期限、筛选和父路由、旧回调/401及直接申请拒绝。Java51及Python协议108结果沿用本批前述最终验证，后续仅前端/记录修改，未重复跑未变业务。Ruff通过。原始构建/测试/启动日志保留忽略目录，不提交令牌、模型密钥或原数据库快照。

升级前保存只读基线，保留数据stop/NoBrowser重建3个JAR，V11在原演示MySQL成功追加；原政策hash与PG索引READY，不开启Live。可复用驱动[checkout_payment_acceptance.py](../scripts/checkout_payment_acceptance.py)支持先snapshot再verify；本次升级前基线由同等只读临时驱动保存。verify实际48项HTTP检查全部通过：未登录401/旧客户与管理员403、跨复合归属404、Agent及Case普通读凭证403、不能注入金额/付款结果、原成功key重放/新key拒绝、取消重放/到期拒绝、跨店分页去重/筛选游标约束及新订单行原售后资格。支付key、令牌、password_hash和原始快照不进入报告。

账本证据见[verification.json](checkout-payment/verification.json)：每笔成功恰好1个尝试/1份原金额收据/1份订单、同一行原金额账本0已退/0预留及FREE槽；取消/待付没有订单/账本/退款槽。原34工单、5归属、34政策绑定、6政策、17授权、9退款操作、36支付账本、36订单、14账号、2旧草稿、92run及92份budget_spent按原ID逐条一致；仅追加4草稿/2订单及对应初始账本/槽。未产生新退款操作、工单或Agent调用，模型调用0。旧草稿只有V11类别列被补齐，原保存字段和状态未修改，EXPIRED是读取投影。

失败与修复：首次前端期限断言使用已过期夹具，改为明确未来日期；类型夹具错误多写version已修正，复跑126/build通过。布局读数诊断首次使用受限DOM环境不提供的parseFloat，改用可用的数值转换；编号折叠标题受旧全局12px覆盖，定点改为16px后21项通过并重新构建。首次文档补丁因整段匹配不全而拒绝，精确重试成功，不影响业务数据。无测试断言删除或演示数据重置。

未运行及边界：UNKNOWN、调用前/收据后中断、确定FAILED及原子发布回滚仅在隔离Java实库/组件故障测试验证，没有向保留演示库注入故障。未调用收费模型、真实支付或新购物退款审批；购物车、多行、模拟发货、未发货/当前日期不可变政策及最终全链验收留后续三批。第三批可体验购买→模拟付款→本人订单→原售后表单，不能称整个商城售后新链路已完成。

后端领域与API已普通推送d924627/bf0f894；本网页、报告与交接精确提交后普通push，实际SHA/远端确认见交接消息，不递归修改自身提交。

收口文档检查：实际Python只读脚本通过README/指南/付款规格/报告的63个本地链接、48项HTTP与21项桌面报告结果断言，并确认验收驱动依赖已跟踪。账本/交接仅更新顶部，历史内容保留；首次写入前缀保护因误用CRLF触发而未写入，核对LF后精确更新。git diff --check通过。
