# D2：版本授权与可靠退款正式结果

2026-10-26。同一自有lab c5265fe48bc946ec99398450c998a014，真实Gateway/Case/Commerce、MySQL、RocketMQ和持久HTTP模拟退款提供方；无模型/费用/真实支付。业务JAR沿用D0冻结构建，资金执行与Outbox/Inbox生产实现未改；本轮修复的是故障实验运行器。授权另见[90轮授权结果](../authorization-d2.md)。

## 结果及分母

- 授权90轮中，旧审批拒绝60、旧消费拒绝30，非法消费0；90个有效消费对照各一命令/Outbox。原93项Java检查通过，3项为继承检查，不当作93轮授权。
- 原退款计划7类各10轮，共70个原ID，实际70订单/80行（F03每轮两行）。最终全局SQL差集和只读SQLite均确认80个新operation、80份成功收据、每行一次提供方处理、每Case一次关闭，全部退款2502000分；重复退款0、超退0，最终预留0。
- 运行器原记通过68轮；独立源审确认67个完整有效故障窗口。F05-r02窗口未到达、F07-r06管理探针超时，另F04-r10断连接发生5.921秒、晚于客户端5秒超时，窗口受干扰。三者原业务资金均成功，不能据此把故障有效数改成70/70。
- 额外U00开发对照不在80行内：无提供方收据，最终仍UNKNOWN、同operation/provider_key、退款0、32900分原预留保持，未人工释放或重新支付。

[完整审计输出](summary.json)同时保留运行器计数与独立窗口计数；其中cohort兼容字段fault_rounds_passed=68表示原运行器记录，完整窗口以validated_fault_windows=67为准。恢复、故障窗口到达与资金效果分开报告。

| 场景 | 原计划 | 完整窗口 | 实际证据 |
| --- | ---: | ---: | --- |
| F01 同event重复命令 | 10 | 10 | 每轮真实MQ十次ACK对应消费记录，一次ACCEPTED/九次DUPLICATE |
| F02 不同event同operation | 10 | 10 | 每轮十个有效重签event、业务载荷相同，仍一次处理 |
| F03 同订单两行预留重叠 | 10 | 10 | 两行19900/32900分预留重叠后结算，整单52800分无超退 |
| F04 提供方成功后丢响应 | 10 | 9 | 九轮2次UNKNOWN快照保留占用、同operation GET恢复；第十轮被5秒超时干扰 |
| F05 已结算未发布时进程退出 | 10 | 9 | 九轮结果PENDING落库后真实终止/新PID，原结果恢复投递；第二轮门控未到达 |
| F06 成功结果重复投递 | 10 | 10 | 每轮原结果加九次重复，最终Inbox deliveries至少10、仅一次Case关闭 |
| F07 Broker中断后自动恢复 | 10 | 9 | 停机至少10秒、命令PENDING且未创建operation，恢复后原应用PID保持自动收敛；第六轮观测超时 |

F03两次审批是顺序HTTP，异步命令形成两行预留重叠；没有记录数据库锁等待，不把它宣称为同步屏障下的锁竞争测试。

## 中断、接续与实验偏差

原批01完成41轮后停止于F05-r02，根因为恢复后的投递配置缓存未更新；批02仅接28个未开始原ID，通过23轮后停止于F07-r06的mqadmin十秒超时。原失败operation只读核验均成功/Case关闭，无重发。修复分别efbff3e6和a94c6d22，均先关键失败回归再通过，普通push核实。细节见[原中断报告](../refund-formal-interruption.md)。

批03接四个未开始ID，但上轮会话中断后Java进程已退出，登录预检连接拒绝，在任何round目录/退款请求前停止，单独保留startup-failure和零轮summary。恢复原构建后批04只接同四个尚未开始ID，4/4通过。四批manifest逐层保留父目录全部hash；最终审计按原70计划汇合，失败ID没有被替换或重跑。探针变慢的底层原因未确认，不能统一归因外网。

另有12个非F04轮次、13个operation的提供方门控超过5秒，并实际观察到原操作GET对账；门控最长44.515秒，明细见summary.additional_reconciliation_rounds。F04-r10另单列窗口干扰。门控用于在提供方响应前采样真实预留，SQL/管理命令较慢时会引入额外HTTP超时；这些是复合故障，不可把其恢复耗时都归因MQ重连，也不代表正常接口RT。采样边界均满足refunded+reserved<=paid，最终全局审计补查所有原行及旁生operation差集；不声称连续采样或数学证明全部执行交错。

| 恢复观测 | 有效样本 | 最小/平均/最大秒 | 起点 |
| --- | ---: | --- | --- |
| F04 | 9 | 22.375 / 23.972 / 29.000 | 提供方收据重新可查询，包含原UNKNOWN退避 |
| F05 | 9 | 0.437 / 0.463 / 0.484 | 新Commerce已健康，不含完整JVM启动 |
| F07 | 9 | 4.406 / 23.758 / 32.156 | 管理探针确认Broker就绪，受提供方门控/查询退避干扰 |

上述耗时用于诊断，不作为简历性能指标。不能拿这个个人单机模拟实验宣称商业支付、高可用或通用故障全覆盖。

## 可复算证据与验证

[911文件原字节归档](evidence.tar.xz)、[逐文件hash与包hash](archive-index.json)，包含四批原manifest/执行源码、70轮原实体/金额/消息/失败/结果/提供方轨迹及全局只读账本。归档逐文件重新读回比对；原目录/数据库/原进程日志保留本机，包内不含数据库快照、令牌或原始敏感日志。

[cohort.py](cohort.py)校验原计划、父批hash、执行源码、已完成/失败不替换；[collect_database.py](collect_database.py)只SELECT及SQLite mode=ro，按原全局inventory差集核对80行并复查U00；[audit.py](audit.py)离线核验真实签名/ACK消费映射、金额/版本/行槽/Case与提供方一致性。四种仅内存篡改（重复请求、超退、错误授权revision、重复关闭）均被审计拒绝，[反例检查](audit-checks.json)，原文件无修改。

实际命令（仓库根目录）：

```powershell
# freeze/execute依次使用refund-formal-01、02、03、04；后三级显式--continue-from前级。
agent/.venv/Scripts/python.exe reports/backend-resume-v1/refund-formal-01/collect_database.py reports/backend-resume-v1/c5265fe48bc946ec99398450c998a014/refund-matrices
agent/.venv/Scripts/python.exe reports/backend-resume-v1/refund-formal-01/audit.py reports/backend-resume-v1/c5265fe48bc946ec99398450c998a014/refund-matrices reports/backend-resume-v1/refund-formal-01/summary.json
agent/.venv/Scripts/python.exe reports/backend-resume-v1/refund-formal-01/verify_audit.py reports/backend-resume-v1/c5265fe48bc946ec99398450c998a014/refund-matrices reports/backend-resume-v1/refund-formal-01/audit-checks.json
agent/.venv/Scripts/python.exe reports/backend-resume-v1/refund-formal-01/archive.py reports/backend-resume-v1/c5265fe48bc946ec99398450c998a014/refund-matrices reports/backend-resume-v1/refund-formal-01
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_backend_refund_matrix.py agent/tests/unit/test_backend_refund_provider_faults.py agent/tests/unit/test_backend_refund_inspect.py -q
```

最后pytest10通过（3.15秒），报告/运行器/回归Ruff通过，四项审计反例通过；探针新回归修复前1失败/5通过，修复后六通过。本轮没有生产Java变更，未重复93项Java或全项目回归。曾误写provider测试文件名导致pytest零项/路径错误，随后按实际路径重跑十通过；Ruff一次导入顺序失败已修复。首次文档写入CRLF使diff-check失败，提交前已恢复LF，未修改原字节归档。

范围保持三Java与既有MQ，不新增支付/服务/模型。Agent/RAG/Harness简历冻结三条、个人PDF及原四历史脏文件未动。技术点5可引用“80笔模拟退款，重复退款与超额退款均0笔”，面试展开7类场景、67个完整窗口及原失败边界，不写70/70。D3订单列表SQL与D4 Redisson性能不属于本结果。

本轮已执行自有stop并核对[停机记录](stopped.json)：十个端口（含VIP）全部关闭，所有自有容器停止且OOM=false；Broker/namesrv在宽限后exit137，其他exit0，容器/数据卷与U00占用保留。压缩包解出到新tmp目录后，[911文件hash及完整离线审计再次一致](archive-roundtrip.json)，不依赖运行中的服务。

最后四轮实际在同一解释器、同一operation_lock内依次调用现有start_java_services(settings, settings.load())及execute(settings, refund-formal-04目录)，避免沿用失效Java PID。没有手工重新发送退款命令，未修改生产调度器或历史失败轮。整理收尾文档时一次未显式UTF-8读取被Windows默认GBK拒绝，在写入前停止，补编码后完成。
