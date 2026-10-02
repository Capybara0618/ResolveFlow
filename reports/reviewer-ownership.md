# 人工归属保护与桌面协作验证

2026-10-02，接续新第三批。当前完成状态以[todo顶部](../tasks/todo.md)为准，规则见[协作协议](../docs/case-collaboration.md)。本报告证明本功能子步，不代表人员管理及整第三批完成。

## 实现与可演示行为

- `CaseCollaborationService.WritePermit`携带签名身份版本、原工单版本和协作版本。工作人员对材料、核验、取消、人工方案、review-actions及reviews写入时，在工单锁事务内校验当前负责人、两个读版本及持久身份。未领取、他人持当前版本、转交后旧页均不能写；缺失协作凭证409，非法输入422。reviews保留缺失If-Match的原422协议。
- 涉及文件为CaseCollaborationService、CaseStaff、CaseEvidenceService、CaseCancellationService、ManualProposalService、ReviewDecisionService、ReviewerWorkspaceService及三个现有控制器。客户回答/追加/撤销、Agent回调和执行结果继续使用各自领域权限，不强加人工负责人凭证。
- 人工方案和审批的Commerce/政策复核先在事务外执行，再在工单锁内检查相同读版本和授权。测试让RPC阻塞时管理员完成转交，原负责人响应随后409，未记录方案。不会在网络调用期间长期锁住工单/账号；最终可退金额仍由Commerce执行校验。
- V22仅追加修正V3/V10/V11旧角色CHECK及actor列120字符兼容。管理员必须先领取未领取工单或显式接管/转交给自己，再独立核验、补证、形成方案或审批；角色不等于负责人，Agent权限没有扩大。
- GET collaboration增加`is_owner`；GET `/api/v1/review/staff`返回本商家启用工作人员的显示身份，客户403，无其他商家、客户账号、口令/哈希。核心OpenAPI、路由表29条、fixture、前端类型和client同步。
- App、ReviewerWorkspace、CaseAssignment接真实归属和五字段协作历史；领取/释放/转交/接管须理由，转交目标来自目录。审批/人工方案弹窗保留打开时的业务/协作版本，409关闭并刷新；迟到目录响应不能污染其他工单。核验409也刷新归属，未领取/他人/终态不开放人工操作。
- reviewer_demo、reviewer_live_check、seed_review_showcase及e2e_resident_refund的合成写入显式领取并携带两版，拒绝自动抢占其他负责人。RefundChainSystemTest可选夹具同步领取和审批头，本轮只编译，未开启其4项外部系统测试。

## 实际命令与结果

Java使用`JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1`，数据库测试为独立Testcontainers，不清演示库。

| 命令/验证 | 实际结果 |
| --- | --- |
| Maven `-pl case-service -am -Dtest=ReviewerOwnershipApiTest -Dsurefire.failIfNoSpecifiedTests=false test`，实现前 | 有效RED：14项中13失败、1通过；旧写入口5类返回200、管理员核验403，暴露负责人缺失 |
| 同入口相关回归 | 初次协作/人工保护25 passed；原业务8类85项中83通过，两个兼容夹具/提示失败已修复；聚焦4类43 passed，不重复累加 |
| `java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am test` | shared62 passed；Case305项，301 passed、4 skipped。人工保护最终16用例，含六入口旧客户端/他人/转交、业务过期、管理员核验/方案/审批、RPC中转交及启用人员目录隔离 |
| `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_core_schemas.py agent/tests/unit/test_contracts_core_corpus.py agent/tests/unit/test_reviewer_demo_driver.py -q` | 最终192 passed，含两版条件头及合成驱动不能抢占他人 |
| `pnpm --dir web test` | 14 files、86 passed；覆盖未接管管理员只读、两版原弹窗提交、协作冲突不重试、切换后迟到目录丢弃及真实候选人 |
| `pnpm --dir web build` | 最终vue-tsc与Vite43 modules构建通过 |
| Maven定点 `spotless:apply spotless:check`，完整参数见[命令记录](reviewer-ownership/verification-commands.json) | 23文件通过；不格式化其他模块/用户脏文件 |
| Ruff两Python测试、四驱动py_compile、`git diff --check` | 通过。四驱动全文件Ruff存在旧诊断19/1/3/0条；与HEAD按诊断代码/消息/源行对比，新增0，见[基线记录](reviewer-ownership/script-lint-baseline.json)，不宣称全脚本Ruff通过 |
| `.\demo.ps1 status`、`.\demo.ps1 stop`、`.\demo.ps1 -NoBrowser` | 确认原进程归属后保留数据停止/重建三JAR/加载V21和V22/五进程只读启动成功；未清库、删卷或开启Live |

测试夹具的领取发生在已核实需要人工处理的工单创建后，调用生产协作服务；请求头来自明确读取。不在通用HTTP helper自动领取，不放宽服务端权限。旧身份测试保留五个拒绝断言，按新管理员权限改为404不可见或422无效方案；新增真实管理员工单覆盖接管前409、接管后核验/方案/审批200及存储角色，避免把角色调整误当越权成功。

失败记录：首次新增HttpHeaders helper误用containsKey编译失败，改为getFirst；第一次旧审批夹具补上本应缺失的If-Match，修正只加协作头，保留缺失版本422断言；冻结错误缺具体CANCELLED提示已修正。契约参数块最初插入response headers处导致39个解析失败，改为components.parameters后通过。Python读错驱动测试文件名没有运行测试，纠正为test_reviewer_demo_driver.py；前端第一次spy缺第四协作参数失败，补真实协作夹具和旧版保持断言。核验冲突刷新第一次传caseId而非CaseSnapshot，vue-tsc失败，修正后构建通过。Windows写入CRLF导致大范围diff/尾空白，统一仅本步文件LF后通过。首次浏览器早于Vite就绪连接失败、等待标题/精确select label定位失败，核对真实页面和服务状态后修正；没有重复提交新申请。临时日志/辅助脚本仅留tmp，不提交凭证或数据库。

## 浏览器与数据证据

本轮只新建合成工单`35011cca-4940-4cd1-a4ae-25398a793dda`，复用本人原已撤销、未退款的订单行91002015682。保留上次工单，不重置历史记录。浏览器操作均调用正式API：

1. 客户提交原始申请与文本材料；工作人员未领取时只有读取与领取入口。
2. 专员一领取，保留已打开拒绝弹窗；另一管理员会话转交专员二。原负责人提交被409拒绝，弹窗关闭、归属刷新、人工动作消失。
3. 管理员显式接管、释放、重新领取。五条独立协作历史为CLAIM/TRANSFER/TAKEOVER/RELEASE/CLAIM，协作版本5。
4. 管理员追加CONFIRMED独立核验记录，客户原文保留，数据库/响应appended_role为MERCHANT_ADMIN。管理员请求补证，客户看到并回答实际问题，不携带协作凭证；材料推进到第5版，负责人和协作版本仍不变。
5. 管理员人工拒绝结束，第6版CLOSED_REJECTED，负责人保留、可执行归属动作为空。客户看到公开理由，不能再追加或撤销；没有新退款授权或模拟付款。

[结构化验收](reviewer-ownership/acceptance.json)保存原始核验、归属历史、回答后状态、最终双端结果及时间线。只读SQL核对其他26工单的status/version/input_revision不变；比对上一客户批次62条历史run的status/version/fence均不变。新增工单自己的修订/run绑定可以正常变化，不混入历史不变结论。收费模型调用0，未启动mock全队列消费者。

桌面1280/1440/1680实际DOM宽度分别1265/1425/1680，不超过视口；[尺寸记录](reviewer-ownership/desktop-layouts.json)记录1280/1680，1440来自本轮截图与DOM测量。截图均实际本地页面：[管理员归属/待补证](reviewer-ownership/admin-owner.png)、[管理员结束](reviewer-ownership/admin-final.png)、[客户结果](reviewer-ownership/customer-final.png)。中段[等待补证截图](reviewer-ownership/admin-waiting.png)展示人工处理状态与政策区域。视觉截图不替代接口/并发测试。

## 尚未完成/未运行

第三批仍需公共/我的/未领取队列、每行负责人及真实服务器计数、最小人员管理和最后管理员保护。当前目录只是转交选择，不是人员管理；队列length仍是已加载数。负责人跨会话主动推送未实现，依靠刷新/冲突处理。

本轮未跑全Python/SDK/live质量、Commerce全资金矩阵、四项可选外部系统链路或完整五批总体验收；不继承旧报告作本轮通过。只读Agent不开展新模型调查，页面如实显示没有当前记录，已有live成果继续保留。历史engineering/verify脚本/Commerce测试/旧日志原样保留并排除提交。
