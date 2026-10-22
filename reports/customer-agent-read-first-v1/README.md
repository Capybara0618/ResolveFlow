# 只读取证与任务声明解耦：结果

2026-10-22。**查询阶段的阻塞已解除：真实4次无标注读取均成功执行，未用纠错。业务两题仍未全过：发布1题，完整0/2、部分1/2、失败1/2。** 不把发布率或格式通过率当业务完成率。

[方案](../../docs/customer-agent-read-first-v1.md)，修复aa28d3a，冻结准备5f36eec。未附tasks/dialogue_events的只读动作不更新任务/事件；主动提供标注仍全校验，回答发布仍必须任务/事件/状态/引用完整。移除两个输入说明/示例键，字段仍封闭、一次纠错、原权限预算不变。未知字段不自动删除、任务不自动完成。

## 真实观测

| 场景 | 实际链路 | 发布/业务结果 | 请求 | Python接口时间 |
| --- | --- | --- | --- | --- |
| R01：最新物流 | 无标注读物流成功→分项回答无任务→补任务但漏事件 | 未发布，失败 | 3 | 4.225秒（失败停止） |
| R02：物流结论+资格+申请入口 | 无标注读订单→物流→政策→同次声明三任务/ADD/分项回答 | 已发布，部分通过 | 4 | 5.795秒 |

两题所有查询都不再因首次任务标注缺失而被拒，也没有新增分类调用。R02首次完整走通“先取证→最后同次事项与分项答复→发布”，三事项及当前原句事件明确保留；并不意味着识别所有诉求或语义质量都正确。

R01失败在**发布阶段**：第一次ANSWER_PARTS没有tasks，被render_answer归为ANSWER_PARTS_COVERAGE。反馈只提示先声明tasks，未明确新声明还需要dialogue_events；模型下一次补tasks但漏事件，第二次非法后停止。旧发布约束未绕过，保存轨迹用于离线修正这个错误分类，不收费重跑。

R02正确区分PAID订单与LOST物流，政策R-LOST-001首位、包含无有效签收/人工核验/整行实付金额条件。但没有读取使用指南，申请入口只说“订单/售后入口”，未准确给出当前“我的售后”，还用政策P1支撑页面流程。因此原评分第一条件通过、第二条件失败，记PARTIAL，不计业务完整。实际Query“台灯 承运结论 LOST 退款资格 申请入口”，检索83.41毫秒；问题是政策/使用指南用途选择，不能因本题效果不足再默认加检索算法。

## 机制与证据

- [完整原始请求/响应/工具/调用账](runtime-results.json)、[原条件源审](semantic-review.json)、[统计](summary.json)、[收口](completion.json)。Codex源审，非独立Gold。
- 新7真实请求、输入12308/输出806，provider均非estimated，ledger1767→1774；供应商错误0，kind/Schema均7/7合法。保守Harness输入14982单列，合法Schema不等于可发布或业务正确。
- embedding预热9.249秒单列，温度0/JSON/1024输出上限/120秒deadline保持。两题时间含API/SDK/持久记录，失败停止时间亦保留，不算两题P95/SLA/提速/降本。
- [98文件新清单](../../evals/customer-agent-read-first-v1/manifest.json)及既有权重冻结，原D01/D02问题/事实/评分/政策保持，仅运行身份变化。真实模型/ASGI/AgentScope/只读保留PG，订单物流为已看过合成HTTP快照，非Java/网页全栈或盲测。无多轮付费扩展/重跑，不更新简历。

## 工程回归

新增14测试先8失败/6通过，实现后14通过。13文件集中首107通过/2失败（旧措辞断言、指南窗口），语义措辞统一后108/1，保守输入实测7251/7168；压缩重复说明保留预算/原文，最终109通过。旧模板断言明确变更为无输入说明键，客户原文继续精确保留；4源码strict mypy/相关Ruff通过。

新API-PG与准备3测试通过：实际3次无标注查询后声明3任务并发布，保存4模型/3工具原文，到期run恢复0模型/0HTTP、结果相同。36文件集中 **188通过/0失败/0跳过，31.63秒**，既有Starlette弃用告警保留。冻结/只读PG预检及四历史脏文件/public11表核验通过，准备独立提交普通push核实后单次真实执行。在agent目录设置`PYTHONPATH=E:/Code/Agent+Backend`、`RESOLVEFLOW_AGENT_DB=postgresql://agent:agent@127.0.0.1:55433/agent_db`：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_support_read_before_tasks.py tests/integration/test_support_read_before_tasks_api.py tests/unit/test_customer_agent_read_first_v1.py tests/unit/test_support_answer_parts.py tests/integration/test_support_answer_parts_api.py tests/unit/test_customer_agent_answer_parts_v1.py tests/unit/test_support_event_groups.py tests/integration/test_support_event_groups_api.py tests/unit/test_customer_agent_event_groups_v1.py tests/unit/test_support_answer_tasks.py tests/unit/test_customer_agent_answer_tasks_v1.py tests/unit/test_support_annotation_repair.py tests/unit/test_customer_agent_annotation_check_v1.py tests/unit/test_customer_agent_action_smoke_v1.py tests/unit/test_customer_agent_eval_v2.py tests/integration/test_customer_agent_eval_v2.py tests/unit/test_customer_agent_live_v3.py tests/unit/test_customer_rag_live_v2.py tests/integration/test_customer_rag_live_v2.py tests/unit/test_support_agent.py tests/unit/test_support_guidance.py tests/unit/test_support_recovery.py tests/unit/test_support_guide.py tests/unit/test_support_sources.py tests/unit/test_support_retrieval.py tests/unit/test_support_api.py tests/unit/test_contracts_support.py tests/unit/test_contracts_support_agent.py tests/unit/test_support_tasks.py tests/unit/test_support_context.py tests/unit/test_support_memory.py tests/unit/test_support_dialogue.py tests/integration/test_support_store.py tests/integration/test_support_retrieval_index.py tests/integration/test_support_guide_api.py tests/integration/test_support_dialogue_api.py -q
```

public11表全行hash与预检/执行前后/上批一致，旧四历史脏文件字节保持，2 run/7模型/4工具账已导出，自有隔离schema清理，无t_ schema。离线回归后已再次核验公共数据，临时PG已停止、原卷保留、10项目端口闭、本批进程退出。旧Gold/输入/报告/清单不改，无Java/UI/资金/政策或新权重修改。

## 本轮随后离线修复与最终状态

真实结果先独立归档b226b68，再按[反馈说明](../../docs/customer-agent-read-first-feedback-v1.md)用保存的R01补关键测试（先1失败/1通过），3行分类修复将无初始任务的分项回答交给TASKS_REQUIRED，明确要求tasks和dialogue_events。原“只补tasks、无事件”的保存响应仍拒绝；显式补齐事件的脚本轨迹可一次修正通过，原始响应不改。

此修复提交0d4feac。最终37文件集中 **190通过/0失败/0跳过，30.58秒**，即以上36文件命令增加`tests/unit/test_support_publication_feedback.py`；4源码strict mypy和相关Ruff通过，首新测试1长行已修。无额外付费请求，ledger仍1774。原98清单按预期拒绝更新后的tasks.py，不改历史hash；最后这一反馈修复尚无新真实模型确认。申请入口来源选择仍未修复，业务不能称全通过。
