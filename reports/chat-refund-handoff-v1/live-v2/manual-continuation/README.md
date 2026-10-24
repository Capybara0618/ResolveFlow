# 手动确认入口的核验与模拟退款：真实整栈通过

2026-10-24，生产6d997d8、准备4160777。沿同一新订单/会话，不重发客服问题，不改上游失败、不手写模型方案。真实Vue→Gateway→Case/Commerce→Python AgentScope→DeepSeek Flash；支付、物流和退款为明确模拟。

| 步骤 | 实际结果 |
| --- | --- |
| 客户填写并编辑确认原因 | 确认前无Case；回执213ms，同键重放/刷新同一Case |
| 初始陈述 | revision1，CUSTOMER_STATEMENT，只有最终确认原因，没有核验值或其他私聊 |
| 首次Agent调查 | 5次模型/0修正，正常MANUAL_REVIEW、有效引用、无退款授权 |
| 商家核验 | 从“核验申请陈述”进入原材料区，CONFIRMED关联原陈述；原文/hash保持，新输入revision2 |
| 第二次Agent调查 | 5次模型/0修正，正常REFUND，Java复核后生成revision2待审授权 |
| 商家审批与退款 | 网页独立批准，唯一退款操作SUCCEEDED，整行32900分已退、预留0 |
| 客户结果 | 原会话及原申请详情同一Case，CLOSED_SUCCESS |

Case：1cbb2300-ffaf-4686-bcbf-f18acd3d7f8e。总10个真实模型请求，准确19800输入/1063输出token、0未知/非估算，原账2083→2093；新客服消息0。保存[浏览器请求/两个版本快照](browser.json)、[两run模型逐调用与资金账](runtime-results.json)。旧工单/付款/操作/政策/运行及原客服失败保持。

真实页面：[客户待核验](customer-waiting-verification.png)、[商家待核验](merchant-waiting-verification.png)、[核验原陈述](merchant-verification.png)、[有效退款方案待审批](merchant-review.png)、[原会话退款完成](refund-complete.png)、[原申请详情](same-application-detail.png)。

这证明本轮H1–H3的确认/核验/重新调查/审批/模拟退款衔接可实际完成。上游客服自动回答仍[失败](../README.md)，不能将本次手动填写的原因当成自动摘要成功，也不能外推多场景准确率或p95。
