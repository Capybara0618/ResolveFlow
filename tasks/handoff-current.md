# 当前执行说明：先审查v2桌面预期图，业务实施暂停

用户已要求调整初版，当前设计入口改为[v2图册](../docs/ui-targets-v2/index.html)、[实施合同](../docs/ui-targets-v2/README.md)和[复查记录](../docs/ui-targets-v2/review.md)。按角色导航、原始信息/核验/补证、新旧调查、人工方案及授权消费/UNKNOWN的合同理解图片；状态板不是新业务路由。初版16图及其审查仅作对比。当前仍不恢复业务写入，不把图片检查当业务验收，不据此假定用户已确认全部设计；实际进度只看[todo顶部](todo.md)。

用户最新明确要求先画出全部页面，再据预期图实施。页面组织采用客户端＋共用商家端，审核员对外称售后专员，管理员增加管理权限，不另建平台超级管理员。当前接手先看[todo顶部](todo.md)，不把下面原开工说明当作继续业务写入授权。

第二批有未提交客户接口原型及4项绿测试，前端尚未开始，完整契约/格式/回归未验收；保留工作区改动，不清库或重新实施第一批。设计提交只包括本设计资产和当前记录。后续按用户对图册的审查意见接续；绘图文字/样例不覆盖业务协议，不能凭图宣称功能已实现。已知实现待核对点：核心Case新增4路由后路由数量断言需同步，创建幂等重放的同商家其他客户归属检查需补回归；这些没有在本次作图中修复。原执行者图册提交后停止业务写入，接手仍需只读核对Git与并行归属。

2026-10-01用户已批准[双端与多人协作补齐方案](../docs/product-completion-review.md)，八项推荐决定均采用，并要求开始。按[plan](plan.md)新五批顺序实施；当前接续点看[todo顶部](todo.md)。批准涵盖两逻辑商家、种子/管理员账号、人工最终审批、领取制、补证保留负责人、管理员显式接管、文本材料及单商家账号；不扩大为企业平台或媒体上传。按功能批次集中验证和汇报，不逐按钮要求用户验收。

接续新第二批“用户完整申请”：先只读核对Git与运行归属，复用[持久身份](../docs/persistent-identity.md)及[第一批报告](../reports/product-identity/README.md)，不要重建身份表或重改旧迁移。先定义本人分页列表、客户专用详情/允许动作与问题回答契约，再贯通订单申请、我的申请、无需手填question_id的回答、撤销和公开结果。保持角色/merchant/customer服务器过滤、已消费输入冻结、回答与现有question_id关联及新修订调查；不要让客户使用管理员投影。管理员管理入口、领取/接管权限按第三批再实施。

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
