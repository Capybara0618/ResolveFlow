# 双端方案第一批：身份与租户基础

日期：2026-10-01。范围：用户批准的[双端方案](../../docs/product-completion-review.md)第一批。实现说明与全部演示凭证见[持久身份](../../docs/persistent-identity.md)，实际执行点统一见[todo顶部](../../tasks/todo.md)。

## 可体验行为

- 登录以Case数据库账号为准，已通过数据库新增账号登录测试，运行时不再依赖固定Java账号列表。
- 两个逻辑商家各有两位客户、两位审核员和一位管理员；原六账号密码与稳定subject保留。顶栏显示持久姓名、商家名与身份。
- 新`GET /api/v1/auth/me`返回公开当前身份。禁用账号/商家、身份版本变化、角色或绑定不一致拒绝旧JWT；重新启用不恢复已失效的版本。旧无版本JWT仅按0兼容。
- MERCHANT_ADMIN可查看本商家队列、工单、调查与政策。接管机制尚未实现，因此不能审批、核验、人工方案、工作台动作或工作人员取消；前端隐藏相应写按钮，服务端独立拒绝。
- M-1002/C-2005有新合成订单行7301、22900分支付账与模拟LOST物流。M-1002独立物流政策按支付时间选择，原M-2002历史损坏fixture和已绑定工单不改。

## 文件与兼容

- 共享JWT/Role：增加identity_version及MERCHANT_ADMIN，沿用HS256、audience、issuer与PBKDF2格式；DemoAccounts只作为旧fixture/密码校验兼容工具，不再作为登录bean。
- Case：PersistentAccounts、登录/me、RequestPrincipalResolver、CaseStaff与五类人工写边界；CaseRow/SSE可见范围显式使用工作人员角色。
- 追加Case V19、Commerce V8；不编辑已执行迁移，不回填或重写历史工单actor、订单及退款。
- 核心OpenAPI新增资料路由与Profile；同步登录角色/展示字段、路由账本及前端类型。演示驱动导入/索引两份M-1002政策。
- 测试：持久身份8例、JWT版本边界、数据库订单种子、管理员页面权限；历史跨商家测试新增明确的测试账号，保留原404断言。启动测试改用CaseDatabaseTest；旧材料更新断言对齐已交付的QUEUED重新调查，仍验证旧授权撤销和零有效授权。

## 集中验证

Java使用`JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1`，数据库测试使用MySQL 8.4 Testcontainers，与用户演示数据隔离。

| 命令 | 实际结果 |
| --- | --- |
| `./java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am test` | shared-kernel 62 passed；Case 265 passed、4 skipped；0失败/错误，BUILD SUCCESS |
| `./java/mvnw.cmd -f java/pom.xml -B -ntp -pl commerce-service -am -Dtest=OrderLineReadServiceDatabaseTest,InternalScopeEnforcementTest,OrderLineControllerTest,OrderLineContextControllerTest,OrderLineShipmentControllerTest -Dsurefire.failIfNoSpecifiedTests=false test` | Commerce 37 passed；shared因未匹配指定类不计入重复测试，BUILD SUCCESS |
| `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_core_schemas.py agent/tests/unit/test_contracts_core_corpus.py agent/tests/unit/test_reviewer_demo_driver.py -q` | 187 passed |
| `pnpm --dir web test`；`pnpm --dir web build` | 74 passed；类型检查及正式构建通过 |
| Maven `spotless:apply` / `spotless:check`，`-DspotlessFiles`只选择本批Java文件 | 本批格式校验通过，不格式化历史资金测试 |
| `.\demo.ps1 -NoBrowser` | 当前源码三个JAR构建通过；保留既有数据启动Java/只读Agent/桌面前端；19/8版迁移、两政策导入与READY索引实测 |
| Python urllib真实Gateway API + JSON Schema校验 | 11账号登录/me、四客户有订单、五次本人/跨商家订单隔离（包含伪造身份头）、两个管理员审批403、匿名me401通过 |
| Python urllib真实工单API | C-2005从7301建单，钉住M-1002的2026.09政策，外商家404；本人取消，审核侧读取CANCELLED。仅一个合成工单，无新批准或退款 |
| 本批文档本地链接核查；`git diff --check` / `git diff --cached --check` | 9份文档105个本地链接；差异检查通过 |

真实API记录见[api-acceptance.json](api-acceptance.json)，只保存合成ID、状态与核验摘要，不保存密码、JWT或原始模型日志。测试日志在忽略的tmp/identity-*，不作为仓库交付依赖。

## 失败、修复与未运行

1. 关键失败用例先执行：初始6个持久身份测试因无identity_account表失败；迁移/接线后通过，最终扩为8例。
2. 第一轮集中测试6失败：旧测试虚构JWT账号在新身份边界被401、全政策fixture数量5→7。补测试账号和正确数量后保持404/商家选择原断言，不放宽生产鉴权。
3. 完整Case测试发现旧PENDING_REVIEW断言已不符合此前QUEUED重新调查，另2个启动测试连接未启动的本机数据库。修正文义并使用同一真实测试数据库；最后完整Case通过。
4. 验证命令误写两个Python路径，导致零测试/退出4；按实际文件名重跑187通过，不把零测试视为成功。Spotless参数最初误用glob/管道regex，失败后改为逗号分隔regex并通过。
5. 一轮构建与测试重叠，构建清理target导致Case37个类加载错误与Commerce类加载失败；该轮无效结果保留。排除重叠后串行复跑通过。新增管理员审批测试最初缺授权必填字段返回422，补齐有效请求后得到预期403。
6. 末次暂存检查发现Windows写出的新JSON报告带CRLF，被仓库LF规则判为行尾空白；报告规范为LF后复查通过，未修改已有用户文件。

未运行：Case的RefundChainSystemTest三例与CoreEventTransportSystemTest一例均为原有显式可选系统测试，在本轮4 skipped；未声称全仓/整链路全绿。未重跑真实退款全链路、正式浏览器多账号协作验收、Agent完整旧矩阵或收费模型。后四批功能尚未完成，尤其客户分页列表/直接回答、领取/转交/接管、管理页面和站内待办。

身份禁用保证后续请求不能使用旧会话，不中止已开始事务或已建立的SSE。正式账号管理第三批必须递增身份版本；目前管理页面未提供这些入口。

本批真实模型调用0；Agent保持只读模式，现有调查记录可浏览。体验仍用原`.\demo.ps1`入口；需新的真实调查时由用户执行既有`.\demo.ps1 -Live`。
