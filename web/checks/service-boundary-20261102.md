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
