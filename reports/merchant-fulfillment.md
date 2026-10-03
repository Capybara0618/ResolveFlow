# 第五批：商家模拟履约与购物政策验证

2026-10-03，依据[第五批规格](../docs/merchant-fulfillment.md)，复用第四批5884d80/fbd5c73/c97685e及资金74df827。第五批已集中完成，正式网页与保留数据部署证据见末节；第六批完整购物退款网页闭环尚未验收。本文早期子步的“未实现/未部署”均为当时历史，当前进度只看tasks/todo.md顶部。

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

## 两商家购物政策与未发货建议复核子步

2026-10-03，接口7e99b6f已推送。仅追加policy-logistics-2026.10与policy-demo-m1002-logistics-2026.10，2026-10-01T00Z起/safety_epoch3，覆盖未发货、丢失、签收争议、损坏/质量核验、普通在途及单行全额/资金/人工决定六条规则。六个旧bundle、历史钉住与正文hash不修改；按支付日期和商家选择版本。新不可变源的manifest_hash分别为b1d94c4da51e65a457119d101448ebc38d5a0aade7e93802c13db7b55ea40faa和87a0c051eebdf5045865f4bd795fe2ad0daf12e06a0e0632630b9b58df3e07d1。既有启动驱动仅在原索引bundle清单追加两ID，沿用从Java读取存储manifest/hash的导入入口，不在生产检索时解析YAML。

UnshippedRefundCheck在REFUND建议引用R-UNSHIPPED-001时复核当前可信订单/商家/本人/目标行，要求持久NOT_SHIPPED头与行/version1、UNKNOWN承运商结论、唯一ORDER_PAID付款事件。缺失物流/未知/在途/签收不能当未发货；缺失404为建议拒绝，依赖故障503。人工批准按授权固定proposal_id读取原建议，当前状态变化409，不写决定/资金；网络读取在既有Case写锁外，随后原revision/负责人/身份/授权CAS仍在锁内复核。旧规则不新增购物依赖。按既有字段语义区分AGENT的回调信封hash与HUMAN的文档hash，保留原回调验证；不改变原哈希协议。

实际命令：

```powershell
./java/mvnw.cmd -f java/pom.xml -pl case-service -am '-Dtest=UnshippedRefundCheckTest,ProposalReCheckApiTest,ReviewDecisionApiTest,PolicyImportTest,PolicyManifestApiTest,ManualProposalApiTest,AuthorizationApiTest,AuthorizationConsumptionApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./java/mvnw.cmd -f java/pom.xml '"-DspotlessFiles=.*(UnshippedRefundCheck|UnshippedRefundCheckTest|ProposalReCheck|ProposalReCheckApiTest|ReviewDecisionService|ReviewDecisionApiTest|PolicyImportTest|PolicyManifestApiTest)\.java"' spotless:apply
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_shopping_policy_index.py agent/tests/integration/test_policy_index.py agent/tests/unit/test_policy_chunking.py agent/tests/unit/test_reviewer_demo_driver.py -q
agent/.venv/Scripts/python.exe -m ruff check agent/tests/integration/test_shopping_policy_index.py
git diff --check
```

最终Java八类88 passed/0 skipped，临时真实MySQL：新旧日期/两商家选择、六旧bundle逐字段不变、新hash与跨语言c-01 hash、重导8跳过/改版拒绝、原钉住保持；未发货提交通过而在途/未知存REJECTED不建授权；提交后发货阻止批准、依赖503不写审批；原人工/授权/消费回归保留。Python四文件56 passed/0 skipped，其中两个新真实PG测试在随机独立schema索引两商家，精确hash门禁、异店拒绝、c-01引用hash及完整限制原文通过；旧索引/分块/启动驱动回归保留。BM25真实检索通过，dense测试使用现有合成embedder，不宣称新模型召回质量；未调用Live。

失败与修复：Java首轮72项70通过/1失败/1错误，错误是Mockito重新when时执行此前抛错stub，改doThrow/doReturn；审批失败暴露AGENT记录的payload_hash实际为回调信封hash，不能直接与建议文档hash比较，按既有AGENT/HUMAN语义修正后73项通过，补强跨语言hash与授权/消费回归最终88通过。Python首轮因chunk_of不在包导出而收集失败，改从既有chunking模块导入；第二轮54通过/2失败为测试误用位置1，依据已有零基位置规范改位置0验证c-01，最终56通过。新Python文件Ruff通过、定点Spotless/diff通过；同时检查旧scripts/reviewer_demo.py全文件Ruff失败19条，与HEAD旧文件相同code/message的19条诊断已核对，不修无关旧代码、不宣称全仓lint通过。

未运行与边界：保留数据演示尚未部署V14/API/新政策/正式索引，网页M09/M10/M11未修改；新索引只在隔离测试schema验证，不能宣称演示RAG已READY。未做新购物退款网页闭环、未启Live/dense收费评测，无原演示订单/资金/工单/run或预算写入。当前复核是跨服务当前事实读取，不是分布式原子锁；只有Commerce已建立退款占用才由相同账本/槽锁阻止发货，Case消费到异步送达之间不作更强承诺。第五批仍未完成，接续正式网页与保留数据集中验证后才进入第六批全链验收。

## 正式网页、逐行售后投影与保留数据集中验收

2026-10-03，本节为第五批最终状态，前述未部署/未接网页说明是历史。复用已推送b404e9b政策与所有原接口，接M10本商家管理员交易筛选/分页、M11不可变全部商品/原金额/逐行退款占用/首次整单模拟发货及确认弹窗，M09本人真实履约/轨迹和独立读取故障。App权限菜单及原队列连接已接；长订单号收起，主事实16px以上，保留既有人员/政策/审核导航。

本批必要协议补充：MerchantTrade增加必填line_aftercare，Commerce按订单真实槽投影FREE/RESERVED/CONSUMED/MISSING及行金额；缺槽为null，不将整单汇总分摊给每行。shared wire、两份core OpenAPI、fixture、网页类型与实库测试同步，未增路由/迁移。新增实库第九项验证一行预留不影响另一行、缺槽不伪造零占用。订单售后按钮按order_id搜索原队列全部阶段，没有创建工单；只支持订单号的搜索不能误传line_id。

发货先保存当前商家/管理员隔离的原key+expected_version+order到sessionStorage，响应丢失后重开页面只读原订单，显式重试原请求。401保留；确定409拒绝后需刷新；存储失败/损坏阻止新写且不抹掉恢复信息。成功后续GET故障仍保留已确认履约，不能反转为未知。独立买家履约读取故障不隐藏付款/售后资格、不假定未发货。没有跨浏览器/关闭会话后的持久恢复承诺。

实际验证命令（Java21/Python沿用原锁）：

```powershell
./java/mvnw.cmd -f java/pom.xml -pl commerce-service,case-service -am '-Dtest=MerchantTradeApiTest,FulfillmentDatabaseTest,CommerceShoppingClientTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./java/mvnw.cmd -f java/pom.xml '"-DspotlessFiles=.*(FulfillmentWire|MerchantTradeService|FulfillmentDatabaseTest)\.java"' spotless:apply
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_fulfillment.py agent/tests/unit/test_contracts_core_routes.py -q
# 以下两条在web目录
pnpm test -- --run
pnpm build
# 以下在根目录，原始证据/原请求仅保存在忽略目录tmp
agent/.venv/Scripts/python.exe -m ruff format scripts/merchant_fulfillment_acceptance.py
agent/.venv/Scripts/python.exe -m ruff check scripts/merchant_fulfillment_acceptance.py
$env:PYTHONPATH='agent/src'
agent/.venv/Scripts/python.exe scripts/merchant_fulfillment_acceptance.py snapshot
.\demo.ps1 stop
.\demo.ps1 -NoBrowser
agent/.venv/Scripts/python.exe scripts/merchant_fulfillment_acceptance.py prepare
# 仅专用M-1001新增订单在正式浏览器点击确认模拟发货
agent/.venv/Scripts/python.exe scripts/merchant_fulfillment_acceptance.py verify
git diff --check
```

结果：Java四类23 passed/0 skipped（Commerce履约9/接口2、Case客户端7/接口5），Python两个文件90 passed/0 skipped；全前端20文件149 passed，vue-tsc/Vite构建通过，定点Spotless/新驱动Ruff通过。十项新管理员组件测试覆盖全行/订单查询连接、显式版本+原key、未知响应重开原请求不自动写、已确认后读故障、409、401、损坏/写失败存储、筛选/游标、跨账号恢复隔离；买家新增未发货和履约503回归。已有人员/售后/购物测试保留，未跳过断言。

保留数据stop/NoBrowser重新构建三JAR，Case已V24、Commerce追加V14；只读Agent8182、Gateway8180、前端5174健康。政策导入新增2/旧6跳过，原启动入口八bundle精确manifest索引READY。真实HTTP/索引20项通过，见[脱敏机器报告](merchant-fulfillment/verification.json)：两商家管理员各自订单/过滤、买家同一履约、匿名401、买家/专员/旧客户403、异店详情/发货404、网页原成功key重放同一回执、新key再次发货409。实际本地缓存dense编码器检索两新政策R-UNSHIPPED-001，引用hash与Java存储原规则严格相同；未调用Live大模型，不能据此宣称模型推荐质量已验证。

正式浏览器：M-1001管理员查看新增329元订单，展开编号核对目标后确认一次模拟发货，观察运输中/version2及两个原追加事件。原727元双行订单只读，两行329/398元完整，进入订单号927b833f-3da3-4331-a5fa-6846d04ace8e队列得到0条，未创建申请。平台买家看到同一329元运输中/同轨迹；第二店新129元订单仍为NOT_SHIPPED/version1/唯一ORDER_PAID。管理员详情1280/1440/1680和买家履约三个桌面尺寸无横向溢出，主要事实至少16px；viewport已恢复默认。截图如下：

- [管理员已确认发货1440](merchant-fulfillment/admin-shipped-1440.png)
- [管理员原双行订单1440](merchant-fulfillment/admin-multiline-1440.png)
- [买家相同运输事实1440](merchant-fulfillment/buyer-shipped-1440.png)
- [买家第二店待发货1440](merchant-fulfillment/buyer-unshipped-1440.png)

专用新增M-1001订单0b184fa2-2a44-4130-9e6a-b40fdf7ce395，商品行SHOP-6ee803c8-f94e-466d-8728-8c89daf6cf49；M-1002订单a9515483-be69-47db-a3fd-93187bbc4f42，行SHOP-4d1af28b-b50d-4c7d-b192-5220ceaf8c0b。公开报告保存合成ID与聚合/哈希，不含令牌、原请求key或原始DB快照。原始样本/keys及baseline仅tmp。

原34工单/5负责人/34钉住、6旧政策/17授权/9退款操作、40账本/40订单/8草稿/42槽、92run及预算、14账号、37原物流/76原轨迹、2购物车头/1条目/5请求，按原ID与所选字段逐条不变；只新增2草稿、2成功付款/订单及2行/槽、2政策，一次专用网页模拟发货；新工单/退款/模型调用0。V14对原已付checkout缺物流样本追加的新事实不计为改写旧物流。启动沿用原显示字段回填与索引replace流程，验证不涵盖全部DB列或索引generation，不宣称全库逐字节不变。

失败与处理：首次单SKU测试错误预期两行，改为正确单行断言并另加多行隔离测试，最终23通过。快照启动首轮临时生成脚本换行转义错误，修正后在V14/政策导入前重新采集，确认仍旧6政策/无SHOP物流；不伪造首次成功。样本驱动错误期待草稿201（实际200）留下一个新未付草稿，核对唯一新增ID、原key及无付款尝试后恢复这笔原草稿，未删除或另建替代；驱动现已先落盘原键/ID，可恢复同一请求。verify第一次查询错误列shipment_expected_version，按真实expected_version修正再跑20通过，未改变数据库。浏览器字体只读测量不支持parseFloat，改直接读取computed fontSize；开发HMR重挂导致首次只读定位仍为329元，刷新状态重新定位727元后完成验证，无重复发货。所有失败没有改变原资金/工单/run，也没有绕过断言。

尚未运行：第六批新购物→申请→Agent/RAG→负责人核验/补证→人工审批→原退款账本→买家终态的正式网页集中链路；未启动收费Live、未消费原QUEUED历史队列、未验证外部真实支付/物流或移动端。第五批基础已部署完成，第六批复用本成果；未发货复核仍不是分布式原子锁，只有Commerce实际退款占用才阻止发货。
