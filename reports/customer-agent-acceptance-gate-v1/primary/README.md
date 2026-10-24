# 主链路一次真实验收：未通过

2026-10-24，准备8af7335已普通push核实后，执行`python scripts/accept_customer_agent_gate_v1.py execute`一次。真实Vue/Java/Python/DeepSeek，合成订单/物流，生产Agent/RAG保持d99fb4d对应最终源码。

实际理解为t1物流需SHIPMENT，t2准备退款原因需ORDER/GUIDE。第2步读取物流，第3步候选正确采用fields-v1，提供字符串refund_summary，但t2没有next_steps。根级摘要语义检查在导航/来源诊断之前抛通用ValueError；反馈回落为“citations、可用O1”，没有指出缺少REFUND_APPLICATION和ORDER/GUIDE。第4步模型删掉摘要，仍未补操作/来源，最终INVALID_DECISION、没有正式发布。

- 真实4请求，准确Provider输入10032/输出528、0未知/非估算，原账2098→2102；完整[runtime-results.json](runtime-results.json)包含全部实际请求/响应/工具与保留核对。
- DOM首反馈150ms、候选首正文4478ms；随后撤回，正式回答未出现，不能当成功首字或完成时间。实际事件见[browser.json](browser.json)，[页面](failure-customer.png)。
- 未生成自动草稿、未编辑/确认、没有新Case调查/授权/退款；同键恢复等后续步骤均未运行。B–D按预先协议未启动，没有用手动入口或人工摘要补造成功。
- 旧业务/索引/全部旧客服run与13保护文件保持；新单已付32900、已退0、预留0，无在途，全部调用计费保存。

根因进一步明确为发布检查的短路诊断：上一修复只覆盖GroundingError，摘要/操作前置检查属于普通ValueError，绕过了来源缺项收集；同一个回答的多项协议缺口仍未在一次反馈里完整呈现。下一步离线聚合来源、必要操作及摘要语义诊断，保留原一次修正/所有发布断言，不逐句增加业务提示或自动继续收费测试。
