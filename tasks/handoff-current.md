# 当前执行说明：审查员五批已完成

2026-09-29审查员五批优化已经实施完毕，实际成果和限制以[todo顶部](todo.md)及各批交付报告为准。第一批“核验、补证后的调查闭环”见[闭环报告](../reports/reviewer-reinvestigation.md)，第二至第五批分别见演示链路、依据阅读、Agent/RAG诊断和视觉报告。

用户最新确认项目只需要桌面网页端，不做移动端产品。已有窄屏响应式代码保留为普通网页兼容兜底，不再安排移动端专项实现或验收。后续如继续改视觉，以参考图的桌面布局和真实业务行为为准。

DS作为编码执行者不等于项目Agent已完成收费live验证；真实模型质量仍是NOT_RUN。接手先只读检查Git及并行进程，不覆盖不明改动。

设计见[优化方案](../docs/reviewer-optimization.md)。不重做V3前端、AgentScope迁移、工作台接口、调查分项、原始记录投影和本次调查闭环，不恢复C12。

## 环境与验证

- 日常浏览器体验从仓库根目录执行`.\demo.ps1`，默认打开`http://127.0.0.1:5174`；`.\demo.ps1 status`查看进程，`.\demo.ps1 stop`停止且保留演示数据。入口复用`scripts/reviewer_demo.py`的隔离、归属与端口检查，不另起共享环境。
- E:\Code\Agent+Backend，PowerShell；main跟踪origin/main，远端https://github.com/Capybara0618/ResolveFlow.git。正常commit/push已授权，精确暂存；失败保留commit并报告。
- Java21：`$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'`，根目录使用`./java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am ...`。系统默认可能17。
- Python用`agent/.venv/Scripts/python.exe`；前端`pnpm --dir web test`及`pnpm --dir web build`；依赖沿用锁。
- 隔离演示栈已用`.\demo.ps1 -SkipBuild -NoBrowser`完成停机后恢复实测，当前Gateway8180、只读Agent8182、桌面Vite5174及演示compose在运行；共享5173不由该入口改动。接手先执行`.\demo.ps1 status`检查实际归属，不重复占端口。
- 默认未开启Agent调查与MQ退款循环，服务健康不代表新工单会自动调查/退款。本轮未调用收费模型。
- 本地fixture审核账号demo-reviewer / demo-pass-1003。
- 第一批验证：Java 83 passed、OpenAPI 87 passed、前端35 passed及build通过；证据见[闭环报告](../reports/reviewer-reinvestigation.md)。扩展契约检查另有5个路由登记/参数失败，第二批手册已逐项指定修复位置；不能删除断言或当永久豁免。
- 其他验证证据见[原始记录交付](../reports/reviewer-sources/README.md)、[工作台](../reports/reviewer-workspace.md)、[消费保护](../reports/reviewer-consumed-input.md)。

## 原有未提交内容

以下并非本批功能，保留但不得夹带提交：docs/engineering.md、scripts/verify.ps1和verify.sh的共用rag-eval入口；Commerce的RefundAcceptanceApiTest既有资金测试（本轮未验证）；多个旧reports日志及provider SQLite。不要git add .，不提交数据库或敏感原始日志，不清库删卷。

tmp目录是忽略的构建日志和临时诊断脚本，按需读，不随Git同步；功能实现不依赖它。C12专属资产已按用户要求删除，共用和持久记录保留。新收费模型预算尚未获明确授权，不沿用旧C12预算。按功能批次集中验证以节省额度，不逐项打断用户。
