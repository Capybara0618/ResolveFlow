# 当前执行说明：按v2预期图接续多人审核

2026-10-02用户已要求开始按v2实施。当前批次验收与记录以[todo顶部](todo.md)为准，证据见[客户批次报告](../reports/customer-workspace.md)。接手点为[plan](plan.md)新第三批“多人审核”，继续[实施对应说明](../docs/ui-implementation.md)的依赖顺序；不重做身份、客户工作台或既有审查/Agent。当前执行者在本批精确提交/正常推送和记录收尾后停止业务写入，接手先只读核对Git、账本及进程归属，不假定其他客户端已停。

当前设计入口为[v2图册](../docs/ui-targets-v2/index.html)、[实施合同](../docs/ui-targets-v2/README.md)和[复查记录](../docs/ui-targets-v2/review.md)。客户端＋共用商家端，审核员对外称售后专员，管理员增加管理权限，不另建平台超级管理员。按角色、原始信息/核验/补证、新旧调查、人工方案及授权消费/UNKNOWN理解图片；状态板不是新路由，位图检查不代表业务验收。初版及此前“先画图、业务暂停”的说明为历史背景，不再阻止已认可方向的范围内接续。

第三批先核对公共队列与所有人工写入口（核验、补证、人工方案、审批、撤销授权）的当前版本检查，再增加原子领取/释放/转交、负责人协作版本和管理员显式接管；补证保留负责人。人员管理限本商家，复用identity_account及身份版本，禁用/重置须拒绝旧会话并保护最后管理员。对应v2的07/10/11/14/16/18/19，不能先画可点击却无服务端权限的管理按钮。契约/类型/fixture同步，按功能批次集中验证，沿用旧锁/追加迁移/单行模拟退款约束。

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
