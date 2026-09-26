# C09生产恢复实施与验收（2026-09-26）

## 请求冻结小步

迁移008追加实际provider请求体、重建用历史spend、SDK状态及manifest字段；工具结果表供下一小步接入。`reserve` 将请求hash/输出ceiling校验与预占同事务提交，失败不扣预算；LiveModelClient提供发送前精确body接口，不包含鉴权header。测试先因错误导入未收集，修正后RED 2 failed（缺request_body参数），实现后请求/attempt/结果/live-client聚焦 **32 passed**。命令：agent目录 `./.venv/Scripts/python.exe -m pytest tests/integration/test_recovery_request.py tests/integration/test_recovery_model_attempt.py tests/integration/test_recovery_model_result.py tests/unit/test_live_model_client.py -q -p no:cacheprovider --tb=short`。尚未接SDK/worker，C09不勾；本小步不重跑全量/Java/live，C09最终验收重跑全量。

## 租约与session锁小步

RunLease保留独立pool checkout承载session advisory lock，领取与fence递增/STARTED同事务；网络期间只保留session锁，不持行事务。另一pool连接心跳续租，退出释放锁和心跳；同run锁仍被持有时即使lease过期也不夺取。恢复保持原active_deadline，STARTED不重复。RED缺模块→lease+worker **22 passed**（真实PG）；新增Ruff/strict mypy通过。生产worker接入/终局fence下一步完成，本步不勾C09，未跑全量/Java/live。

## 领域journal小步

迁移009记录模型结算后spend和工具调用前后spend，工具结果/manifest绑定同事务校验run fence。重复已保存工具不重复计预算；未知工具保留占用并最多两次额外attempt。journal及已有预占/结果回归通过，具体命令 `pytest tests/integration/test_run_journal.py tests/integration/test_recovery_model_result.py tests/integration/test_recovery_budget_store.py -q -p no:cacheprovider --tb=short`；此处不代表SDK生产接入。SDK重建接线正在下一小步实施，未提交部分保留，不夹入本小步提交。

## 同SDK重建小步

现有AgentScopeRunner接入DurableRun；按稳定逻辑call_id重建已保存模型/工具回复、历史上下文和SDK控制状态，实际预算保留原PG账。每次发送前冻结精确请求，重建不一致拒绝；首个恢复新推理使用总12次内的恢复分区。SDK状态可校验但不声称直接load后续跑：本步使用规范允许的领域记录重建路径。三个故障窗口真实PG各5次通过，UNKNOWN原attempt不退且最多一次重试；已保存工具外部读取总计一次。相关SDK循环/检索76 passed；全量Ruff通过，新代码strict mypy通过。生产worker接入、跨进程和H4最终门禁仍待后续小步。

## 生产worker接线小步

HTTP服务显式启用常驻worker时默认走RunLease与DurableRun；旧注入测试仍可用兼容worker。终局UPDATE与outbox同事务检查fence/owner/有效lease/取消。旧RUNNING缺fence明确MIGRATION_REQUIRED；过期活动deadline直接FAILED且不调用模型。快照格式版本升到2。RED4 failed→租约/worker26 passed；factory/resident/manifest/SDK44 passed；Ruff通过，四个源码strict mypy通过。合并测试暴露SDK旧MCP异常handler在工具故障注入抛异常时遮蔽原错误，工具保存后的注入移至下一模型调用前（工具已保存、尚未推进新调用），重新15窗口全部通过。修正上个提交文档写入引入CRLF的格式噪声，未改历史记录。未运行全量/跨进程/Java/live，最终门禁继续。

## 跨进程CF6/H4与边界修复

`pytest tests/integration/test_sdk_durable_recovery.py tests/integration/test_recoverable_worker.py tests/integration/test_run_worker.py tests/integration/test_c09_acceptance.py -q -p no:cacheprovider --tb=short` → **62 passed / 79.32s**。CF6三个窗口各5次（15个真实PG双进程运行），首进程`os._exit(73)`、新进程实际重领fence2、重建同SDK：成功15/15、未决0、旧UNKNOWN成本保留、稳定model-0/model-1、仅一份终局。另同进程三个窗口各5次。每次原deadline不变、model累计2或3、工具实际读取一次。取消/新revision/旧fence在返回后保存前注入，旧响应不落SAVED、不发终局；预算manifest不一致无新增模型调用。

增加行锁等待消耗lease的反例，RED1 failed（租约已过期仍PROPOSAL）→先锁row再读取DB时间修复。物流分页重建RED1 failed（trace_pages=0）→从保存的Observation恢复计数，新MCP无外部调用。live客户端HTTP桩503反例RED2 failed→worker留RUNNING可接管、最多原请求一次重试，二次UNKNOWN后MODEL_RETRY_EXHAUSTED，真实计费数据保守保留；不是收费live评测。合并测试第一次有一个子进程恰好在编辑源码期间启动而ImportError，停止并行编辑后完整62项通过。Ruff全量通过，本步三个源码strict mypy通过。

真实Java/PG/MCP/MQ/mock退款闭环 `python scripts/e2e_resident_refund.py`，运行20260926-230859，**PASSED / 38.9s**；Case/run/line分别7799b0e7-c09e-40d6-9a2c-ee1fbb9af925/a264709d-cbb6-52cb-a961-d6691ed1c9b7/9230907；2599分退款、预留0、provider一次attempt、STARTED/PROPOSAL两条ACCEPTED。原始日志和provider SQLite保留忽略目录tmp/c08-resident-refund/20260926-230859，不提交敏感原始日志。不是自主live或生产可靠性保证。最终全量仍下一步运行。

## 最终版本与deadline核验

未设置构建戳时code_revision改为源码(.py/.sql)与uv.lock内容指纹；wheel无lock时使用实际安装依赖列表hash，部署可显式使用构建戳。RED缺模块→指纹变化测试通过，预算/state/code/model四类manifest变更全部拒绝且模型不新增调用。政策检索/本地Observation恢复各一项，缓存命中时禁止查询方法，local_reads/tool_attempts原计数保留；测试首次patch错局部导入路径失败，修正后通过。模型timeout反例RED1 failed（剩5秒仍传30）→发送前读PG时间，模型/MCP timeout取原配置、冻结预算timeout和原deadline剩余的最小值，发送后恢复client配置。聚焦37 passed（不含15个跨进程case，将随全量重跑），Ruff全量通过，五个相关源码strict mypy通过。

## 工具入口迟到fence拒绝

在已保存模型回复后、进入工具预占之前注入fence递增，RED1 failed复现AgentScope 2.0.8/MCP 2.2旧handler把StaleFenceError遮蔽成AttributeError。MCP/本地桥捕获领域拒绝并停止gate，SDK外传回原异常由worker处理，拒绝不触发外部工具且不写终局。模型保存前、后及工具入口三处均有迟到反例。聚焦60 passed（排除跨进程15项），补充调整后入口反例1 passed；全量Ruff通过。
