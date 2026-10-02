# 当前执行说明：v2新五批已收口，等待用户新要求

2026-10-02第五批正式网页集中验收已完成，当前唯一进度以[todo顶部](todo.md)为准；证据/实际命令/失败/未运行见[第五批报告](../reports/product-flow.md)，日常启动及体验见[浏览器指南](../docs/browser-experience.md)。三客户、四专员、管理员及两商家五新申请已终态：三笔329元模拟退款恰好各一成功操作、一拒绝、一撤销；48项隔离/冻结及独立停用会话通过。Java84、Python189、前端109/build、Ruff/diff通过，费用调用0，原27工单/78run及政策/授权/资金快照保持。三个小修复已推送11cbd59/b30e300/1772597；本批最终记录与驱动提交以Git/todo为准。

当前实施者精确提交/正常推送本批收尾后停止业务写入，没有默认第六批。下一执行者先只读核对工作区、账本及`demo.ps1 status`，不假设其他客户端已停，也不重做已交付五批。现有只读演示进程保留5174/8180/8182；日常新调查由用户自己`demo.ps1 -Live`，不要为了截图开启收费调查。已成功退款不能重置复用；manifest内E失败run保留FAILED及原预算/deadline，HUMAN第3版成功审批，D取消派发仍QUEUED而Case已终态，不能据此自动清库或扫历史队列。原UNKNOWN保持原操作及占用。报告明确mock/失败恢复/历史run读取/上下文/公开通用轨迹文字等限制，不宣称企业平台或所有live异常自动恢复完成。

下列“接续第五批”段落是收口前的实施依据与历史，不再作为开工指令。

2026-10-02用户已要求开始按v2实施。当前批次验收与记录只以[todo顶部](todo.md)为准，本批收口证据见[商家工作台报告](../reports/merchant-workspace.md)，此前[人员管理报告](../reports/staff-management.md)与[客户批次报告](../reports/customer-workspace.md)继续复用。接手点为[plan](plan.md)新第五批“整体验收与说明”，继续[实施对应说明](../docs/ui-implementation.md)的依赖顺序；不重做身份、客户、多人审核、商家只读页面或既有审查/Agent。当前执行者在本批精确提交/正常推送和记录收尾后停止业务写入，接手先只读核对Git、账本及进程归属，不假定其他客户端已停。

当前设计入口为[v2图册](../docs/ui-targets-v2/index.html)、[实施合同](../docs/ui-targets-v2/README.md)和[复查记录](../docs/ui-targets-v2/review.md)。客户端＋共用商家端，审核员对外称售后专员，管理员增加管理权限，不另建平台超级管理员。按角色、原始信息/核验/补证、新旧调查、人工方案及授权消费/UNKNOWN理解图片；状态板不是新路由，位图检查不代表业务验收。初版及此前“先画图、业务暂停”的说明为历史背景，不再阻止已认可方向的范围内接续。

第三批已完成公共队列与所有人工写入口（核验、补证、人工方案、审批、撤销授权）的版本检查、原子领取/释放/转交、负责人协作版本和管理员显式接管；接续复用，补证保留负责人。人员管理限本商家，复用identity_account及身份版本，禁用/重置须拒绝旧会话并保护最后管理员。对应v2的07/10/11/14/16/18/19，不能先画可点击却无服务端权限的管理按钮。契约/类型/fixture同步，按功能批次集中验证，沿用旧锁/追加迁移/单行模拟退款约束。

接续入口为[协作协议](../docs/case-collaboration.md)、CaseCollaborationService/Controller及[人工归属保护报告](../reports/reviewer-ownership.md)，完成状态仅看todo顶部。人工入口已有当前负责人、独立协作版本、原业务版本和锁内签名身份检查；管理员显式接管后可人工处理，V22兼容旧角色CHECK与actor宽度。App/ReviewerWorkspace/CaseAssignment已接真实归属、目录、操作与旧弹窗保护，不重做这些成果。

第三批人员管理已完成，接口/权限/锁序见[规格](../docs/staff-management.md)，真实验收与失败见[报告](../reports/staff-management.md)。AdminPeople及管理员菜单已有本商家真实筛选分页、维护/启停/角色、新增/重置/审计，打开时账号版本及安全字段旧会话失效，自身变更立即退出；last admin保护由服务端事务保证。原归属/队列及人工写约束不重做。V23已追加到保留数据的演示库；后端已推送d353553，本功能最终提交以Git/todo为准。独立合成人员synthetic-people-1002180836已停用、v9、审计9条；种子账号及27个原工单没有修改。网页登录新增/重置只检查空弹窗及取消，真实凭据生命周期由独立HTTP/API与组件测试覆盖；未调用Live。

第四批实施入口为[规格](../docs/merchant-workspace.md)及MerchantWorkspaceService/Controller、PolicyIndex metadata、AdminOverview/AdminPolicies。本商家真实计数/原文/精确hash索引状态已接线，Case37/Agent7条核心路由。概览计数仅未结束待办，跳转现有归属队列ALL含历史，可以继续按阶段筛选；不以页面长度冒充真实总数。人员停用/当前失败/UNKNOWN各有明确协调原因，阅读政策不影响钉住版本。队列30秒、客户列表15秒可见空闲读取，多页保留与提示，401退出、旧回调不影响新会话。后台投影子步已推送2b352be，整批最终提交查Git/todo，不凭旧段落重做。

下一批以正式页面集中验证多客户提交→多专员看到新单→明确领取/转交/管理员接管→原始材料/调查与政策阅读→补证后新调查→拒绝/批准及模拟退款结果；同时测试跨商家404、旧版本/旧负责人冲突、失效身份和消费冻结/UNKNOWN原operation追踪。优先复用现有合成驱动，在新增专用样本上执行，不能重置27个旧工单或复用一次性付款样本再退款。只读页面与组件模拟通过不等于这套实际多账号流程已经验收。复用demo.ps1启动入口，补清楚用户自行启动/浏览器体验说明；mock/live/历史证据分开，未运行及失败明确记录，不启动批量收费评测或恢复CXX/C12。范围内缺陷直接修复，按功能批次验证，不另规划产品。

先执行demo.ps1 status核对进程归属；当前保留数据重建后的只读demo（Gateway8180、Agent8182、Vite5174）。第四批只读前后27工单/1归属/27政策绑定/6政策/11授权/78 run状态/version/fence不变。不要为截图开启Live，保留已保存run和合成工单35011cca-4940-4cd1-a4ae-25398a793dda的人工拒绝终态；UNKNOWN ce263102-965d-4dee-974f-351c9800b5cb仍原执行编号0bc48b1b-d9e1-4ca4-947f-995524f68979。种子名称是demo-admin、demo-admin-m2、demo-reviewer、demo-customer等，不能省略demo-前缀；密码见持久身份说明，不在日志记录token/key。保留浏览器标签11管理员概览，临时桌面尺寸已重置。每个验证通过的独立子步精确commit/正常push；最终第五批验收通过才宣称整套v2体验完成。

2026-10-01用户已批准[双端与多人协作补齐方案](../docs/product-completion-review.md)，八项推荐决定均采用，并要求开始。按[plan](plan.md)新五批顺序实施；当前接续点看[todo顶部](todo.md)。批准涵盖两逻辑商家、种子/管理员账号、人工最终审批、领取制、补证保留负责人、管理员显式接管、文本材料及单商家账号；不扩大为企业平台或媒体上传。按功能批次集中验证和汇报，不逐按钮要求用户验收。

客户侧实现入口为[CustomerWorkspace](../web/src/ui/CustomerWorkspace.vue)、[专用契约](../docs/customer-workspace.md)与CustomerCaseService，继续保持专用投影、服务器范围过滤、版本回答、消费冻结及UNKNOWN不重付。scripts/customer_workspace_acceptance.py只对已保存manifest内新工单定点mock调查，不消耗其他排队run；当前3条样本已终态，不重置或重复退款。Agent上下文无损字段表已有回归，累计多材料仍可超8K并转人工；这项限制在报告保留，不声称已验收live质量，也不通过删约束/增预算处理。当前5174只读demo保留数据，先status核对，不为截图启动-Live。

第一批验证留下只读演示服务与一个已取消的合成7301验收工单，详细合成ID在报告；不凭本文假定服务仍在运行，先查status。原执行者本批提交后停止业务写入，其他客户端仍须先核对账本/Git再接管。

下列2026-09-30信息是已交付审查侧的环境与历史证据，不是下一步实施指令。

2026-09-30用户授权的审查侧收尾已完成集中验证，实际进度只看[todo顶部](todo.md)，证据、失败和未运行项见[收尾记录](../reports/reviewer-completion.md)。DeepSeek V4.1 Flash使用官方API模型ID deepseek-flash，密钥仅从用户环境变量读取。旧五批成果沿用；用户侧改造由用户另行确定，不自动开启新路线。

2026-09-29审查员五批优化已经实施完毕，实际成果和限制以[todo顶部](todo.md)及各批交付报告为准。第一批“核验、补证后的调查闭环”见[闭环报告](../reports/reviewer-reinvestigation.md)，第二至第五批分别见演示链路、依据阅读、Agent/RAG诊断和视觉报告。

用户最新确认项目只需要桌面网页端，不做移动端产品。已有窄屏响应式代码保留为普通网页兼容兜底，不再安排移动端专项实现或验收。后续如继续改视觉，以参考图的桌面布局和真实业务行为为准。

项目Agent已完成有限真实模型验证，包含成功、人工接管与受控失败；不是对模型正确率的保证。补证回答进入新run、真实待审建议、浏览器批准后模拟退款成功和人工拒绝终态均有证据。接手先只读检查Git及并行进程，不覆盖不明改动；执行者切换仍需确认原执行者停止写入。

设计见[优化方案](../docs/reviewer-optimization.md)。不重做V3前端、AgentScope迁移、工作台接口、调查分项、原始记录投影和本次调查闭环，不恢复C12。

## 环境与验证

- 日常完整浏览器体验从仓库根目录执行`.\demo.ps1 -Live`，默认打开`http://127.0.0.1:5174`；用户环境变量Deepseek_API_KEY提供密钥。`.\demo.ps1 status`查看进程，`.\demo.ps1 stop`停止且保留演示数据；无-Live仅关闭新Agent调查。入口复用`scripts/reviewer_demo.py`的隔离、归属与端口检查，不另起共享环境。
- E:\Code\Agent+Backend，PowerShell；main跟踪origin/main，远端https://github.com/Capybara0618/ResolveFlow.git。正常commit/push已授权，精确暂存；失败保留commit并报告。
- Java21：`$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'`，根目录使用`./java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am ...`。系统默认可能17。
- Python用`agent/.venv/Scripts/python.exe`；前端`pnpm --dir web test`及`pnpm --dir web build`；依赖沿用锁。
- 隔离演示栈支持只读/Live Agent模式切换，Gateway8180、Agent8182、桌面Vite5174；共享5173不由该入口改动。接手先执行`.\demo.ps1 status`检查实时归属，不能凭本文假定进程仍在运行。
- -Live开启真实调查；两种模式均开启Java/MQ模拟退款。已保存57次成功响应及usage，另2次HTTP400；详情见收尾记录。不要为截图或复查反复创建收费调查，已有结果可直接浏览。
- 本地fixture审核账号demo-reviewer / demo-pass-1003。
- 最终本轮相关Python235 passed、前端73 passed和build；Java9 passed及三个JAR构建通过。旧五批测试结果留在各自报告；历史5个路由登记/参数失败已在第二批修复，不要重复修复。已知5个过期committed golden pack本轮未运行，不伪装为通过。
- 其他验证证据见[原始记录交付](../reports/reviewer-sources/README.md)、[工作台](../reports/reviewer-workspace.md)、[消费保护](../reports/reviewer-consumed-input.md)。

## 原有未提交内容

以下并非本批功能，保留但不得夹带提交：docs/engineering.md、scripts/verify.ps1和verify.sh的共用rag-eval入口；Commerce的RefundAcceptanceApiTest既有资金测试（本轮未验证）；多个旧reports日志及provider SQLite。不要git add .，不提交数据库或敏感原始日志，不清库删卷。

tmp目录是忽略的构建日志和临时诊断脚本，按需读，不随Git同步；功能实现不依赖临时验收脚本。C12专属资产已按用户要求删除，共用和持久记录保留。本轮有限真实接入与调查由用户明确授权，未沿用旧C12预算；后续不自动开启批量付费评测。按功能批次集中验证以节省额度，不逐项打断用户。
