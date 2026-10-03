# 商家角色合并验证

2026-10-03；批准范围见[三角色规格](../docs/merchant-role-merge.md)。本批改为买家、商家、平台三种使用者。MERCHANT_ADMIN协议名称保持，退款硬约束及历史多人兼容保留。

## 代码集中验证

- Java21：`java/mvnw.cmd -f java/pom.xml -pl case-service -am test -Dtest=MerchantSingleAccountTest,CaseCollaborationApiTest,CaseApiTest,StaffAdminApiTest,PlatformManagementApiTest,ReviewDecisionApiTest -Dsurefire.failIfNoSpecifiedTests=false -Dspotless.skip=true -q`，六类53 passed、0 skipped。覆盖创建事务自动归属、零/多个商家回滚、商家停用、旧专员登录拒绝、人员/释放拒绝、错误负责人版本及原审批/多人回归。
- Python：`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_foundation.py agent/tests/unit/test_contracts_platform_buyer.py agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_core_models.py agent/tests/unit/test_demo_foundation.py agent/tests/unit/test_reviewer_demo_driver.py -q`，最终206 passed、0 skipped（初轮180；补升级守卫及旧启动回归）。AUTO_ASSIGN只在审计事件，不在客户端动作；single_operator只在商家身份；未给apply/备份失败不转换或构建。
- 网页：`pnpm --dir web test`，最终21文件157 passed；`pnpm --dir web build`通过。商家登录打开统一工作台，五个导航，售后无人员/领取入口；单商家批准/补证/拒绝保留确认当时版本，旧多人测试继续通过。最后仅纠正测试中的负责人面板选择器，`pnpm --dir web exec vitest run tests/app.spec.ts tests/foundation.spec.ts`复测通过。
- 定点Spotless已执行；不格式化原有未提交Commerce测试及工程修改。

首次Java测试使用了错误的既有测试类/构造器引用，编译失败后对齐实际fixture再运行；协议编辑缩进导致YAML解析失败，修正后180项通过；构建发现旧协作历史标签缺AUTO_ASSIGN，补齐后构建通过。未删旧断言或靠跳过测试通过。

## 本机转换与流程

代码节点990c93c已推送并确认远端。随后执行`agent/.venv/Scripts/python.exe scripts/merge_merchant_accounts.py --apply`：固定compose项目/端口/容器标签/唯一商家守卫，停止所属应用，备份到`tmp/reviewer-demo/backups/20261003-120206-290778`，构建三JAR并追加V26，保留数据转换。原清库前备份20261003-104641-179070未替代。46个业务表逐行值排序后hash/计数在转换前后相同，见[脱敏证据](merchant-merge/conversion.json)；初始订单和工单均0，没有以空白验证冒充历史交易转换实测。无历史引用的staff01–06删除，三商家身份版本更新，10买家与平台保留。脚本有历史引用时保留禁用人员、未消费工单转归属及历史冻结保护，本机无旧工单所以该历史转换分支未制造实测样本。

执行`demo.ps1 -SkipBuild -NoBrowser`恢复服务，`agent/.venv/Scripts/python.exe scripts/merchant_merge_acceptance.py`集中真实HTTP **77项通过**：14账号可登录、6旧专员401，三店各10商品，两店读取404，买家和平台不能审批403，单商家人员创建/释放403，旧协作版本409。三店买家新购→申请自动归属admin01/02/03、协作版本1/AUTO_ASSIGN/SYSTEM→指定run生产AgentScope、真实MCP与PG dense→人工批准→329/129/169元模拟退款成功，每行成功操作1次、预留0。[机器报告](merchant-merge/verification.json)：3run completed、12次mock模型调用/9工具观察，全部按这3个run统计，Live0；没有扫原队列或重置预算。

三个标注合成集中验收的订单和退款成功工单保留，未在验收后reset。当前仍3店/30商品/45SKU/14启用账号/3READY索引，见[当前状态](merchant-merge/state.json)。普通start再次复用健康所属进程通过，未重复初始化；此时verify的“初始空白”检查不适用，日常使用status。旧foundation_acceptance入口现在委托三角色驱动，历史20账号实现保留在Git历史；不要把验收驱动加入普通启动。

正式浏览器同一admin01登录，五个入口、本店10商品、交易原实付与已退状态、绑定政策原文、售后终态及原始调查记录可见，没有人员/领取面板。新工单默认全部阶段，处理中申请不会因待审筛选消失。1280工作台/1440工作台和售后无横向溢出，主要新概览标签16px，减少重复小字；浏览器临时尺寸已恢复，原用户商城标签保留。截图：[工作台](merchant-merge/workspace.jpg)、[售后](merchant-merge/aftercare.jpg)。本次浏览器只核对终态和入口，审批动作由真实HTTP及单账号网页回归覆盖；未在浏览器再次造订单或收费模型。

Ruff check覆盖本轮新转换/验收、初始化数据/脚本与测试通过；Spotless/构建通过。没有全仓回归、新Live质量评测、真实支付/库存/移动端、公开入驻或新店自助政策。新建店使用同一商家角色，但政策/索引仍需受控准备。日常使用[新指南](../docs/clean-demo-experience.md)：`demo.ps1 -Live`启动之后新申请的真实调查；当前只读Agent8182和网页5174健康。
