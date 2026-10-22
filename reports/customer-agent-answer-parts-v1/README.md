# 客服回答单次生成：实施与真实确认

2026-10-22。**分项回答已实现并在真实物流题发布；真实两条仍仅1条完整，混合题在首次标注阶段失败。** 不能宣称整体完成率提升，未启动四轮付费扩展。

## 改动

[设计](../../docs/customer-agent-answer-parts-v1.md)，实施5758e7a，准备469e398。

- 新ANSWER_PARTS按task_id给显式状态、text、citations，程序按顺序用空行连接正文，引用有序去重，从已确认任务复制意图/诉求。任务response_excerpt从同一text取前400字符，全文不截断。模型不用重复生成全文和逐字摘录，没有自动推断任务完成。
- 全部任务逐项覆盖，漏/重复/未知ID、未来引用、PENDING、未经事件授权撤回、无首次任务声明或拼接后超过4000字符均拒绝。旧ANSWER的精确摘录校验继续保留。初始任务、记忆、对话事件仍原子校验，只有一次纠错。
- 新显式READ_TOOL/search_policy/arguments与目录/真实执行入口一致，共享query/top_k及额外字段禁止校验；旧SEARCH_POLICY仍兼容，同预算/引用/记录。不自动改写模型错输出或放宽跨主体读取。
- 原始模型响应先保存，校验后将parts确定性渲染为SDK兼容ANSWER；公开Java/客户消息结构保持。恢复重建相同文本/任务/引用，没有新模型/网络或第二循环。

## 真实结果

| 场景 | 行为 | 业务结果 | 模型请求 | Python接口耗时 |
| --- | --- | --- | --- | --- |
| P01：最新物流 | 首次漏tasks；纠错完整重发后查物流；ANSWER_PARTS生成并发布 | 完整，按IN_TRANSIT说明在途，无虚构预计送达 | 3 | 3.863秒 |
| P02：承运结论+资格+入口 | 首次误输出annotation_example_note且漏任务；纠错仍只有工具动作 | INVALID_DECISION，无工具执行/无答案 | 2 | 1.769秒（失败停止） |

P01真实最终输出为ANSWER_PARTS，部分text与发布正文完全一致，内部任务摘录由同一正文投影，消除了该路径的重复改述校验问题。但模型还额外重发了tasks元数据，说明“不重复”的建议未被完全遵循；状态来自part显式值，结果校验通过。首动作漏tasks仍消耗一次修正，不能称协议已稳定。

P02首动作包含`annotation_example_note:先取订单/付款事实，再查物流与政策`，该键是上下文说明，不是合法输出字段。extra_forbidden反馈后只重发READ_TOOL/get_order_context，不带首次tasks/dialogue_events，继续失败。实际读取和RAG调用均0，不能归因为检索差或ANSWER_PARTS生成失败。未到混合回答阶段，不能证明其已修复。

后续应先离线梳理首次任务声明与工具动作的组合呈现、输入说明键进入输出的原因，考虑让首次声明与后续工具/回答的职责更清楚；不能继续仅加长提示或反复收费试题。本轮不新增此后续实现，也未扩大纠错次数/自动填任务。两条为已看过合成问题，不能用于简历泛化完成率。

## 计量与证据

- 5次真实DeepSeek Flash请求，输入7793/输出384，provider均非estimated，ledger1762→1767；供应商错误0，kind合法5/5，Schema合法4/5。保守Harness输入9766单列，不能作为实际provider token。
- embedding预热10.687秒单列，温度0/JSON/1024输出上限与120秒deadline保持。接口包含Python/SDK/持久化，P02是失败停止时间；不报两题P95/SLA/稳定提速或降本。
- 原D01/D02完整请求仅run/conversation身份变化，事实、评分、政策代际保持。[清单](../../evals/customer-agent-answer-parts-v1/manifest.json)新冻结90文件及既有权重。真实模型/ASGI/AgentScope/只读PG，订单物流为冻结合成HTTP快照，非Java/网页全栈或盲测。
- [原始请求/响应/工具/调用账](runtime-results.json)、[源审](semantic-review.json)、[统计](summary.json)、[收口](completion.json)。源审由Codex复核，非独立Gold；失败按原条件计入分母。

## 工程验证与保留

新测试先3失败/6通过；接实现后39通过/1新脚本引用夹具错误（只读P1却沿用默认O1，改夹具引用P1）。协议/目录显式升级后4旧枚举/示例期望与1窗口测试失败，按新增契约更新断言并保留旧ANSWER/SEARCH_POLICY严格解析；SYSTEM使用新parts示例代替重复完整ANSWER示例后通过。另补总长/初始重复边界，11文件92通过；4生产模块strict mypy/相关Ruff通过。

新准备/实际ASGI-SDK-隔离PG测试共3通过，原始parts逐字持久化，2模型/1工具结果恢复时0模型/0HTTP；首次Ruff一长行修正。33文件集中 **171通过/0失败/0跳过，48.66秒**，既有Starlette弃用告警保留。冻结与只读PG预检通过后独立提交普通push核实，再单次执行真实两条。agent目录设置`PYTHONPATH=E:/Code/Agent+Backend`、`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_support_answer_parts.py tests/integration/test_support_answer_parts_api.py tests/unit/test_customer_agent_answer_parts_v1.py tests/unit/test_support_event_groups.py tests/integration/test_support_event_groups_api.py tests/unit/test_customer_agent_event_groups_v1.py tests/unit/test_support_answer_tasks.py tests/unit/test_customer_agent_answer_tasks_v1.py tests/unit/test_support_annotation_repair.py tests/unit/test_customer_agent_annotation_check_v1.py tests/unit/test_customer_agent_action_smoke_v1.py tests/unit/test_customer_agent_eval_v2.py tests/integration/test_customer_agent_eval_v2.py tests/unit/test_customer_agent_live_v3.py tests/unit/test_customer_rag_live_v2.py tests/integration/test_customer_rag_live_v2.py tests/unit/test_support_agent.py tests/unit/test_support_guidance.py tests/unit/test_support_recovery.py tests/unit/test_support_guide.py tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/unit/test_support_api.py tests/unit/test_contracts_support.py tests/unit/test_contracts_support_agent.py tests/unit/test_support_tasks.py tests/unit/test_support_context.py tests/unit/test_support_memory.py tests/unit/test_support_dialogue.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_guide_api.py tests/integration/test_support_dialogue_api.py -q
```

public11表全行hash与预检/执行前后/上批相同，四历史脏文件逐字节保持；旧输入/Gold/报告/清单不改。2 run/5模型/1工具账已导出，自有隔离schema清理且无t_ schema。临时PG停止/原卷保留/10端口闭/本批进程退出见completion.json。未改简历/UI/Java、未发布政策或退款，无新依赖权重。
