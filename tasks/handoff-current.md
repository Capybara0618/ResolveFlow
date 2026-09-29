# 当前执行说明：交给DSH执行剩余四批

2026-09-29用户决定将剩余四批交给DSH/DeepSeek执行。第一批“核验、补证后的调查闭环”已在928ec84完成，实现和验证见[闭环报告](../reports/reviewer-reinvestigation.md)，进度唯一来源仍为[todo顶部](todo.md)。

新执行入口：[DSH总手册与开工提示词](dsh-reviewer/README.md)，按[第二批](dsh-reviewer/02-demo-chain.md)→[第三批](dsh-reviewer/03-readable-sources.md)→[第四批](dsh-reviewer/04-agent-rag.md)→[第五批](dsh-reviewer/05-fields-visual.md)执行。这是[原计划](plan.md)的具体化，不另起路线。先修5个已知契约失败，再完成隔离mock演示；第一批不重做。

本次仅编写交接文档和保存用户参考图，没有启动剩余四批业务实施。以交接者最终回复“已停止写入”为接管点；接手先只读检查Git及并行进程，不覆盖不明改动。DS作为编码执行者不等于授权项目Agent收费live调用。

设计见[优化方案](../docs/reviewer-optimization.md)。不重做V3前端、AgentScope迁移、工作台接口、调查分项、原始记录投影和本次调查闭环，不恢复C12。

## 环境与验证

- E:\Code\Agent+Backend，PowerShell；main跟踪origin/main，远端https://github.com/Capybara0618/ResolveFlow.git。正常commit/push已授权，精确暂存；失败保留commit并报告。
- Java21：`$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'`，根目录使用`./java/mvnw.cmd -f java/pom.xml -B -ntp -pl case-service -am ...`。系统默认可能17。
- Python用`agent/.venv/Scripts/python.exe`；前端`pnpm --dir web test`及`pnpm --dir web build`；依赖沿用锁。
- 上次记录Docker核心七容器已启动、Gateway8080、Vite5173；本次文档交接未重验运行状态。接手检查实际进程，不重复占端口，不并行跑两个Compose up。
- 默认未开启Agent调查与MQ退款循环，服务健康不代表新工单会自动调查/退款。本轮未调用收费模型。
- 本地fixture审核账号demo-reviewer / demo-pass-1003。
- 第一批验证：Java 83 passed、OpenAPI 87 passed、前端35 passed及build通过；证据见[闭环报告](../reports/reviewer-reinvestigation.md)。扩展契约检查另有5个路由登记/参数失败，第二批手册已逐项指定修复位置；不能删除断言或当永久豁免。
- 其他验证证据见[原始记录交付](../reports/reviewer-sources/README.md)、[工作台](../reports/reviewer-workspace.md)、[消费保护](../reports/reviewer-consumed-input.md)。

## 原有未提交内容

以下并非本批功能，保留但不得夹带提交：docs/engineering.md、scripts/verify.ps1和verify.sh的共用rag-eval入口；Commerce的RefundAcceptanceApiTest既有资金测试（本轮未验证）；多个旧reports日志及provider SQLite。不要git add .，不提交数据库或敏感原始日志，不清库删卷。

tmp目录是忽略的构建日志和临时诊断脚本，按需读，不随Git同步；功能实现不依赖它。C12专属资产已按用户要求删除，共用和持久记录保留。新收费模型预算尚未获明确授权，不沿用旧C12预算。按功能批次集中验证以节省额度，不逐项打断用户。
