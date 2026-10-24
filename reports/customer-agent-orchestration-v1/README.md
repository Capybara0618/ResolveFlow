# 客服编排职责重构实施记录

2026-10-24，合同见docs/customer-agent-orchestration-v1.md。新profile为orchestrated-v1；历史single/staged-v1及失败不重算。

## 第一步：独立就绪控制与回答装配

新增agent/src/resolveflow/support/orchestration.py与agent/tests/unit/test_support_orchestration.py。

- TurnPlan一次接受goal并补最低依据；实际来源按类型/版本/订单行/必要字段检查。受控GUIDE须匹配当前版本/内容，未读来源不是失败；实际不可重试失败才允许BLOCKED。重试失败仍需继续调查。
- Response不接收模型next_steps/fact_rendering/refund_summary；程序装配实际字段、对应UI引用/操作、用户原因摘要。相关POLICY仍由模型选引用；撤销/暂停/受阻不生成可提交原因。
- 提前收尾的就绪快照与格式纠错分开，同一无进展快照第三次终止NO_PROGRESS。

实际命令：
```
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_support_orchestration.py -q --tb=short
agent/.venv/Scripts/python.exe -m mypy --strict agent/src/resolveflow/support/orchestration.py
agent/.venv/Scripts/python.exe -m ruff check agent/src/resolveflow/support/orchestration.py agent/tests/unit/test_support_orchestration.py
```

先红：模块未实现时ModuleNotFoundError。实现后13 passed；strict mypy成功，Ruff成功（初次发现import排序及2处类型问题，已修正复跑）。覆盖正常缺口/有界提前收尾、程序退款装配、纯政策相关引用、实际不可重试失败、撤销、错误行/金额缺失、可重试失败、未读引用、目标错配。

本步尚未接引擎/API/流式/PG恢复，未做新真实模型确认；运行中服务和默认profile未更改，usage仍2102。不得将这些单元通过作为真实模型或网页验收通过。

## 第二步：唯一SDK循环、阶段流式与原发布校验

新orchestrated-v1接入engine/stages，新增orchestration_prompts；progress/stream_projection按程序阶段投影RESPOND，completion允许程序按当前事项依据声明实际相关失败工具。single/staged-v1原规则保持。理解后通过原工具账本读指南一次，原始模型响应先保存，提前RESPOND不占格式纠错，仍记模型费用且无进展有界。COMPOSE编译后继续原导航/事实/金额/事项/完成校验。

红测：新SDK测试先5项均因未知profile失败；实现后扩展为7 passed，覆盖提前收尾补查、有限无进展、纯政策、真正订单失败、流式阶段隔离、伪造金额仍拒绝、只问入口无需订单和摘要。实际命令：
```
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_support_orchestrated_engine.py -q --tb=short
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit -q -k "support or customer_agent_publication or customer_answer or refund_summary" --tb=short
agent/.venv/Scripts/python.exe -m mypy --strict agent/src/resolveflow/support/orchestration.py agent/src/resolveflow/support/orchestration_prompts.py agent/src/resolveflow/support/engine.py agent/src/resolveflow/support/stages.py agent/src/resolveflow/support/progress.py agent/src/resolveflow/support/stream_projection.py agent/src/resolveflow/support/completion.py
```
扩大回归（补最后2项前）418 passed、6 skipped（当时未指定实际PG DSN）、1既有失败：test_customer_agent_publication_v2.py::test_saved_acceptance_paths_pass_without_disabling_the_new_predicate，冻结v2指南与当前v3冲突，保留旧断言/原始失败。7源码strict、本步Ruff通过。不把既有失败/跳过隐藏成全绿。API/runtime profile、真实PG恢复和新真实模型确认尚未完成；原服务未重启，0新付费调用。
