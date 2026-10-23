# 聊天退款闭环：使用与实现边界

2026-10-23。设计依据：[实施合同](customer-chat-refund-implementation-v1.md)、[已认可预期稿](ui-chat-refund-stream-v1/index.html#confirm)。实现证据：[集中报告](../reports/chat-refund-closure-v1/README.md)。本页不维护独立进度。

## 用户体验

1. 买家在“售后咨询”选择本人已付款商品，描述物流或商品问题。助手仍按需读取订单、物流与政策，正文沿现有真实流式通道显示。
2. 最终回答可携带申请原因建议，当前会话据此准备可编辑卡片；模型失败、未提供建议时，也可点击“申请退款”手工准备。仅询问政策或入口不需要自动准备。
3. 卡片显示服务端核对的整行实付、数量和原因。点击编辑并保存原因；暂不申请保留已保存原因，不创建工单。
4. 点击“确认提交申请”才创建正式申请，同卡片显示申请编号和当前进度。“我的售后”展示同一笔申请。回执不明时使用“确认原请求结果”，刷新仍保留同一请求，不自动换键建单。
5. 等待补证时打开原申请详情补充材料；核查/审批/模拟退款复用既有链路。结果待确认与退款完成分别展示，不将UNKNOWN当成功。

商家从现有“售后工单”查看客户确认提交的原因，审核及后续处理入口保持。原人工咨询核查单仍可独立回复，未提交的退款草稿/退款建议摘要不随共享调查报告发送给商家。首版材料在原申请详情补充，不自动把私聊作为证据。

## 当前接口

所有接口位于`/api/v1/support/conversations/{id}`，仅本人平台买家访问。写请求携带`Idempotency-Key`，金额/身份不作为客户端输入。

| 方法与后缀 | 请求 | 行为 |
| --- | --- | --- |
| GET `/refund-application` | 无 | `{draft,application}`，application复用客户Case Detail |
| POST `/refund-drafts` | `{expected_version,reason}` | 核对后生成30分钟草稿，同版本已有有效草稿保留用户编辑 |
| POST `/refund-drafts/{draftId}/edit` | `{revision,reason}` | 保存原因，revision递增 |
| POST `/refund-drafts/{draftId}/cancel` | `{revision}` | 暂不申请，保留已保存原因 |
| POST `/refund-drafts/{draftId}/confirm` | `{revision,expected_version}` | 重核资格，原子创建Case/关联/回执或恢复已有申请 |

实际采用POST edit/cancel，替代早期目标协议的PATCH草案；原契约新增路由/共享类型/fixture已同步。退款进度采用当前客户投影5秒只读轮询和手动刷新，不新增`refund.created/progress` SSE事件；Agent正文继续原SSE。草稿状态另包含按当前输入版本投影的STALE。

## 实现与验收边界

仍是唯一AgentScope两阶段循环。可选`refund_summary`属于同一次最终ANSWER/ANSWER_PARTS，必须与已读取指南及REFUND_APPLICATION步骤同时通过原终局校验；不增加总结调用或模型写工具。只有接纳后的本人助手消息可准备草稿，生成中的正文不能作为操作依据。

Java CaseService拆出无写入的准备，网络读取在事务外；确认短事务调用原CaseWriter并写入当前草稿关联/回执。旧申请入口继续原建单行为。已有申请、同键并发、响应丢失、旧版本/过期和关联失败回滚分别验证，不改资金与审批职责。

本批工程、真实隔离数据库和合成业务网页已验证；未运行本批真实DeepSeek自然对话到模拟退款完成的整栈验收，也未测本批p50/p95或简历指标。日常项目保持停止，后续按原启动入口保留数据启动。旧manifest/旧指南/旧原始结果保留，新run使用当前源码清单，旧run不静默升级。
