# 客服事件分组：工程与真实确认

2026-10-21。**显式分组在真实混合题中已生效，但两条业务确认仍只有1条完整，未达2/2。** 本轮未进入四轮付费扩展，不宣称客服整体完成或成功率提升。

## 实现与依据

[设计](../../docs/customer-agent-event-groups-v1.md)，修复dc9228e，准备48ce783。

任务状态与客户本轮引起的变化含义不同，不能仅从状态猜测暂停/撤回。但相同变化、相同客户原句关联多个任务时，可显式输出一个事件：`task_ids:["t1","t2","t3"]`，不重复三份change/reference/quote。旧task_id保持兼容，两者二选一，1–8个不同合法ID。

程序只展开模型明确给出的ID，逐任务检查前后状态、当前客户原文和覆盖；组内非法、重复/重叠/未知任务、旧消息引用仍拒绝整次动作。内部输出仍为逐任务事件，公共API/Java保持。漏覆盖反馈列missing_task_ids及完整重发/分组规则；不自动填事件或任务终态，不增加模型分类请求/纠错次数/预算。

## 真实结果

| 场景 | 实际链路 | 发布结果 | 请求数 | Python接口耗时 |
| --- | --- | --- | --- | --- |
| E01：最新物流 | 单任务分组ADD → 读取物流 → ANSWERED回答 | 完整：按IN_TRANSIT说明在途，未编造预计送达 | 2 | 3.700秒 |
| E02：承运结论+资格+入口 | 三任务分组ADD → 订单 → 物流 → 政策 → 指南 → ANSWER被拒 | 失败，INVALID_DECISION，无发布答案 | 6 | 8.683秒（失败停止） |

E02首次实际输出LOGISTICS/ELIGIBILITY/APPLICATION三个任务，一个ADD/task_ids覆盖三项，被成功接受，已解除上一批首次事件覆盖阻塞。之后自主查到LOST物流、R-LOST-001与使用指南，Query为“台灯 LOST 丢失 退款资格 条件 例外”，检索115.42毫秒，R-LOST-001排第1。实际业务/知识工具5次（两题合计），检索1次。

剩余两个具体问题：

- 中途误写READ_TOOL/tool_name=search_policy；目录要求SEARCH_POLICY。模型经一次反馈改用合法动作并成功检索，该次纠错机会已消耗。
- 最终ANSWER包含全量三任务，却把response_excerpt写成改述，而非text的实际子串。例如t1片段“承运结论为 LOST，物流状态 LOST，无有效签收记录。”并不在正文中。三个片段均不满足原句校验；保存响应离线复现TaskStateError，且此前有效任务仍是PENDING。再次非法后按既有机制停止，草稿不发布。

因此，本轮证明了分组格式可被模型使用、三事项可以完成取证；**尚未证明混合回答任务闭合通过**。源审按原条件将未发布题计失败，不能用正确草稿/取证完成代替业务成功。本轮没有遇到RAG漏主条款，不把失败归因于检索。

后续应先离线审查模型动作与实际工具目录的表达一致性，以及回答正文/任务片段的重复生成负担；这些为待修问题，本轮未改、未另行付费重复。不要继续仅增加长提示，或靠自动标完成、扩大纠错次数通过测试。多轮暂停/恢复/纠正/撤回真实质量仍未验证。

## 计量与范围

- 新8次真实DeepSeek Flash请求，provider输入18357/输出975，均非estimated；ledger1754→1762。供应商错误0；kind合法8/8，但动作Schema合法7/8，不能混称所有动作正确。最终失败是任务原句校验，区别于前面的工具Schema错误。
- Harness保守输入21665与真实provider输入分开；embedding预热11.888秒单列。保持温度0/JSON/1024输出上限、120秒deadline及原RAG。接口时间含Python API/SDK/保存开销，失败时间也入报告；不报两题P95/SLA/稳定提速/降本。
- 原D01/D02完整输入仅run/conversation身份变化，事实、评分、政策代际不改。[新清单](../../evals/customer-agent-event-groups-v1/manifest.json)冻结82文件与既有权重；已看过合成HTTP快照、真实模型/ASGI/AgentScope/只读PG，不是Java/网页全栈或独立盲测。
- [完整轨迹](runtime-results.json)、[逐项源审与原句对照](semantic-review.json)、[统计](summary.json)、[工程/数据/运行收口](completion.json)。源审由Codex完成，非独立Gold。

## 验证与收口

新11测试首次5失败/6通过，旧协议已有负例拒绝。接实现后两次81通过/1指南窗口失败，实测保守输入7172/7168；删重复说明而非原文/预算后10文件82通过。4生产模块strict mypy与相关Ruff通过。新ASGI/SDK/隔离PG分组持久与到期run恢复1通过（初Ruff一长行修正）：3次脚本模型/1次工具保存，恢复0模型/0网络，结果完全相同。新评测准备2测试通过。

30文件集中 **158通过/0失败/0跳过，36.75秒**，保留Starlette既有弃用告警。冻结/只读PG预检通过，独立提交普通push核实后单次真实执行。设置`PYTHONPATH=E:/Code/Agent+Backend`、`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`，在agent目录执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_support_event_groups.py tests/integration/test_support_event_groups_api.py tests/unit/test_customer_agent_event_groups_v1.py tests/unit/test_support_answer_tasks.py tests/unit/test_customer_agent_answer_tasks_v1.py tests/unit/test_support_annotation_repair.py tests/unit/test_customer_agent_annotation_check_v1.py tests/unit/test_customer_agent_action_smoke_v1.py tests/unit/test_customer_agent_eval_v2.py tests/integration/test_customer_agent_eval_v2.py tests/unit/test_customer_agent_live_v3.py tests/unit/test_customer_rag_live_v2.py tests/integration/test_customer_rag_live_v2.py tests/unit/test_support_agent.py tests/unit/test_support_guidance.py tests/unit/test_support_recovery.py tests/unit/test_support_guide.py tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/unit/test_support_api.py tests/unit/test_contracts_support.py tests/unit/test_contracts_support_agent.py tests/unit/test_support_tasks.py tests/unit/test_support_context.py tests/unit/test_support_memory.py tests/unit/test_support_dialogue.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_guide_api.py tests/integration/test_support_dialogue_api.py -q
```

public11表全行hash与预检/执行前后/上批一致，四历史脏文件逐字节相同；旧输入/Gold/报告不改。2 run/8模型/5工具调用账已导出，自有隔离schema清理、无t_ schema；原数据卷保留，临时PG停止/10端口闭/本批进程退出记录在completion.json。无新依赖权重、资金/政策发布、Java/UI或简历修改。
