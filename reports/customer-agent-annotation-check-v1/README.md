# 客服标注修复：两条真实确认

2026-10-21。**目标未达成：两条自主单轮中，1条发布且完整，1条INVALID_DECISION。** 本轮只确认标注修复，不代表客服Agent整体或多轮验收通过。

修复提交a0f621b，准备提交7ff0de5；[方案](../../docs/customer-agent-annotation-repair-v1.md)、[冻结清单](../../evals/customer-agent-annotation-check-v1/manifest.json)、[输入](../../evals/customer-agent-annotation-check-v1/cases.json)。沿用原D01/D02首轮问题、事实、政策代际和评分条件，换新运行身份。67文件与既有embedding权重绑定，旧12/88轮与Gold不改。用户要求继续后仅单次运行两条，无新增固定组或付费重跑。

## 实际结果

| 场景 | 实际读取 | 发布/业务结果 | 请求数 | Python接口耗时 |
| --- | --- | --- | --- | --- |
| C01，最新物流 | get_shipment_trace | 完整：按IN_TRANSIT在途回答，未编造预计送达 | 2 | 3.577秒 |
| C02，承运结论+退款资格+申请入口 | get_shipment_trace → get_support_guide → search_policy | 失败：两次ANSWER均漏tasks更新，PENDING未闭合，无可发布回答 | 5 | 6.251秒 |

7次响应均有合法kind，供应商错误0。C01任务从PENDING更新为ANSWERED，引用真实读取的O1/version3，回答原句与任务标注一致。原始UTC事件时间复制到文字但未注明时区，是后续展示问题，不改变已冻结两项评分。

C02自主选择了物流、指南和政策，Query为“台灯 丢失 退款资格 条件 例外”，检索约102.59毫秒，R-LOST-001排第1，原文含LOST、无有效签收、人工核验、订单行全量实付金额。草稿也覆盖这些条件与“我的售后”，但两次回答都没有任务终态标注。实际反馈指出tasks/PENDING与完整重发，模型仍漏tasks，Harness按原约束停止。**不能把正确草稿当作用户已收到的答案，也不能把本条归因为检索未找到政策。** 三个诉求被合成一个LOGISTICS任务，事项拆分也是后续应验证的问题。

## 本轮修复证明与不足

仅首请求、无前轮任务时给出本轮原文的标注形状；CURRENT/0引用说明、拒绝标注未提交及完整重发反馈已接入。C01实际形成“自主读物流→更新任务→发布答案”；C02所有事件引用合法且走通取证，但最终任务更新仍失败。相较旧冒烟自主首轮均失败，这是新观测，不能以不同小队列的1/2和旧0/6计算效果提升，更不能推导Agent优于固定流程。

后续应先利用本次保存的请求/响应做离线关键失败测试：明确回答动作的任务终态形状，核查持续任务如何提示模型，检查混合诉求的事项拆分。当前未实现这些后续改动，未重新收费；多轮暂停/恢复/纠正/撤回仍待独立验收。

## 计量与运行范围

- 真实DeepSeek Flash、温度0、JSON、1024输出上限；生产Python ASGI/SupportRuntime/AgentScope/BGE/只读PG政策，订单物流为已看过的合成HTTP快照。未启动Java、网页或业务队列，非盲测。
- 实际provider usage：输入15338、输出956，均非estimated；账本1743→1750。Harness输入预算记账18078是保守口径，不能替代真实provider token。未设置新的累计消费上限。
- embedding预热12.715秒单列；接口时间包含记录与校验，C02为失败停止时间。仅两条不报告P95/SLA或稳定提速；单次102.59毫秒检索不能替代RAG整体效率评测。
- [完整请求/响应/工具/调用账](runtime-results.json)、[逐项源审](semantic-review.json)、[统计](summary.json)、[工程与保留数据收口](completion.json)。源审为Codex复核，不是独立Gold。

## 验证与保留

中断期间PG退出，导致一次124通过/13跳过和预检PoolTimeout，未记为通过。恢复原保留容器后，25文件137通过/0失败跳过（38.18秒），2生产模块strict mypy及相关Ruff通过；既有Starlette弃用告警保留。冻结与只读数据库预检通过后独立提交、普通push核实，再执行两条。

完整回归命令在agent目录执行，设置`PYTHONPATH=E:/Code/Agent+Backend`及`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_support_annotation_repair.py tests/unit/test_customer_agent_annotation_check_v1.py tests/unit/test_customer_agent_action_smoke_v1.py tests/unit/test_customer_agent_eval_v2.py tests/integration/test_customer_agent_eval_v2.py tests/unit/test_customer_agent_live_v3.py tests/unit/test_customer_rag_live_v2.py tests/integration/test_customer_rag_live_v2.py tests/unit/test_support_agent.py tests/unit/test_support_guidance.py tests/unit/test_support_recovery.py tests/unit/test_support_guide.py tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/unit/test_support_api.py tests/unit/test_contracts_support.py tests/unit/test_contracts_support_agent.py tests/unit/test_support_tasks.py tests/unit/test_support_context.py tests/unit/test_support_memory.py tests/unit/test_support_dialogue.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_guide_api.py tests/integration/test_support_dialogue_api.py -q
```

public11表全行hash在预检/执行前后/收口相同，旧四历史脏文件逐字节相同，两个run与7模型/4工具调用已导出，自有隔离schema删除，未遗留t_ schema。原数据卷保留，普通业务服务未启动；最终端口检查与容器停止结果见completion.json。无新权重、退款、政策发布、UI/简历修改；不以工程通过替代真实业务通过。
