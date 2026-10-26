# 后端简历主线：D0隔离运行与基线

2026-10-26，按[开发v1.1](../../docs/backend-resume-development-v1.md)与[评测v1.1](../../docs/backend-resume-evaluation-v1.md)完成第一步准备。当前任务进度只在tasks/todo.md顶部，本报告记录实际实现和证据。

后续独立证据：[逐请求记录接线](request-journal.md)、[完整运行器接线](matrix-wiring.md)、[正式交易160轮与源审](trade-formal.md)。后续结果不回写或替换本报告的D0基础成绩。

## 本步交付

- `scripts/backend_resume_lab.py`：显式run-id的prepare/resume/check/exercise/verify/stop，不回落到原演示库。
- `scripts/evaluation/backend_lab.py`：32位运行标识、容器label、固定独立端口、MQ VIP端口冲突检查、操作进程互斥、不可覆盖的冻结JAR、进程标识和容器归属检查。
- `scripts/evaluation/backend_provider.py`：仅提供既有退款provider的loopback HTTP适配，SQLite持久化，无模型/Agent worker。
- `scripts/evaluation/backend_smoke.py`：实际经Gateway购物、付款、模拟发货、受控LOST物流、创建工单、人工方案审批、自动双向MQ退款以及最终只读核对；原key/订单/操作保存在本批状态，中断续接不重新造交易。

运行ID为`c5265fe48bc946ec99398450c998a014`。独立Compose包含MySQL8.4、Redis7.4、RocketMQ5.3.3 namesrv/broker及一次性broker卷归属初始化。Case/Commerce使用各自账号，真实跨库读取均被拒绝。沿用标准签名主题rf.case.core.v2/rf.commerce.core.v2及broker名映射，隔离来自本批独立Broker与run专属consumer/producer group，不私改协议主题绕过CoreTopicNames。

三个JAR构建后复制到忽略的`tmp/backend-resume-v1/<run_id>/baseline/`，后续resume只校验并运行这些副本；政策fixture另外冻结hash并用现有一次性Java导入命令导入。优化前生产构建来自60f7766时点，未修改业务源码。首个baseline.json同时保留当时早期实验工具hash；[smoke.json](c5265fe48bc946ec99398450c998a014/smoke.json)另列最终实际工具hash，不能把早期工具hash当作修复后执行器版本。

## 实际结果

[setup-checks.json](c5265fe48bc946ec99398450c998a014/setup-checks.json)中8项通过，覆盖Gateway/Case/Commerce/provider、MySQL/Redis及两个服务账号的跨库拒绝。MQ实际可用由创建主题、真实命令Inbox和结果投影共同验证，非仅TCP就绪。

[smoke.json](c5265fe48bc946ec99398450c998a014/smoke.json)15项通过：实付32900分、模拟退款32900分、最终预留0、行CONSUMED、操作SUCCEEDED、Case CLOSED_SUCCESS；同一行退款操作1条、provider成功记录1条/实际处理尝试1次、关闭事件1次。Case命令和Commerce结果均自动投递至PUBLISHED，对应两个Inbox及结果projected_at已核对。

人工方案中的证据是明确合成fixture（observation ID/证据hash由运行器准备），政策引用来自实际导入原文的canonical hash；不把本次称为模型调查或真实承运商验收。购物/付款/发货/API审批、MQ、账本和provider是实际服务执行，物流用既有受控存储过程。

已实际完成stop→resume→check→exercise：同一组订单、工单、退款操作和收据不变，再次读取通过，未产生第二笔模拟退款。环境/镜像ID、端口、政策hash、Compose和HTTP轨迹hash见[environment.json](c5265fe48bc946ec99398450c998a014/environment.json)。本步是基础冒烟，非160轮交易/70轮退款或性能正式矩阵。

## 测试、失败与修正

- 新模块最初11项检查因模块缺失收集失败；实现隔离工具后11通过。提供方新增检查先缺模块失败，首次使用错误的测试方法名attempt_count，改为实际接口attempts后通过；另加命令互斥检查，最终本文件13项。
- `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_backend_resume_lab.py agent/tests/unit/test_provider_stub.py agent/tests/unit/test_provider_stub_http.py -q`：38通过、1个既有Starlette/AnyIO弃用警告，4.52秒。
- `agent/.venv/Scripts/ruff.exe check scripts/backend_resume_lab.py scripts/evaluation/backend_lab.py scripts/evaluation/backend_provider.py scripts/evaluation/backend_smoke.py agent/tests/unit/test_backend_resume_lab.py`通过。最初测试HTTP helper触发S310，改用仅绑定loopback的HTTPConnection，未关闭检查。
- Java21，java目录`./mvnw.cmd -B -pl gateway,case-service,commerce-service -am package '-Dmaven.test.skip=true'`构建通过，20.136秒。首条未引用Maven点号参数在PowerShell被拆成错误phase，引用后成功；本步构建未运行Java测试，不计为业务回归通过。
- Broker最初启动失败：新命名数据卷为root归属，日志明确`store/lock Permission denied`，追加独立root初始化容器只修本批broker-store卷归属，Broker仍以镜像原用户运行。原卷/共享容器不动。原prepare等待进程停止后再恢复，后续加入OS文件锁拒绝同run第二命令。
- 首次建Case422：全新库尚无政策，沿现有受控import-dir命令导入冻结合成政策后，复用原订单/key继续，未放宽政策检查。
- 资金链已完成后，首个verify误断言Commerce Inbox为APPLIED；实际枚举和持久记录为ACCEPTED。核对RefundCommandConsumer后修正精确期望，保留最终资金/Inbox/事件断言，未改业务消费者或重做退款。

## 运行入口

以下为本步已实际执行的命令。已存在的运行使用resume；prepare只用于新的32位小写hex运行ID，不能覆盖旧状态。

```powershell
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py prepare --run-id c5265fe48bc946ec99398450c998a014
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py check --run-id c5265fe48bc946ec99398450c998a014
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py exercise --run-id c5265fe48bc946ec99398450c998a014
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py verify --run-id c5265fe48bc946ec99398450c998a014
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py stop --run-id c5265fe48bc946ec99398450c998a014
agent/.venv/Scripts/python.exe scripts/backend_resume_lab.py resume --run-id c5265fe48bc946ec99398450c998a014
```

状态、幂等键、原HTTP轨迹、进程日志、JAR和provider SQLite留忽略tmp；提交脱敏摘要/hash，不提交密钥、数据库快照或原始敏感日志。stop只终止带本run标识的PID及label匹配的容器，保留数据和Broker卷。Agent侧冻结/PDF与四历史脏文件保持。本批0模型请求/费用，无原业务数据库或服务修改。

后续按D1补交易竞争与恢复反例，再D2/D3/D4；Redisson尚未引入，正式评测尚未开始。

## 本轮收尾

D1基础预检后已停止本run所有Java/provider及Compose资源，[stopped.json](c5265fe48bc946ec99398450c998a014/stopped.json)记录10个端口（含Broker VIP）全部关闭；MySQL/Redis/初始化容器exit0，Broker/namesrv在停止宽限后exit137、OOM均false，容器与数据卷保留。此前stop→resume实际完成并核对同一消息/操作/资金；不把镜像启动包装器的强制停止写成全部优雅退出。[D1预检](trade-preflight.md)单独记录，未覆盖D0结果。


## D2正式证据入口（2026-10-26）

[当前版本授权90轮](authorization-d2.md)、[可靠退款正式审计](refund-formal-01/README.md)：70原计划/67个完整故障窗口，70订单80退款行各一次成功、重复/超退0；两次运行器中断和一次窗口干扰保留，不作70/70主张。911文件归档完整解压复算一致，自有环境已停并保留数据。当前任务位置仍只看todo顶部。


## D4功能证据入口（2026-10-26）

[D4工作台/Redis/Redisson功能报告](d4-functional-01/README.md)：实际双Commerce与双Case、16个开发条件场景、三次真实Lua窗口、2万工单7条件查询计划，58独立Java及3离线反例通过。211文件原字节归档、全部临时资源收尾。锁开启时等待者可能503，收益与拒绝率分开报告；正式R120及HTTP p95仍由D5单独冻结执行，当前没有第7条性能成绩。
