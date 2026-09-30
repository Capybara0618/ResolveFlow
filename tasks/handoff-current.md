# 当前执行说明：审查侧收尾

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
