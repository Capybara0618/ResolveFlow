# 第四批：商家概览与政策阅读

2026-10-02，依据v2与[本批规格](../docs/merchant-workspace.md)。后台只读投影子步已完成，桌面页面与集中浏览器验证接续，此记录不表示整第四批完成。实际真实队列API＋新投影16 passed、前端`pnpm --dir web typecheck`通过；最后scope回归后Ruff行长失败已格式化并重新通过。

新增Case三个管理员只读接口和Agent一个内部精确版本索引状态接口。商家/当前身份范围由服务器确定；概览同一读快照全量计数、最多20条协调记录，原文从不可变bundle取，索引从Python持久generation查。无迁移、政策写入、Agent调用或资金动作。Case在数据库事务结束后读取有界索引客户端；不可用明确UNAVAILABLE。

实际验证：Java首次RED为2个404权限/路由失败和2个夹具漏填order_id错误；补齐字段后4 passed。增加当前修订失败/重复回调和我的补证待办后，MerchantWorkspaceApiTest 5、StaffAdminApiTest 11、CaseCollaborationApiTest 11，共27 passed。命令：Java21 `java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am -DspotlessFiles=.*MerchantWorkspace.*[.]java,.*AgentRunClient[.]java spotless:apply test -Dtest=MerchantWorkspaceApiTest,ReviewQueueWorkspaceTest,PolicySelectionServiceTest,CaseCollaborationApiTest,StaffAdminApiTest -Dsurefire.failIfNoSpecifiedTests=false`；其中两个历史类名不存在，未执行，不计入通过。随后用真实类MerchantWorkspaceApiTest、ReviewQueueApiTest集中复测，结果见后续记录。

Python首轮因默认55432库不可达2 skipped；显式使用演示PG55433及临时独立schema后，`pytest agent/tests/integration/test_policy_status_api.py agent/tests/integration/test_policy_index.py agent/tests/integration/test_run_api.py agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_core_schemas.py agent/tests/unit/test_contracts_core_reject.py -q` 187 passed。另一次调用错误文件名core_case/core_agent未执行测试，已纠正。补缺省scope拒绝后，索引新测试＋核心路由81 passed，覆盖实际PG READY/FAILED/BUILDING/MISSING、精确hash、跨商家、缺scope/主体和422。两新Python文件Ruff与Git diff检查通过。Case核心37条、Agent7条路由、严格schema/合成fixture、前端类型同步。未运行收费调查/模拟退款/整第五批流程。
