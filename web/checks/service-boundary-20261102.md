# 商城与售后边界调整验证

2026-11-02。目标见 `docs/service-boundary-plan.md`，执行进度仅见 `tasks/todo.md` 顶部。原四个历史脏文件保持，不作为本批提交依赖。

## 公共目录直连 Commerce

新增 `PublicCatalogController` 直接复用 Commerce 领域服务，8 个公共操作与原 Case 请求/响应兼容。Gateway 按方法和明确路径直达 Commerce，保留路径/查询和伪造身份头清除。未进行内部路由前缀重写。图片字节仍依赖 Case 的文件与归属存储，私有交易尚未切流。Case 同名公共目录契约及实现暂作兼容，后续清理。

同步 Commerce OpenAPI、核心路由表、隔离演示 Gateway 的两个上游地址及 Compose 地址。新增展示 schema 使用现有 DTO 结构。无数据库迁移/项目业务写入/模型请求；Docker Desktop 为隔离 Testcontainers 测试启动，未启动项目业务服务。

### 实际命令与结果

- JDK `C:/Users/hjn/.jdks/jdk-21.0.12.1+1`，`java/mvnw.cmd -f java/pom.xml -B -pl gateway -am -Dtest=CoreRoutesTest -Dsurefire.failIfNoSpecifiedTests=false test`：新增 8 个路由用例先红，原 3 项通过，证明请求此前落到 Case。日志 `tmp/service-boundary-gateway-red.log`。
- 同入口 `-pl commerce-service -am -Dtest=PublicCatalogApiTest`：4 项先红，真实独立 MySQL，未启动 Case。日志 `tmp/service-boundary-commerce-red.log`。
- 同入口 `-pl gateway,commerce-service -am -Dtest=CoreRoutesTest,PublicCatalogApiTest,ShoppingApiTest,ProductReviewApiTest,InternalScopeEnforcementTest,IdentityHeaderStripFilterTest`：Gateway 14、Commerce 16 全过，无跳过。覆盖参数/路径、报价金额、未知字段拒绝、公开评价、未授权内部入口、Agent 无交易权限及 SSE 首帧/断点头。
- 定向 `spotless:apply spotless:check`，参数 `-DspotlessFiles=.*CoreRoutes[.]java,.*CoreRoutesTest[.]java,.*PublicCatalogController[.]java,.*PublicCatalogApiTest[.]java` 通过。初次误用 glob 导致正则错误、第二次参数被 Windows batch 解释，均未形成格式通过；最终使用逗号分隔正则通过，保留 `tmp/service-boundary-format.log`。
- `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_reviewer_demo_driver.py -q`：29 过，包含 Gateway 使用当前隔离环境两个服务地址。
- 新公共契约、原 shopping/presentation 与完整核心路由检查一起执行；初轮 94 过/8 失败，其中新增 presentation 的 path-level 参数触发旧遍历假设，已把参数移入 GET 操作。其余 7 项以 HEAD 原件在忽略目录独立复现：旧 Case 路由表遗漏、操作缺 summary、专题文档缺 profile、Case/Commerce 旧草稿示例缺 shipping、旧 stream-events 错误 security/缺 401、403。未删断言或修改旧记录掩盖。
- 修正后完整同组检查 95 过/7 个原失败，公共目录/购物/展示契约单独 21 过；没有关闭原失败。新增测试及修改的运行驱动测试 Ruff 通过；`reviewer_demo.py` 整文件 Ruff 有 19 项历史错误，HEAD 与工作区逐条诊断相同，未顺带修改无关脚本。`git diff --check` 通过。

本步未运行浏览器、付费模型、项目购物/退款端到端；不以目录测试代替后续受保护交易验收。公共 Commerce 数据读取在无 Case 进程下已实测，Gateway 转发由独立 HTTP 上游测试核实。

## 当前身份与地址协议

新增 `IdentityAccessWire`、Case `IdentityAccessController` 与 Commerce `IdentityAccessClient`。内部入口要求 `commerce-service` 服务主体及独立 `identity:resolve` scope，用户凭证只放请求体。Case 复核持久账号、身份版本与有效绑定，可选读取本人当前地址快照；响应 `no-store`，不读订单或工单。Commerce 先验证用户 JWT，再逐请求查询账号权威，核对返回主体/版本/绑定结构，失败不退回离线 JWT 或缓存范围。限时 1 秒连接/3 秒读取；不会在初始化时连接 Case，不引入 Compose 健康依赖环。

账号变更的线性化点仍是账户查询/地址短事务，不承诺跨服务原子撤销已通过校验的在途操作；与原先 Case 认证后调用 Commerce 的语义一致。Java 退款授权消费协议不变。

- `-pl case-service -am -Dtest=IdentityAccessApiTest`：5 项先红，全部为尚无接口/新权限所致，原日志 `tmp/service-boundary-identity-red.log`。
- `-pl case-service,commerce-service -am -Dtest=IdentityAccessApiTest,IdentityAccessClientTest,InternalScopeEnforcementTest,AccountServiceTest -Dsurefire.failIfNoSpecifiedTests=false test`：Commerce 13、Case 11 全过。首次客户端单测暴露 HttpURLConnection 流式 POST 读取 401 时异常，原错误被包装成 503；换成 JDK HttpClient 传输，保留状态响应并修复。原失败在 `tmp/service-boundary-identity-green.log`，通过在 `tmp/service-boundary-identity-final.log`。
- 追加真实跨买家地址拒绝与格式化后，`IdentityAccessApiTest` 5 项再次通过（重叠，不累计）；校验无凭证、错误 aud/服务主体/scope、用户内嵌服务 token、附加 merchant_id、停用、旧身份版本、本人地址版本冲突及跨买家地址404。
- `IdentityAccessClientTest` 验证独立服务 token、用户 token 仅在请求体、无身份头、401保留、上游500/畸形响应/连接失败503、返回主体/版本错配及重复绑定拒绝。未使用项目账号/数据库。
- 身份契约夹具/注入拒绝及运行驱动 31 项过；新测试 Ruff、7 类定向 Spotless、`git diff --check` 通过。核心路由数只追加一个 Case 内部操作，未删除原断言。

本步尚未切换私有交易流量；身份服务暂部署在 Case，受保护交易仍依赖它的可用性。账户包尚复用旧会话解析器，不宣称整个身份模块已经实现物理拆分。

## 买家购物与结算直连

`PublicCartController`/`PublicCheckoutController` 通过当前身份协议取可信绑定，直接调用 Commerce 的购物车、草稿、付款与购买记录服务。跨店归并迁到 `BuyerPurchaseReads`，保留买家/绑定/筛选绑定游标、微秒时间及稳定店内排序。Gateway 切换对应 12 个操作，其他未迁移入口保留原路由。共享 DTO 与原 Case 兼容声明保留；Commerce 公共操作显式使用用户 bearerAuth，内部接口继续要求服务凭证。

新建草稿前先在所有可信店铺探测原键结果，确认需要新建才读取地址快照。修复第二店铺旧草稿可能先读已删除地址的问题；外部账户调用位于本地事务完成后，付款/购物车版本/幂等/金额与原服务一致。

- 新 `PublicShoppingApiTest` 4 项先红，日志 `tmp/service-boundary-shopping-red.log`；初实现与原购物/金额/收货/多行数据库组通过，追加分页检查后最终该类 5 项通过。
- 最终 `-pl gateway,commerce-service -am -Dtest=CoreRoutesTest,PublicShoppingApiTest,BuyerPurchaseReadsTest,PublicCatalogApiTest,CartDatabaseTest,CheckoutPaymentDatabaseTest,MultiCheckoutDatabaseTest,CheckoutShippingDatabaseTest -Dsurefire.failIfNoSpecifiedTests=false test`：Gateway 23、Commerce 46 全过，无跳过。日志 `tmp/service-boundary-shopping-final2.log`。
- HTTP 身份桩只返回已签名主体的绑定与地址，不代理交易；真实 MySQL 验证跨买家/跨店购物车隔离、附加 customer_id 拒绝、禁用后401、第二店铺地址删除后原键重放、换请求体409、重复付款只有一笔订单、收货快照不变、购物车结算服务器金额与原键回执。
- 新归并单测 2 项验证相同微秒时间下原店内顺序、游标不能跨买家/归属/筛选复用、任一店失败不返回部分列表；HTTP 还验证真实两店分页。
- 公共购物/目录/身份及原购物、付款、购物车契约 58 过；新增 Ruff、定向 Spotless 通过。初次契约命令误指不存在的文件，0 tests 明确失败后改为现有文件重跑，不当作成功。
- 首次网关扩大用例出现桩默认404在POST未消费请求体时触发连接重置，修正 HTTP 测试桩读取请求体后，原404断言保持并通过；生产路由未为此放宽。

仍未运行项目浏览器或付费模型；商家、评价写入、原订单行视图与图片字节的迁移不在本步完成声明内。

## 商家交易、商品与评价直连

新增 Commerce `PublicMerchantController`、`PublicCatalogAdminController`、`PublicReviewController`，13 操作切到 Commerce，继续通过当前会话协议认证，服务自身按商家/买家匹配订单、商品与评价。购物车与付款等原领域规则、通知事件和资金路径不改。迁移评价限流到 Commerce，保留原 Redis 命名空间与账号/动作窗口；运行脚本及 Compose 显式启用，旧窗口不重置。

- 新增3个HTTP场景先红，原5场景通过；实现后完整 `PublicShoppingApiTest` 8过。新增场景覆盖本店/他店/买家访问商家交易、重复发货原键复用、本人履约、签收资格、跨买家评价、跨店回复、商品管理归属及请求体归属注入拒绝。
- 最终 `-pl gateway,commerce-service -am -Dtest=CoreRoutesTest,PublicShoppingApiTest,ReviewWriteLimiterRedisTest,PublicReviewLimiterApiTest,ProductReviewDatabaseTest,FulfillmentDatabaseTest,CatalogManagementTest -Dsurefire.failIfNoSpecifiedTests=false test`：Gateway36、Commerce32全过。真实隔离Redis的3项沿用原6次/60秒、两个实例原子共享窗口和暂停故障限时拒绝；HTTP额外验证429/503、Retry-After及失败不调用评价领域写入。
- 直接购物/商家契约、原履约/基础管理与运行驱动69过；新Ruff、定向格式、diff-check通过。原评价契约专题纳入集中收尾。日志 `tmp/service-boundary-merchant-red.log`、`merchant-green.log`、`merchant-final.log`、`merchant-contracts.log` 均在相同前缀目录。

商家展示资料写入与图片上传/读取仍在Case：实际文件与媒体归属库属于该进程，不能仅按商品URL把它切给没有文件的Commerce。普通商品管理已直连；原订单行API及旧门面默认停用仍待下一小步。

## 公共订单行查询直连

`PublicOrderController`/`PublicOrderReads`/`PublicOrderWire` 直接调用 Commerce 行查询，保留平台买家跨店标签、普通商家/旧商家客户范围、原分页默认值与字段可空语义；不通过账户接口代理订单。新 HTTP 场景先红，已有8场景保持；最终9场景过，覆盖订单/订单行跨买家和跨店404、商家读本店、旧客户响应不增加商家标签、跨店游标不能换买家、查询参数不能扩大客户范围。

- 最终 `-pl gateway,commerce-service -am -Dtest=CoreRoutesTest,PublicShoppingApiTest,PublicOrderReadsTest,OrderLineReadServiceDatabaseTest,AftercareProductReadDatabaseTest -Dsurefire.failIfNoSpecifiedTests=false test`：Gateway39、Commerce25过，原查询/售后商品读取未退化。新归并单测验证相同微秒时间下数据库原生顺序，不能改用Java字符串重排，绑定变化拒绝旧游标。
- 契约核对发现同名 `Cursor`/`OrderId` 在两服务含义不同：公共游标16384与内部200、订单ID路径与内部查询。新增语义对照先2红，再用 `PublicOrderCursor`/`PublicOrderId` 保留公共协议，不修改内部定义。新订单、原评价与平台买家契约14过；Ruff/定向格式/diff过。
- 日志 `tmp/service-boundary-orders-red.log`、`orders-green.log`、`orders-final.log`、`orders-contract-red.log` 与 `orders-contracts.log`，均保留先红和实际通过。未改已有数据库、旧评测或用户数据。

本步仅切换3个订单公共读取操作；Case内部订单客户端继续用于售后事实复核，属于必要领域协作。旧公开门面的生产停用与集中验收另行记录。

## 旧门面退出默认运行与集中验收

Case 的7个已迁移商城/订单控制器及3个仅供其使用的聚合/限流组件以 `resolveflow.compat.commerce-facade-enabled` 显式兼容开关装配，默认关闭。公共展示资料两个纯转发方法移入同样默认关闭的 `LegacyPublicPresentationController`；媒体与商家展示保存仍保留原控制器。旧测试基类显式启用兼容，不删除旧测试或断言。新增默认关闭测试明确断言所有旧控制器不存在、对应HTTP404，必要的账户、售后订单客户端与媒体控制器仍存在。

身份请求记录增加 `toString` 脱敏，避免记录类的默认字符串输出内嵌用户凭证。旧门面默认关闭测试先红，再与旧兼容HTTP、身份接口运行：Case34/共享脱敏1通过。新增展示拆分再运行默认关闭及原媒体HTTP组2项通过，生产默认关闭与历史兼容都保留。

### 三进程真实HTTP验收

`scripts/verify_service_boundaries.py` 启动3个真实JVM、带唯一label的临时MySQL/Redis，Case/Commerce分别使用独立库及最低权限账号；不启动Agent或模型/MQ worker，不调用现有项目服务。凭证仅在内存，运行目录在忽略tmp。脚本每次操作和停止容器前核对本轮label，结束停止本人启动的JVM与临时容器，未操作现有数据卷。

实际命令：设置JDK21后 `java/mvnw.cmd -f java/pom.xml -B -pl gateway,case-service,commerce-service -am -DskipTests package` 构建成功；`agent/.venv/Scripts/python.exe scripts/verify_service_boundaries.py` 最终8组全部通过，证据 `tmp/service-boundary-live/95e1e45beee14d6bae4f8068bfdd59ea/result.json`。断言包括：

- 默认Case旧目录404、Commerce与Gateway目录200，Gateway不公开internal路径。
- 正式注册/登录、本人地址、草稿原键复用、付款原键复用，仅新增一笔订单。
- 本人订单/订单行可读，其他买家及其他商家404，买家访问商家交易403；Case客户申请/咨询读取继续可用。
- 正式商家模拟发货与买家履约/原收货快照可读。
- 临时数据库内停用账号后受保护交易401；正式找回密码后旧token401，新登录可读原订单。
- 只停止本轮Case：Gateway商品及展示资料200，持原token的购物车503，不回退离线认证。
- 重启本轮Case：原当前会话与订单仍可读，未重复发布订单；最终本轮进程/容器均停止。

首次独立运行在订单数断言失败：Flyway自带历史种子订单，脚本误把总数当本轮新增数。保留失败目录 `tmp/service-boundary-live/2e1a27c29e9c41a3b1891e37709dd108`，改为本轮前后增量严格等于1；未改应用、删除种子或清库。

### 售后与契约收尾

- `-pl case-service,commerce-service -am -Dtest=AuthorizationConsumptionApiTest,ReviewDecisionApiTest,AgentCallbackApiTest,SupportRefundApiTest,RefundDispatchApiTest,MultiLineRefundDatabaseTest -Dsurefire.failIfNoSpecifiedTests=false test`：Commerce15、Case89过，无跳过；覆盖授权消费/审批、迟到回调、聊天退款与金额/多行退款。日志 `tmp/service-boundary-aftercare-regression.log`。未调用真实模型，也不是新跑完整Agent/MQ/provider链。
- 核心契约扩大检查发现本次迁移公共订单时漏带 `InvalidArgument` 响应组件；已补齐，所有Commerce文档内部引用检查通过。修补脚本最初将组件插到操作内，扩大检查继续失败后按完整行定位修正；两次错误保留，不将局部YAML可解析视为语义正确。
- 最终核心路由＋新增订单契约检查78过/7失败，失败集合与迁移前独立基线完全相同；无新失败。旧7项仍在，本批不称全部契约全绿。
- README与系统设计图改为Gateway并列路由Commerce/Case，明确暂部署于Case的账户模块与媒体边界；SVG源和2560px PNG同步、渲染审看，保留退款消息与Agent职责。

未运行浏览器完整点击、真实模型问答或新付费评测；前端未改接口URL。账户及媒体仍与Case同进程，未宣称全面故障隔离或物理身份服务拆分。

最后展示兼容控制器拆分后重新构建三个jar（`tmp/service-boundary-package-final.log`），同一驱动对最新二进制再次8组通过，最终证据 `tmp/service-boundary-live/461a4cbad03e4d56b947a6f971474fe3/result.json`，日志 `tmp/service-boundary-live-current.log`；随后核对无本轮临时容器、无三Java业务进程残留。中间两次成功验证分别保留，不累加成16个独立场景。

集中订单/购物/目录/身份/评价/平台买家/驱动契约72过；新增脚本与测试Ruff通过。`pnpm.cmd --dir web build` 含类型检查与Vite构建通过。SVG与PNG第二次审看修正箭头穿过文字，README与系统设计同步；未改变页面或依赖。工作区只保留开工前四个历史改动，本批精确提交排除它们。
