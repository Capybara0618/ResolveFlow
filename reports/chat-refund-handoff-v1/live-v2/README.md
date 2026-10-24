# 修复后单样本真实客服结果（2026-10-24）

生产6d997d8、准备c6f4d98，新合成329元LOST订单，仅发送固定1条消息。[原回答/事件](browser.json)/[全部模型与费用](runtime-results.json)/[真实失败页面](failure-customer.png)保留。

结果FAILED/INVALID_DECISION，尚未生成申请草稿或Case。理解为物流与申请两个focus；首个候选过早回答，缺ORDER/POLICY/GUIDE与申请next_steps，被一次修正拦下。之后三项已读取，最后refund_summary为正确根级字符串，但物流part带SHIPMENT_STATUS/CARRIER_CONCLUSION的facts，正文却未使用对应占位符，仍不符合事实绑定协议，被拒，未正式发布。与本轮已修复的确认材料/核验衔接分开判定。

真实7模型，准确25495输入/816输出token、0未知，原账2076→2083。DOM反馈118ms、候选正文首见5087ms，6次正文变更、29帧SSE和8次状态变更：确实有流式候选，之后撤回失败，不能称正式答案延迟或p95。旧业务/索引/运行比较保持。

不重发本问题、不改协议接受坏回答。继续同一新订单的现成手动申请入口，亲自填写确认原因，单独验证H1–H3核验/审批/模拟退款；最多原计划中2Case run、0新客服消息。此补充不是自动摘要成功，不改首份失败。驱动静态检查通过，输出manual-continuation；若调查失败则保留，不手写模型方案或改库推进。
