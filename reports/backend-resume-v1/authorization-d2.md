# D2.1：当前版本授权矩阵

2026-10-26。按开发/评测v1.1重测现有矩阵，不沿用历史90次拒绝数字。源码、8种失效动作及消费先提交的反向场景先冻结在[manifest](authorization-d2-01/manifest.json)，通过[执行器](../../scripts/evaluation/backend_authorization.py)启动新Testcontainers MySQL8.4和真实Case HTTP；消费使用生产AuthorizationConsumptionService事务，Commerce资格来源为原显式fixture stub，不涉及MQ投递或真实退款执行。

实际[90条记录与审计](authorization-d2-01/summary.json)：V1–V8各10轮共80轮，消费先提交另10轮。逐次动作得到**旧授权审批拒绝60、旧授权消费拒绝30，合计90次拒绝；旧授权非法消费0、命令及退款Outbox均0**。10次旧callback均STALE另列，不重复算授权拒绝。80个有效对照加10个消费先提交场景，共90次有效消费，各恰一命令及退款Outbox；消费先提交后10次材料修改、10次撤销全部409，input_revision保持。

| 编号 | 实际动作/顺序 | 拒绝行为 |
| --- | --- | --- |
| V1 | 待审建议后追加客户材料 | 旧审批 |
| V2 | 客户陈述核验CONFIRMED/REFUTED各5轮 | 旧审批 |
| V3 | 已审批后追加客户材料 | 旧授权消费 |
| V4 | 两线程屏障保证新材料先提交，再审批 | 旧审批 |
| V5 | 两线程屏障保证新材料先提交，再消费 | 旧授权消费 |
| V6 | 两线程屏障保证撤销先提交，再消费 | 旧授权消费 |
| V7 | 输入更新后收到旧callback，再审批 | callback STALE及旧审批 |
| V8 | 连续两次输入更新、分别尝试旧授权 | 每轮两次旧审批 |
| consume-wins | 消费先提交，随后尝试更新及撤销 | 两个HTTP409，原revision/命令/Outbox保持 |

“两线程屏障”验证规定提交顺序，不声称所有授权操作同时抢锁。数据库在测试间清理的是Testcontainers新建临时case_db，原业务库及D0/D1数据库未连接。JVM退出后Testcontainers容器已消失；Docker只读列表为空，0模型/费用。

[增强测试](../../java/case-service/src/test/java/com/resolveflow/caseservice/casefile/ResumeAuthorizationMatrixApiTest.java)记录真实拒绝动作/跳过原因及case、authorization、revision、operation、event关联，增加退款Outbox与消费后撤销断言。Surefire **93通过/0失败/0跳过**，其中90为本矩阵，3为继承的原输入变更测试，分开记数；[脱敏JUnit](authorization-d2-01/junit-sanitized.json)及原XML hash保留。新增3个离线计分检查先缺模块失败后通过，相关Python含provider基础共43通过/1旧弃用警告；两项provider故障属于后续准备，另提交，不当作本授权结果。Java格式检查通过；生产源码/迁移/JAR不改。

执行命令：

```powershell
# java/目录，JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1
./mvnw.cmd -B -pl case-service -am spotless:apply '-DspotlessFiles=.*ResumeAuthorizationMatrixApiTest.java'
# 仓库根目录
agent/.venv/Scripts/python.exe scripts/evaluation/backend_authorization.py freeze --experiment-id authorization-d2-01
agent/.venv/Scripts/python.exe scripts/evaluation/backend_authorization.py execute --experiment-id authorization-d2-01
agent/.venv/Scripts/python.exe scripts/evaluation/backend_authorization.py analyze --experiment-id authorization-d2-01
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_backend_authorization_audit.py -q
agent/.venv/Scripts/ruff.exe check scripts/evaluation/backend_authorization.py agent/tests/unit/test_backend_authorization_audit.py
```

首次Python检查误在java目录使用根目录相对路径导致命令未找到，回到根目录执行3通过；没有因此重跑Java矩阵。编译保留既有弃用/ByteBuddy动态代理警告。原90条/manifest只写一次，禁止覆盖；分析如需复算应使用新输出。后续F01–F07的70轮真实退款故障尚未执行，第5条简历金额/故障指标仍待该批，而非从本授权矩阵推导。
