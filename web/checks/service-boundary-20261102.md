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
