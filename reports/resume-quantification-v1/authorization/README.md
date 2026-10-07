# 版本授权矩阵（2026-10-07）

真实 Case Spring HTTP 和隔离 Testcontainers MySQL；Commerce 资格来源是显式 fixture stub。此批证明授权消费边界，不将它计为真实 MQ 或资金结算实验。

8 类各 10 轮，共 80 个场景；V8 每轮尝试两个旧版本，因此共 **90 次旧授权尝试，90 次拒绝；80 次有效授权控制全部消费成功；非法消费 0**。另有 10 次消费先提交，随后修改输入均被拒绝。V4/V5/V6 用双线程屏障固定提交先后。每轮断言旧授权不产生执行命令、当前授权消费并产生一个命令；未用随机竞争命中率替代状态验证。

原始 90 份逐轮记录在 `attempt2/`，汇总和文件 SHA 在 [summary.json](summary.json)。`ResumeAuthorizationMatrixApiTest` 共 93 项通过（80+10+继承的3项回归），0 失败/错误/跳过。首次执行因继承的嵌套测试配置未自动导入导致依赖注入失败；明确 Import 后重跑，未将失败批次计为完成矩阵。

同批新增实际 Mapper 调用处 inflight/peak gauges。`ReviewQueueBackpressureTest` 2 项通过：受控阻塞时 inflight/peak 为 8，12 并发中 4 请求拒绝，释放后 inflight 回到 0。这是受控数据库测试；正式 HTTP Redis 故障峰值另外测量。

实际命令：

```powershell
java/mvnw.cmd -f java/pom.xml -pl case-service -am '-Dtest=ResumeAuthorizationMatrixApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dresolveflow.resume.authorization.report-dir=reports/resume-quantification-v1/authorization/attempt2' test
java/mvnw.cmd -f java/pom.xml -pl case-service -am '-Dtest=ReviewQueueBackpressureTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
agent/.venv/Scripts/python.exe scripts/resume_authorization_summary.py
```

已经存在的逐轮记录不可覆盖；再次测试时必须显式指定新的 attempt 目录。原始日志位于本地 `tmp/resume-authorization-attempt1.log`、`tmp/resume-authorization-attempt2.log`、`tmp/resume-backpressure-red.log`，不提交环境日志。
