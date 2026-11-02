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
