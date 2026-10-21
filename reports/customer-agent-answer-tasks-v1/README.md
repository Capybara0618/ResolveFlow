# 客服回答任务修复与真实确认

2026-10-21。**工程修复已完成，真实两条仍仅1条业务完整，未达2/2目标。** 混合题在首次标注阶段就被拒，未走到最终回答，不能据此称任务闭合问题已全部解决。按预先规定的门槛，本轮未继续四轮付费测试。

## 改了什么

[方案](../../docs/customer-agent-answer-tasks-v1.md)，修复提交5fd5d5a，准备提交3c2007f。

1. 真实发送SYSTEM中的ANSWER示例带全量tasks/原句/evidence_refs；首次与ANSWER均须携带任务，独立事项分开跟踪，仍由同次模型判断，无关键词路由或额外分类调用。
2. 已有任务时每次请求携带answer_requirements，列出回答所需任务ID。不会自动替模型选终态或提交标注。
3. PENDING及删任务反馈增加具体issue/task_ids、合法状态、原句和引用要求。仍只有一次纠错，未接受标注不提交，重复非法仍失败。

新离线测试复用上批两条真实被拒ANSWER，验证精准反馈与状态不污染；另用明确标为脚本的三事项修正轨迹验证完整重发，引用映射仅为脚本源O1，未改原报告。旧来源、暂停恢复、撤回、窗口、持久恢复与权限断言保留。

## 真实观测

| 场景 | 实际行为 | 结果 | 请求数 | Python接口时间 |
| --- | --- | --- | --- | --- |
| A01：最新物流 | 自主读物流；ANSWER携带任务ANSWERED、实际原句与O1引用 | 完整，准确在途且无编造预计送达 | 2 | 3.341秒 |
| A02：物流结论+资格+入口 | 首次提出三任务但只标一个ADD事件；拒绝后仅重发工具动作 | INVALID_DECISION，无工具执行/无答案 | 2 | 2.840秒（失败停止） |

A02首次分为t1/LOGISTICS“台灯的承运结论”、t2/ELIGIBILITY“台灯能否退”、t3/APPLICATION“退款在哪申请”，这是实际拆分观测。但dialogue_events只包含t1，不能通过原逐任务覆盖校验。反馈已发送“完整动作/拒绝标注未保存/以当前接受状态为准”，模型修正只包含get_order_context，无tasks或事件，故再次拒绝。

本轮混合题比上批更早失败。既不能把“拆出三个任务”当最终完成，也不能称本轮RAG效果差——该题没有执行检索。A01实际走通“取证→更新任务→回答”；A02未触发新的ANSWER/PENDING精准反馈，**新反馈对真实混合回答的作用尚未验证**。两次单轮结果均为1/2，未证明整体改善，也未证明可稳定复现或泛化。

后续应利用本次完整请求/响应离线分析任务与事件两套标注的一致性：首次多事项缺哪些事件、原子拒绝后的补全说明，以及是否有必要同时表达重复信息。优先调整通用契约呈现，不能自动标完成或按案例写规则；本轮不再追加提示/付费追分。多轮暂停/恢复/纠正/撤回真实质量仍待独立验收。

## 计量与范围

- 4次真实DeepSeek Flash请求，输入6120/输出468，provider均非estimated，供应商错误0，kind合法4/4；ledger1750→1754，无付费重跑/新累计消费上限。
- Harness保守输入预算7665与provider6120分开报告。模型响应均未达到1024输出上限；不是截断引起。
- embedding预热12.240秒单列。接口时间含Python API/SDK/持久记录，A02是失败停止时间。样本仅2条，不计算P95/SLA或稳定提速。
- 原D01/D02问题、事实、评分、完整请求仅run/conversation身份变化；[新清单](../../evals/customer-agent-answer-tasks-v1/manifest.json)冻结74文件和既有权重。合成HTTP订单物流、真实ASGI/AgentScope/保留PG，未启动Java/网页/业务队列；已看过的合成题，非独立盲测。
- [完整轨迹](runtime-results.json)、[原条件逐项源审](semantic-review.json)、[统计](summary.json)、[收口](completion.json)。Codex源审非独立Gold。

## 工程验证与保留

新5测试先全失败。实现后69通过/2窗口失败，精简后两次70通过/1指南窗口失败；保守输入实测7332/7168，压缩重复说明而非原文/预算后9文件71通过。首次Ruff两长行修正；3源码strict mypy与相关Ruff通过。新准备测试首次1失败/1通过暴露加载器替换递归，保留原函数后2通过。

原保留PG启动后的27文件集中 **144通过/0失败/0跳过，34.74秒**；既有Starlette弃用告警保留。设置`PYTHONPATH=E:/Code/Agent+Backend`、`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`，在agent目录执行：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_support_answer_tasks.py tests/unit/test_customer_agent_answer_tasks_v1.py tests/unit/test_support_annotation_repair.py tests/unit/test_customer_agent_annotation_check_v1.py tests/unit/test_customer_agent_action_smoke_v1.py tests/unit/test_customer_agent_eval_v2.py tests/integration/test_customer_agent_eval_v2.py tests/unit/test_customer_agent_live_v3.py tests/unit/test_customer_rag_live_v2.py tests/integration/test_customer_rag_live_v2.py tests/unit/test_support_agent.py tests/unit/test_support_guidance.py tests/unit/test_support_recovery.py tests/unit/test_support_guide.py tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/unit/test_support_api.py tests/unit/test_contracts_support.py tests/unit/test_contracts_support_agent.py tests/unit/test_support_tasks.py tests/unit/test_support_context.py tests/unit/test_support_memory.py tests/unit/test_support_dialogue.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_guide_api.py tests/integration/test_support_dialogue_api.py -q
```

冻结/只读PG预检通过，准备独立提交并普通push核实后单次真实执行。public11表全行hash与预检/执行前后/上一批一致，四历史脏文件字节保持，旧Gold/输入/报告不改。两个run及4模型/1工具调用账已导出，自有schema清理且无t_ schema。临时PG停止、原卷保留、10项目端口闭和本批进程退出在completion.json记录。无简历/UI修改、新依赖、退款或政策发布。
