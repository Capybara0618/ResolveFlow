# 商家角色合并验证

2026-10-03；批准范围见[三角色规格](../docs/merchant-role-merge.md)。本批改为买家、商家、平台三种使用者。MERCHANT_ADMIN协议名称保持，退款硬约束及历史多人兼容保留。

## 代码集中验证

- Java21：`java/mvnw.cmd -f java/pom.xml -pl case-service -am test -Dtest=MerchantSingleAccountTest,CaseCollaborationApiTest,CaseApiTest,StaffAdminApiTest,PlatformManagementApiTest,ReviewDecisionApiTest -Dsurefire.failIfNoSpecifiedTests=false -Dspotless.skip=true -q`，六类53 passed、0 skipped。覆盖创建事务自动归属、零/多个商家回滚、商家停用、旧专员登录拒绝、人员/释放拒绝、错误负责人版本及原审批/多人回归。
- Python：`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_foundation.py agent/tests/unit/test_contracts_platform_buyer.py agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_core_models.py agent/tests/unit/test_demo_foundation.py -q`，180 passed。AUTO_ASSIGN只在审计事件，不在客户端动作；single_operator只在商家身份。
- 网页：`pnpm --dir web test`，21文件154 passed；`pnpm --dir web build`通过。商家登录打开统一工作台，五个导航，售后无人员/领取入口；历史多人测试继续通过。
- 定点Spotless已执行；不格式化原有未提交Commerce测试及工程修改。

首次Java测试使用了错误的既有测试类/构造器引用，编译失败后对齐实际fixture再运行；协议编辑缩进导致YAML解析失败，修正后180项通过；构建发现旧协作历史标签缺AUTO_ASSIGN，补齐后构建通过。未删旧断言或靠跳过测试通过。

## 本机转换与流程

此代码验证节点尚未转换本机账号、没有新增交易或收费模型调用。接续先备份并保留现有业务数据转换，再集中真实HTTP和桌面验证；完成记录将追加在本节。
