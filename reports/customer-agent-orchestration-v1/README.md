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
扩大回归（补最后2项前）418 passed、6 skipped（核心契约fixture中无citation项的既有条件跳过）、1既有失败：test_customer_agent_publication_v2.py::test_saved_acceptance_paths_pass_without_disabling_the_new_predicate，冻结v2指南与当前v3冲突，保留旧断言/原始失败。7源码strict、本步Ruff通过。不把既有失败/跳过隐藏成全绿。API/runtime profile、真实PG恢复和新真实模型确认尚未完成；原服务未重启，0新付费调用。

## 第三步：显式API/runtime协议及真实PG恢复

service/app/reviewer_demo允许显式orchestrated-v1；日常project_runtime仍staged-v1。新TurnPlan/RESPOND的mock脚本可提前验证，新提示/编排源码hash进入manifest。已完成原结果保持可读，未完成运行不能静默换协议。

- 新runtime红测2失败（mock不识别、API拒绝profile）/1已有流式工程通过；实现后真实临时PG+API/SDK/模拟SSE/原store四组18 passed、0 skipped。原始model.response_json保留RESPOND，指南按独立tool记账，恢复时0模型/工具重发、spend保持，旧profile未完成恢复明确MANIFEST_MISMATCH。
- API默认runtime profile和驱动共32 passed。扩大客服/合同回归421 passed、6 skipped、1既有冻结v2指南诊断失败。六个跳过来自test_contracts_core_citations.py无citation的fixture，不是PG不可达；更正前一步的原因说明。
- service strict mypy与本步Python源码/测试Ruff通过。reviewer_demo.py全文件Ruff有19处既有问题，与HEAD逐code计数比较完全相同；本次只增加允许的profile，不混入无关清理。

实际命令：
```
$env:RESOLVEFLOW_AGENT_DB='postgresql://agent:agent@127.0.0.1:55433/agent_db'
agent/.venv/Scripts/python.exe -m pytest agent/tests/integration/test_support_orchestrated_runtime.py agent/tests/integration/test_support_staged_api.py agent/tests/integration/test_support_stream_runtime.py agent/tests/integration/test_support_store.py -q --tb=short
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_support_api.py agent/tests/unit/test_reviewer_demo_driver.py -q --tb=short
agent/.venv/Scripts/python.exe -m mypy --strict agent/src/resolveflow/support/service.py
```

未部署新profile、未访问真实模型；usage仍2102。后续先固定新协议的离线变换对照，再有限真实确认，不修改旧失败/Gold或日常默认。
