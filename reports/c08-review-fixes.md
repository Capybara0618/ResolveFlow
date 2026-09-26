# C08 审查修复记录

日期：2026-09-26。起始HEAD：`f70cb34`。范围：修复审查确认的问题并整理DSH执行入口，不实现整包C08/C09/C10，不更换依赖锁，不改Java业务语义。采用测试驱动、分片修复与当前上下文入口收敛。

## 1. 基线与保留

开工已有两个`reports/c052c-chain/*.log`修改，以及20260925-232103链路报告/SQLite和两份20260926 verify报告未跟踪，全部保留，未覆盖/清理/提交它们。代码与文档起始无其他未提交修改；未发现同文件并行编辑。本轮不提交或推送，交给DSH接管时须保留完整工作树diff。

## 2. 问题、修复与边界

| 问题 | 本轮实现 | 证据/仍有边界 |
| --- | --- | --- |
| 输出预算只记账、不拦截 | BudgetGuard调用前预占最小可用输出额度，将ceiling传给ModelClient；已知usage退差额，未知/估算保守保留；超额先记账并拒绝动作 | 新旧路径均覆盖耗尽后不再调用、超额不执行工具；持久化/稳定call_id仍归C09 |
| ContextPacket之后追加SDK输入 | 新路径只发送packet消息，P0保留system且不重复；计数覆盖最终渲染文本、标签、schema、包装预留，hash与实际ModelClient输入一致 | 不再append SDK hints/工具历史；live供应商实际HTTP包装/参数/hash仍须C08适配验证 |
| 旧路径计数早于当前报文构建、SDK会修改历史Msg | 先构建并深拷贝请求，再计数和发送；复用同一快照 | 保留显式兼容路径，ContextBuilder默认启用仍是下一步，不冒充已切换 |
| 中文字符/3低估 | 改为UTF-8字节保守估算+包装预留，标ESTIMATED | 不是准确tokenizer/费用保证；旧裁剪测试容量改从完整请求计算，所有保护/裁剪断言保留 |
| 退款预留金额缺失 | P2读取core契约的reserved_refund_amount，移除不存在的refundable_amount权威映射 | 测试检查响应键与core OpenAPI一致，并贯通工具Observation→FactsView；本轮未重跑Java HTTP链路 |
| 回放断网可绕过 | 可恢复context manager，在loop初始化后拦截socket/create_connection/connect/connect_ex/sendto/DNS及asyncio连接入口 | 4种TCP入口有独立子进程localhost探针；不证明原生扩展、子进程、已有连接或OS隔离，C10门禁不勾完成 |
| 状态和交接滞后 | todo顶部为进度唯一入口，handoff-current为执行入口；旧交接加历史标记，Git左右计数更正，worker归C08.2 | 撤回AS01“全面断网/零业务写已证明”的过强表述；历史保留但不作当前指令 |

核心代码：`agent/src/resolveflow/harness/{budget,context,model,sdk_adapter,sdk_runner}.py`；核心测试：`agent/tests/integration/test_context_wiring.py`、`agent/tests/unit/test_context_{builder,trimming_demo}.py`、`test_harness_loop.py`。回放代码/测试位于`spikes/agentscope/src/resolveflow_spike/replay.py`及`tests/test_replay{,_network_boundary}.py`。

## 3. RED → GREEN 实际过程

1. 先新增预算反例：`pytest tests/integration/test_context_wiring.py -q -p no:cacheprovider` → **6 failed, 7 passed**。旧代码在预算1时执行两次、输出超额仍成功；新预占API/输出ceiling尚不存在。实现后联合loop测试 **39 passed**。
2. 新增最终输入/真实退款字段/中文计数反例：wiring+builder测试 **3 failed, 34 passed**，分别暴露额外SDK HintBlock、预留字段遗漏、中文低估。修复后，原5个小容量裁剪用例因计数更保守而失败；调整夹具容量与二分查找的mandatory overflow处理，不删除任何保护断言，相关5文件 **64 passed**。
3. 回放子进程连接探针先 **3 failed, 1 passed**：direct connect、connect_ex、asyncio可绕过，create_connection被拦。补guard生命周期和入口后，旧回放+新探针 **12 passed**。
4. 第一次agent全量 **1 failed, 918 passed, 9 skipped**：原“12次模型预算”测试先撞到正确核算后的输入上限。仅该测试扩大非目标输入预算以隔离call-count边界，保留必须恰好12次等所有原断言；生产预算默认值没有提高。
5. 增加旧路径请求核算反例后 **1 failed, 44 passed**：SDK后续原地修改Msg导致历史输入变化。深拷贝冻结后 **45 passed**，另覆盖输入上限在调用前拒绝与ESTIMATED不返还输出预占。

## 4. 最终验证（实际执行）

命令中工作目录明确如下，使用已有venv，不重新解析依赖：

| 工作目录 | 命令 | 结果 |
| --- | --- | --- |
| agent | `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=short` | **923 passed, 9 skipped, 1 warning，135.19秒** |
| agent | `.\.venv\Scripts\python.exe -m ruff check src tests` | **通过** |
| agent | `.\.venv\Scripts\python.exe -m mypy` | **失败：9处既有错误，4文件；47源码文件已检查**，无本轮修改源码错误 |
| spikes/agentscope | `.\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --tb=short` | **40 passed，15.02秒**，含恢复/回放实验 |
| spikes/agentscope | `.\.venv\Scripts\python.exe -m ruff check src/resolveflow_spike/replay.py tests/test_replay.py tests/test_replay_network_boundary.py` | **通过** |
| 仓库根 | `git -c core.whitespace=cr-at-eol diff --check -- AGENTS.md README.md agent docs tasks spikes/agentscope reports/agentscope-migration/compatibility.md` | **通过**；尊重已有CRLF，未修改用户原有log产物 |

既有strict mypy问题：provider_stub/__init__.py（3）、contracts/_schemaio.py（1）、contracts/fixtures.py（1）、contracts/core_corpus.py（4），均为no-any-return。本轮没有关闭检查或加忽略豁免。Starlette/AnyIO弃用warning为依赖提示。9个skip来自无引用文件的既有契约citation参数化检查，不是本轮新增跳过。

本轮未执行：Java全量/真实RocketMQ退款链路、项目all-offline、收费live评测、OS级strict隔离验收、生产C09故障验收。已有reports/verify结果仅供历史，不算本轮通过。全量Python测试按既有fixture创建/清理自身临时schema，未清理业务库/卷或用户数据。

## 5. 不得扩大本轮结论

- 未完成默认ContextBuilder切换、live ModelClient、完整HarnessManifest、ProposalVerifier、run worker；C08.1/C08.2仍不勾完成。
- 当前packet的manifest_id仍是政策派生标识，P0动作目录仍需完整参数描述；下一步在正式路径收口时补齐，不能称冻结manifest/真实模型全部通过。
- 不将回放guard称为OS沙箱，不将静态import扫描称为业务写隔离；无凭据、无网络与写入口反例必须在C10验收。
- 恢复预算历史“预留”与spike“12+2”存在规范冲突，C09前显式解决，不能自动继承例外或静默改用户历史决定。
- 不改变项目范围，继续C08.1a→C08剩余→C08.2闭环，再进入C09/C10。执行提示词见[tasks/handoff-current.md](../tasks/handoff-current.md)。
