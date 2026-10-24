# 操作摘要的客户原话与系统事实分离

2026-10-24，针对[Q01/1实际反例](../reports/customer-agent-goal-confirm-v1/source-review.json)：本轮仅读GUIDE，人工摘要却自由生成“已核实客户已付款订单”。product支持商品信息、policy_manifest支持政策版本选择，均不能代替当前订单状态Observation。

## 设计与协议

保留orchestrated-v1、唯一AgentScope循环及原UNDERSTAND/INVESTIGATE/COMPOSE分工。改变内部RESPOND的refund_reason/handoff_reason：从自由字符串改为`{"customer_quotes":["客户原话"]}`。每个对象选1–4条，每条1–300字符，非空、不重复，不接受额外verified_facts等自由字段。

模型继续负责理解诉求、判断调查所需依据、按Observation选工具及组织解释；准备操作摘要时选择最相关原话。程序完成以下装配：

1. 原话必须是当前输入的确切片段，或已通过CustomerMemory作用域/来源验证、仍ACTIVE的历史完整quote；历史原文同时须匹配source.quote且来自更早输入。不能取助手文字、模型改写、SUPERSEDED/RETRACTED陈述或未来来源。
2. 原话统一标为“客户陈述（未经核验）”，保留本轮/历史有效陈述标签。用JSON字符串引用，换行等控制字符转义，避免原话伪装成新的系统事实区。
3. 只使用对应目标事项已装配的AnswerFact，逐项经value_for重查ORDER/SHIPMENT类型、版本存在、非错误及当前订单行。状态、金额和承运商记录由程序显示，附本run O编号；来源版本沿用外层citations。其他事项的读数、不相关POLICY/GUIDE及商品展示不填作系统状态。
4. 未读取订单或物流时明确未附已读系统记录；不为了生成普通人工摘要强制读取全套工具。系统记录与客户陈述并列，不把承运商记录等同于已核验客户投诉。
5. 程序附“尚未发送/尚未提交、待本人确认”，整段不超过外部原2000字符上限；超限返回原有一次纠正反馈，不静默截掉事实或来源。

Java/前端收到的handoff_summary/refund_summary仍为字符串，原可编辑确认卡片、共享与建单协议不变。未改业务权限、预算、资金或SDK主循环，也未新增校验LLM请求。未改single/staged-v1的旧兼容协议；同run仍按原manifest，新增逻辑被既有grounding.py/orchestration.py/engine.py/prompt源码hash覆盖，旧未完成run不能静默换协议。

## 与目标核对的关系

产物仍用refund_reason/handoff_reason标明用途，因此上一批一次REVIEW_GOAL机制保留。旧目标错误时，新结构的人工摘要仍能触发目标冲突核对；纠正后选定原话及实际已有证据由程序重新装配。旧自由字符串不迁移为可发布内容，而是走原格式纠正。旧M02回归仅适配摘要字段结构，保留原错误计划、工具和正文；原历史文件不变。

## 验证与限制

原Q01两个决定原样重放，旧错误自由摘要拒绝，再由脚本提供新quote对象，不能把这一步称为真实模型自行修正。验证商品/政策元数据、客户与系统冲突、失效历史、重复/额外字段、换行标签、错误来源、SDK目标核对和PG租约恢复；结果见[报告](../reports/customer-agent-summary-grounding-v1/README.md)。

这保证摘要中系统事实字段的来源，不是任意自然语言真伪判定。模型仍可能选取不完整、歧义或不相关原话，特别是截取片段丢失否定/假设语境；提示要求保留原意，但出处匹配本身不能证明语义正确。正文政策解释仍需原质量检查。新协议对真实模型的遵循程度及目标核对的真实触发仍待单独有限验收，本批0新付费请求，不改旧评分、不更新简历指标。
