# 操作摘要事实来源约束修复

2026-10-24，基线7ef3833，按用户授权修复摘要将推断写成已核实事实的问题。[设计合同](../../docs/customer-agent-summary-grounding-v1.md)，原反例及3/4成绩[保持](../customer-agent-goal-confirm-v1/README.md)。

## 根因与变化

正文事实有程序装配，root级handoff_reason/refund_reason却是任意字符串，只检查非空和目标用途，没有对应的事实装配。修复采用同一职责分工：模型选择客户原话，程序验证来源并附本事项已读ORDER/SHIPMENT事实及O编号。仅读GUIDE时不生成已付款事实，也不为准备人工摘要强迫多读工具。外部摘要仍是原字符串、客户可编辑并确认，Java业务合同不改。

## 实际验证

| 范围 | 命令与结果 | 证据 |
| --- | --- | --- |
| 失败先行 | `pytest agent/tests/unit/test_support_summary_grounding.py -q --tb=short`；7失败/1通过，原自由摘要被旧实现直接接受 | [red.txt](red.txt) |
| 针对回归 | 新摘要8项及编排/解释/目标核对共49通过；随后增加4项换行/错误来源检查，纳入最终扩大回归 | [targeted.txt](targeted.txt) |
| 最终单元/契约 | 全部`agent/tests/unit/test_support*.py`与`test_contracts_support.py`、`test_contracts_support_refund.py`；464通过、0跳过 | [unit.txt](unit.txt) |
| 真PG/API/流式/恢复 | `test_support_summary_grounding_runtime.py`、`test_support_goal_review_runtime.py`、`test_support_orchestrated_runtime.py`、`test_support_staged_api.py`、`test_support_stream_runtime.py`、`test_support_store.py`；20通过、0跳过 | [runtime.txt](runtime.txt) |
| 静态 | 四生产源码strict mypy通过，四源码/七测试Ruff通过；首次新增行过长及复用局部变量类型问题已修正 | [static.txt](static.txt) |

原Q01错误计划后输出的自由摘要保持原样，拒绝发布后脚本给出quote对象，3模型/1指南读取成功，无订单读取、无支付状态扩写。真实PG保留原错误模型响应和正确结构，4journal；过期租约恢复结果一致，0新模型/工具发送，原理解事件不重复。mode=live仅用于走严格发布路径，模型本身为TokenizedScript，不能当作真实供应商调用。

[离线前后示例](q01-offline-example.json)绑定原Q01文件hash，保留原自由摘要、脚本修正对象、最终摘要及来源读取次数；这是有适配的故障复现，不称同manifest strict回放。

原M02回归因内部摘要ABI改变，仅适配原人工reason到quote对象，保留错误目标/工具/正文及一次核对，断言正确人工产物、无退款及预算/流式行为。未删除原业务断言来迁移；历史真实原文件和Gold均保持。

## 当前结论与边界

本批0新增供应商请求、全局账2329保持，未创建Case/人工核查单/退款，未改RAG。只使用所属PG55433的临时测试schema，公共11表、历史报告及四历史脏文件核对见[最终审计](final-audit.json)。仅恢复本批PG停止、保留卷及Docker。

摘要系统字段已有来源硬约束；仍不能证明任意原话选择或正文政策解释语义正确。未做新真实模型/浏览器/Java整栈/全仓/简历评测，也未将原3/4重写成4/4。下一次真实验收需要确认新quote协议的遵循程度；此前目标核对真实触发未观察的边界也继续保留。本批收口，不自动追加付费测试。
