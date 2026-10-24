# 一次真实客服确认：未整体通过

2026-10-24，按准备提交d94f7a4的[冻结计划](plan.json)只执行一次。新合成329元LOST订单；实际Vue→Java→Python→DeepSeek，原预算不变，无mock、拦截响应或替换模型建议。

- **原事实格式缺口已避开**：两次实际候选都明确`fact_rendering=fields-v1`，物流facts合法选择SHIPMENT_STATUS/CARRIER_CONCLUSION及已读O1，没有占位符。原根级退款摘要也为字符串。
- **本轮正式发布失败**：模型第3步提前回答，用物流O1充当退款操作GUIDE；一次修正反馈只要求补读get_support_guide。第4步读取指南，第5步虽引用正确指南，但仍未读取/引用自己声明的申请事项ORDER。最终stage_sources拒绝，INVALID_DECISION；没有正式回答/自动草稿，编辑与刷新步骤未运行。
- 离线使用原5个模型动作及原2个工具结果、只更新诊断deadline，经原SDK复现同样失败；精确末次`StageError.gaps=[{task_id:t2,need:ORDER}]`。不是占位符、检索失败或资金核验失败。本次实际最后回复仍混入非客户必需的商家核查说明，不能据字段协议宣称自然解释质量全过。
- **5次真实请求**，准确14070输入/678输出，0未知/非估算，原全局usage2093→2098。Harness spend中的16546输入含估算预留口径，不作为Provider准确token。所有失败均计费并保留。
- DOM首反馈168ms、候选首正文3951ms，随后候选撤回，无正式答案完成时间；不能当正式首字或p95。实际帧/原文见[browser.json](browser.json)，实际请求/返回/费用/审计见[runtime-results.json](runtime-results.json)，[失败页面](failure-customer.png)。
- 原7Case/归属/政策钉住与3政策、5授权/操作、14旧付款、8旧调查、全部旧客服结果/精确索引及10保护文件SHA保持。新单已付32900、已退0、预留0，0新Case调查/退款，无在途run；没有重发或用手工摘要代替自动摘要。

根因定位：现有拒绝诊断先尝试整体合并next_steps引用，遇到首个无效GUIDE就抛错，导致同时缺少的ORDER未加入反馈。下一步只修正拒绝反馈的只读来源缺项收集；不放松发布、增修正次数、固定完整工具路径或改本次失败。不自动发第二条收费测试。
