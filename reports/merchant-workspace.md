# 第四批：商家概览与政策阅读

2026-10-02，依据v2与[本批规格](../docs/merchant-workspace.md)。新第四批集中验收完成，接续第五批整体验收；不表示全部v2改造已经验收。后台子步2b352be已正常推送origin/main。实际真实队列API＋新投影16 passed、前端`pnpm --dir web typecheck`通过；最后scope回归后Ruff行长失败已格式化并重新通过。

新增Case三个管理员只读接口和Agent一个内部精确版本索引状态接口。商家/当前身份范围由服务器确定；概览同一读快照全量计数、最多20条协调记录，原文从不可变bundle取，索引从Python持久generation查。无迁移、政策写入、Agent调用或资金动作。Case在数据库事务结束后读取有界索引客户端；不可用明确UNAVAILABLE。

实际验证：Java首次RED为2个404权限/路由失败和2个夹具漏填order_id错误；补齐字段后4 passed。增加当前修订失败/重复回调和我的补证待办后，MerchantWorkspaceApiTest 5、StaffAdminApiTest 11、CaseCollaborationApiTest 11，共27 passed。命令：Java21 `java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am -DspotlessFiles=.*MerchantWorkspace.*[.]java,.*AgentRunClient[.]java spotless:apply test -Dtest=MerchantWorkspaceApiTest,ReviewQueueWorkspaceTest,PolicySelectionServiceTest,CaseCollaborationApiTest,StaffAdminApiTest -Dsurefire.failIfNoSpecifiedTests=false`；其中两个历史类名不存在，未执行，不计入通过。随后用真实类MerchantWorkspaceApiTest、ReviewQueueApiTest集中复测，结果见后续记录。

Python首轮因默认55432库不可达2 skipped；显式使用演示PG55433及临时独立schema后，`pytest agent/tests/integration/test_policy_status_api.py agent/tests/integration/test_policy_index.py agent/tests/integration/test_run_api.py agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_core_schemas.py agent/tests/unit/test_contracts_core_reject.py -q` 187 passed。另一次调用错误文件名core_case/core_agent未执行测试，已纠正。补缺省scope拒绝后，索引新测试＋核心路由81 passed，覆盖实际PG READY/FAILED/BUILDING/MISSING、精确hash、跨商家、缺scope/主体和422。两新Python文件Ruff与Git diff检查通过。Case核心37条、Agent7条路由、严格schema/合成fixture、前端类型同步。未运行收费调查/模拟退款/整第五批流程。

网页新增AdminOverview/AdminPolicies及共用桌面样式，保持v2白蓝工作台：真实汇总、异常优先协调表、启用人员、政策版本和原文/来源折叠阅读。管理员进入原详情才能领取/显式接管，不新增自动分配或政策编辑。专员五个业务入口（四个队列快捷项及工单查询），管理员另有概览/人员/政策，客户只有订单/申请。头像与角色采用真实账户姓名及明确角色。概览卡片计数是未结束待办，卡片进入现有归属队列后可按处理阶段进一步筛选；队列ALL含历史，不将其计数说成待办。

工作人员每30秒读取队列、客户可见申请列表每15秒读取，保持搜索草稿、所选详情及原审核弹窗版本；展开多页后不静默清空原行，有更新提示用户刷新。失败保留数据并可重试，读取失败不会变成“零工单/无政策”；失效会话退出，旧页面人工提交的迟到回调不会触发新会话。退出时同时清理原工单查询编号、核验草稿和审核上下文，补强原角色切换测试，最后整套108 passed＋build。已有原始材料、补证、政策引用、旧建议失效/调查失败继续复用；补齐消费/执行/UNKNOWN明确冻结提示，无批准或重复退款入口。终态仍显示已结束。

实际前端最终`pnpm --dir web test` **108 passed / 16 files**，`pnpm --dir web build`通过。新增覆盖全量计数展示、读失败保留、概览周期/卸载、无效身份、政策原文/迟到选择/索引不可用/失败与空态、队列新单发现/搜索保留/401退出、客户列表进展/查询保留、人工回调卸载和消费冻结。首次98 passed/1 failed是登录401被错误改写为会话失效提示，修正为仅已登录会话退出，保留原登录错误测试。新增客户用例首次105 passed/1 failed是错误placeholder定位，改用页面已有aria-label后通过。两次精确补丁因上下文未匹配失败，未产生部分改动，核对后重新应用。

保留数据执行`demo.ps1 stop`→`demo.ps1 -NoBrowser`重建三个JAR并启动只读Agent/Vite，受控导入跳过原6个政策，未重建索引或启用Live。Gateway实际读取两商家概览和4个本商家可见版本原文/READY索引；专员/客户三接口各403，跨商家政策404。独立验收脚本首轮因省略种子用户名的demo-前缀401，按持久身份说明纠正。脚本在忽略的tmp内，只作本次读取核验，产品不依赖它；结果留在[验证记录](merchant-workspace/verification.json)。重启及浏览器检查前后 **27工单、1归属、27政策绑定、6政策、11授权、78 run（状态/version/fence）完全不变**。原合成人员及凭据未修改，本轮主动收费调用/新增退款操作0。

正式浏览器完成：商家一概览13未领取/0我的待办/7需关注/14协调条目/4启用staff；点击协调进入既有UNKNOWN详情，看到输入冻结、跟踪原执行和无审批按钮。政策两版切换及原文/READY；商家二0/0/0空态、3启用staff与独立政策；专员我的工单空态和无管理菜单；客户本人17个申请及公开状态。概览、政策、客户列表1280/1440/1680没有水平溢出，见[尺寸记录](merchant-workspace/desktop-checks.json)。客户1280首次读取尚在加载，不计作列表验收，加载17条后补验通过。截图发现共用dl样式覆盖政策三列，提升选择器后重新截图核验；首次旧标签失效，换同一浏览器的新标签，不动共享5173。临时尺寸已恢复，保留管理员概览标签11。

截图：[商家概览](merchant-workspace/overview-desktop.jpg)、[政策原文](merchant-workspace/policies-desktop.jpg)、[商家二空态](merchant-workspace/merchant-two-empty.jpg)、[客户申请](merchant-workspace/customer-applications-desktop.jpg)。此批浏览器只读；实时多账号新单/补证/并发转交/批准付款的完整实际动作留第五批，不把组件模拟或历史证据记成本批完整闭环，也未运行批量收费评测、移动端或历史全量轨迹包。工作区原工程/verify/Commerce测试/旧日志保留，不夹带提交。
