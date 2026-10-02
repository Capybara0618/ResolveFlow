# 多人审核：协作基础验证

2026-10-02。本次接续[新第三批](../tasks/plan.md)，协议见[工单协作](../docs/case-collaboration.md)。当前完整进度只在[todo顶部](../tasks/todo.md)。本报告仅证明协作API及独立数据基础，不代表第三批整体完成。

## 可复现行为

- 新增Case V21：独立负责人/协作版本/操作历史。旧工单不回填负责人，读取为`owner:null,version:0`。
- 两条正式API：GET/POST `/api/v1/cases/{case_id}/collaboration`；同商家工作人员读，客户403，跨商家404。POST复用有效JWT并携带`If-Collaboration-Match`。
- CLAIM/RELEASE/TRANSFER/TAKEOVER在工单锁内原子执行；两专员并发领取一200、一409，只有一个协作事件；重复本人领取不增加事件。
- 非负责人即使携带正确协作版本也不能释放/转交；转交回来后旧版本仍失败。管理员覆盖现有负责人必须显式接管或转交，有理由/actor/from/to记录。
- 目标限本商家启用工作人员；客户、禁用、其他商家和不存在统一422。禁用负责人保留展示，可由管理员释放或接管可协作工单。
- 案例原始行（包括业务版本/修订/状态/时间）完整不变，Agent binding、业务时间线和Outbox均无新增。WAITING_CUSTOMER保留负责人。已批准/执行/对账/终态和“PENDING_REVIEW但授权已消费”冻结负责人变更。
- 工单锁后，商家共享锁及按username排序的账号共享锁中复核入口捕获的签名身份版本，避免密码重置/角色变更/禁用在入口校验后失效仍写入。`RequestPrincipalResolver.Session`复用既有JWT校验，不改签名协议/角色/登录会话。
- 核心OpenAPI、路由表、合成协作fixture和前端类型/API方法同步；既有页面暂未调用这些新方法。

## 实际验证

所有Java数据库测试使用CaseDatabaseTest独立Testcontainers MySQL；未清理演示数据库。

| 命令 | 实际结果 |
| --- | --- |
| `JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1`；`java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am '-Dtest=CaseCollaborationApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test`，实现前 | 有效RED：9 tests，9 failures，旧路由404；并发用例两次404 |
| 同入口，`-Dtest=CaseCollaborationApiTest,PersistentIdentityApiTest,ReviewQueueApiTest` | 最终27 passed（协作11、身份8、队列8）；补非负责人携带当前版本的断言后，单跑协作11 passed，不重复累加数量 |
| `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_core_models.py agent/tests/unit/test_contracts_core_profile.py -q` | 176 passed；仅整理导入/旧长行后再跑routes，73 passed；不累加 |
| `pnpm --dir web test` | 13 files / 83 passed；页面行为未修改 |
| `pnpm --dir web build` | vue-tsc通过、Vite 40 modules构建通过 |
| Maven `-pl case-service '-DspotlessFiles=.*CaseCollaboration.*[.]java,.*RequestPrincipalResolver[.]java' spotless:apply spotless:check` | 仅本次4个Java文件，通过 |
| `agent/.venv/Scripts/python.exe -m ruff check agent/tests/unit/test_contracts_core_routes.py`、`git diff --check` | 修复后通过 |
| Python pathlib/re正则定点检查协作协议、报告、handoff及fixture | 28个本地文档链接和2条协作历史夹具一致性通过 |
| `.\demo.ps1 status` | 原只读demo五进程仍运行，端口5174/8180/8181/8182/8183；只读取现状，未重启或部署本次JAR |

失败保留：首次实现编译因Event构造多取一列失败，修正为对应7列后通过。首轮协作9+身份8+队列8共25通过；新增消费回归首次fixture直接插入CONSUMED但缺审批决定，触发数据库`chk_authorization_decision`，是无效夹具，不算业务RED；改为合法PENDING_REVIEW→decide→consume后27通过。首次Ruff发现新增导入顺序及本文件原有客户例子长行，整理格式未删断言后通过。首次契约补丁误写前端导出名，整块未应用，核对coreApi后重新应用；读取阶段若干误写历史路径已更正，不计通过。日志留在本机tmp，不提交原始日志或凭证。

## 尚未验收的边界

这次未接入旧核验/补证/人工方案/审批/工作人员取消等写入口，现有工作人员操作仍按原有角色和业务版本校验，**还没有统一负责人限制**。新协作API不应被解读为所有旧操作已被安全约束。MERCHANT_ADMIN仍受第一批人工写禁令，接管后还不能通过旧入口审批。

下一子步需统一锁内负责人/协作版本/账号身份版本/业务版本检查；补充旧客户端未领取提交409及转交后旧页写入失败回归，保留客户回答、Agent回调和执行结果不需负责人凭证。检查审批的Commerce复核网络调用事务边界，不将网络/模型放入新的协作锁事务。V3/V10/V11的appended_role/decided_role/authored_role数据库CHECK和核心ProposalView.authored_role仍有旧角色限制，需追加迁移和同步协议，不能编辑已运行迁移；相关actor列长度也需与新账号规则一致。

公共/我的/未领取队列筛选和真实计数、人员管理及最后管理员保护、桌面领取/转交/接管界面未实施，正式浏览器第三批闭环未运行。未跑全仓Java、Commerce资金矩阵、完整Python/SDK/live模型质量或付费调用；本步模型调用0，未支付模拟退款、未清库/删卷。已有用户和他人脏文件保留，不纳入本步提交。
