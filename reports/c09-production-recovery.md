# C09生产恢复实施与验收（2026-09-26）

**完成验收（2026-09-26 23:33 +08:00）**：C09.1/C09.2及H4/CF6恢复门禁通过；生产代码`070e68c`已推送并确认origin/main。最终全量 **1138 passed / 9 skipped / 1 warning**，Ruff通过；新增/相关9源码strict mypy通过，全量仍既有4文件9错。原始测试证据见[JUnit](c09-production-recovery.junit.xml)。实际SDK+真实PG恢复验收，模型为mock/HTTP桩，收费live与C10不在本次通过结论中。


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

## 最后迁移竞争与全量基线

源码ac28ee4全量 `pytest tests -q -p no:cacheprovider --tb=short` → **1137 passed / 9 skipped / 1 warning / 245.99s**。strict mypy 59源码仍4个既有文件9个no-any-return，新增代码未引入错误；Ruff抓到一次B904，补`raise ... from None`后重查通过。最后旧C08领取者不带fence、C09接管已增fence的反例RED1 failed（旧PROPOSAL仍能入outbox）→兼容终局分支仅允许数据库fence也为NULL，聚焦37 passed，Ruff通过。最终再跑包含此反例的全量并保存JUnit，不把前述全量当最后修复后结果。

最新真实闭环20260926-232409 **PASSED / 57.3s**，Case acc36759-2b64-4541-9ad5-13379a9cc71d/run f5f25010-7ab6-5851-a1a4-2c557049c15b/line9232418；仍2599分、provider一次、预留0、两条ACCEPTED。之前运行PG读回确认fence1、state_schema_version2、model-0/1/2 SAVED、10+2持久分区普通3/恢复0。模型是显式mock，token零usage不冒充收费成本结果。

## 恢复快照与运行入口

本次使用迁移规格§4允许的**同SDK领域记录重建**，没有第二个循环。持久快照映射：

| 领域内容 | PG记录/行为 |
| --- | --- |
| run/case/revision、原deadline、owner/fence | agent_run；RunLease领取、独立连接心跳、session advisory lock |
| manifest/state/code/lock/模型/预算 | agent_run_model_budget.manifest及冻结budget；格式2，重建完整比较 |
| 逻辑step、下一阶段/已应用结果游标 | model-N/tool-N的有序稳定记录和UNKNOWN/SAVED标记；SDK重放前缀恢复应用游标，不新增可漂移的第二份进度 |
| SDK状态、待调用精确请求 | 每次模型预占保存sdk_state/request_body/request_hash/replay_spend，同事务fence验证 |
| 回复、attempt、usage、预占 | agent_model_call/agent_model_attempt；结果与settled_spend恰一次结算 |
| Observation、上下文引用、工具计数 | agent_tool_call的结果及before/after_spend；同SDK重新应用事实/历史/权限/repair控制，已保存读不查询 |
| 最终方案/状态/回调 | RunWorker.finish先锁run行后校验当前DB时间/fence/owner/状态/取消，状态和callback_outbox同事务 |

运行入口仍是显式 `RESOLVEFLOW_INVESTIGATION_ENABLED=1` 与已命名mock/live配置，API默认不开调查；启用后即使用本次租约恢复。lease30秒、每10秒心跳，同run保留PG session advisory lock而不持网络长事务；异常退出后等原lease失效接管。503等已知模型outage留RUNNING/UNKNOWN并保持常驻线程活着；重新接管最多重发一次同请求，二次UNKNOWN后明确FAILED。过期原活动deadline不延长，未支持的历史RUNNING明确MIGRATION_REQUIRED。升级前需停止旧客户端/旧worker，当前工作区DSH已确认停止；不宣称混跑旧C08二进制也能被新源码改写保护。

H4证据只覆盖真实PG、实际AgentScope 2.0.8、mock及HTTP桩故障。真实业务闭环有MCP/Java/MQ，但未使用收费模型；不据此验收H1/H2/H3/H5或生产高可用。C10 strict、live实验和Java单测/Spotless/all-offline包装入口本次未运行。

## 最终验收与原始证据

最终代码070e68c，agent目录实际执行：

- `./.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --tb=short --junitxml=../reports/c09-production-recovery.junit.xml` → **1138 passed / 9 skipped / 1 warning / 232.96s**。JUnit 1147 cases，failure/error均0，9项skip统一为`no citation in this file`，不是PG缺失。
- `./.venv/Scripts/ruff.exe check src tests`（最后也从根目录检查agent/src agent/tests）→通过。
- `./.venv/Scripts/mypy.exe src/resolveflow/runtime/worker.py src/resolveflow/runtime/durable.py src/resolveflow/runtime/journal.py src/resolveflow/runtime/build_identity.py src/resolveflow/runtime/leases.py src/resolveflow/runtime/factory.py src/resolveflow/harness/sdk_runner.py src/resolveflow/harness/local_reads.py src/resolveflow/harness/manifest.py --follow-imports=silent` →9源码通过。
- `./.venv/Scripts/mypy.exe src --strict` →既有4文件9个no-any-return；provider_stub 211/386/391，contracts/_schemaio121、fixtures51、core_corpus94/209/210/245。未修与C09无关的基线。

CF6最终JUnit每项时间包括两个进程启动、故障注入与恢复全程，**不是单独恢复延迟**；统计入口为解析该XML中`test_cf6_fresh_process_reclaims_and_finishes`的time字段：

| 故障窗口 | 成功/次数 | 未决 | case时间最小/中位/最大（秒） |
| --- | --- | --- | --- |
| 模型响应返回但未保存 | 5/5 | 0 | 4.522 / 4.627 / 4.905 |
| 模型回复已保存但SDK尚未推进 | 5/5 | 0 | 4.545 / 4.725 / 4.884 |
| 工具回复已保存、下一模型调用前 | 5/5 | 0 | 4.588 / 4.690 / 4.720 |

H4分别覆盖旧fence、取消、新revision、manifest budget/state/code/model不兼容、未支持历史run、原deadline不延长与租约等待过期；一律零非法终局/读取，缺fence旧领取也不能覆盖新fence。UNKNOWN仍可能重复计费，保留原attempt占用，逻辑call_id不换；不承诺零重复付费或生产高可用。

未运行：Java单测/Spotless、all-offline包装入口、收费live及H1/H2/H3/H5、C10 strict。原始Java日志/provider SQLite与既有数据库快照保留不提交；本次自启Java/Agent子进程及测试/心跳均已退出，既有PG/MySQL/RocketMQ四容器继续运行。Git推送期间曾有schannel短暂握手失败，有限普通重试后逐小步ls-remote确认，未force push/关TLS/改remote。
