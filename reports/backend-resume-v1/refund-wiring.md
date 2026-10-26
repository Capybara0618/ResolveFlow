# D2.2：七类退款故障接线与只读诊断

2026-10-26。授权结果`daf57500`及原字节属性修正`50257a43`已普通push核实。沿用D0独立环境/冻结JAR、真实Gateway/Case/Commerce/MySQL/RocketMQ与持久SQLite模拟退款，人工资格/方案明确合成；0真实模型/费用。未修改生产业务或迁移，依赖锁保持。

## 实际证据

七类故障各已有一轮通过；另有两轮自动链路冒烟、一轮无收据UNKNOWN对照，共10个通过开发场景。第一次F04在实际已成功后被运行器错误断言判失败，原失败保留；修正后用明确新业务组验证，没有重发原operation，不能把原失败删除后称首轮全通过。

| 场景 | 故障实际操作及核对 |
| --- | --- |
| F01 | 同一个真实签名命令并发投递10次，10个broker ACK和10条消费msg_id对应，1 ACCEPTED/9 DUPLICATE；一资金操作/提供方成功/工单关闭 |
| F02 | 只更换event_id并用原实验fixture密钥重签10份，其余payload完全相同；10份实际消费，仍1 ACCEPTED/9业务DUPLICATE，而非仅event_id去重 |
| F03 | 实际购买同单两SKU，32900/19900分；两个操作同时持有预留后放行provider，最终共52800，行状态与账本一致 |
| F04 | 提供方持久成功后真实断开socket，查询隐藏10秒；UNKNOWN时原32900预留未释放，隐藏窗口后再次核对仍保持，随后原operation查询结算 |
| F05 | 暂停自有Commerce结果Outbox投递，确认结算成功且原结果PENDING，真实终止进程；重启后发布原结果，provider只成功处理一次 |
| F06 | 原成功结果自动投递后重复投9次，Case inbox收到至少10次；关闭事件、退款和金额不增加 |
| F07 | 自有Broker先停，真实审批消费/命令产生；停机10.859秒后仍PENDING且无资金操作，恢复后应用PID保持，自动命令/结果投递闭环完成，未人工重投 |
| U00 | 提供方没有收据，返回UNKNOWN；10秒后仍同operation/原32900占用，GET NOT_FOUND不被当失败释放；不算应收敛成功组 |

正常路径由自动Outbox投递。F01/F02显式暂停Case命令投递，实验发送器只针对真实Outbox原文控制重复次数；F05只暂停自己结果投递，其他步骤自动。发送器的地址/run/group显式传入，依赖从冻结JAR提取，未引入新MQ或收费服务。消费DEBUG仅记录消息ID/处置，用于对应实际ACK，不提交原进程日志。

完整证据见[原字节压缩包](refund-wiring-v1/evidence.tar.xz)、[逐文件hash](refund-wiring-v1/archive-index.json)、[三次执行汇总](refund-wiring-v1/summary.json)，共170文件，归档后逐字节核验。原目录和SQLite留本机，包内只有必要结构化记录/源码，无数据库/密钥/令牌。第一目录4通过/计划9后停止于F04；第二目录只执行明确剩余/修正的F04/F05/F06/F07/U00，5/5通过；第三目录只在最终实验隔离配置下新冒烟1/1。不能把这些开发次数并入正式70轮。

## 暴露的问题与边界

第一次F04的错误是强制要求Java在10秒隐藏期内GET，而源码固定未知结果退避30秒。实际原UNKNOWN/占用、收据、30秒后GET及关闭都已保存；只读原operation核对最终一次成功，不改原FAILED或重发。修正为记录隐藏期结束仍UNKNOWN/原占用，随后原GET返回成功；provider的隐藏期404由实际HTTP单测单列证明，不虚构Java在隐藏期的查询。

原lab启动器中`agent.dispatch-enabled=false`及`support.dispatch-enabled=false`不是实际开关。源码确认退款消费与Agent run派发共用dispatch.enabled，support使用support-agent.enabled。原日志只有Agent连接拒绝，无Agent进程/接受调用/模型；本步将Agent地址固定为自有provider（非退款POST返回404，无模型能力），support实际开关关闭。最终新冒烟通过，不为后端实验修改冻结Agent实现。

[只读诊断CLI](../../scripts/evaluation/backend_refund_inspect.py)按operation_id读取授权revision/版本、case、命令/结果Outbox与重试、原命令Inbox/结果投递数、预留账本、provider收据/尝试。实际已检查F04 SUCCEEDED和U00 UNKNOWN/32900占用/无收据，结果在包内；F02重签event_id不在原命令Outbox，诊断明确该关联边界，可结合实验消费记录。只有SELECT及SQLite mode=ro，无外部资金调用、管理写入口或新服务。

新增provider两检查、资金计分三检查、诊断两检查均先失败后通过；与本步授权/原相关Python共48通过/1既有弃用警告，Ruff通过。实际Java单文件MQ发送器已在真实broker执行，未重跑Java全回归。终态观测耗时只作接线材料，不能将早期包含核对开销的时间混入正式恢复分布。

```powershell
agent/.venv/Scripts/python.exe scripts/evaluation/backend_refund_matrix.py freeze --run-id c5265fe48bc946ec99398450c998a014 --experiment-id refund-wiring-01
agent/.venv/Scripts/python.exe scripts/evaluation/backend_refund_matrix.py execute --run-id c5265fe48bc946ec99398450c998a014 --experiment-id refund-wiring-01
agent/.venv/Scripts/python.exe scripts/evaluation/backend_refund_matrix.py freeze --run-id c5265fe48bc946ec99398450c998a014 --experiment-id refund-wiring-02 --scenarios F04,F05,F06,F07,U00
agent/.venv/Scripts/python.exe scripts/evaluation/backend_refund_matrix.py execute --run-id c5265fe48bc946ec99398450c998a014 --experiment-id refund-wiring-02
agent/.venv/Scripts/python.exe scripts/evaluation/backend_refund_matrix.py freeze --run-id c5265fe48bc946ec99398450c998a014 --experiment-id refund-wiring-03 --scenarios S00
agent/.venv/Scripts/python.exe scripts/evaluation/backend_refund_matrix.py execute --run-id c5265fe48bc946ec99398450c998a014 --experiment-id refund-wiring-03
agent/.venv/Scripts/python.exe scripts/evaluation/backend_refund_inspect.py --run-id c5265fe48bc946ec99398450c998a014 --operation-id <本批已记录的operation UUID>
```

本步精确提交普通push核实后，冻结最终源码/JAR及新formal目录，执行F01–F07各10轮=70一次；计划80行，按实际结果核对，不先填成功。未知或失败轮保留并停止自动重发，D2正式结果尚未产生；D3/D4仍待后续。
