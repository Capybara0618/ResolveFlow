# 客服双端界面 v2 实施证据

2026-10-20。按用户已接受的[双端预期图](../../docs/ui-customer-agent-v2/README.md)实施，唯一进度在[todo顶部](../../tasks/todo.md)。保留现有Support协议、请求幂等、输入版本与共享边界；没有因图片里的附件/计数新增后端能力。

## 来源与上下文组件

提取support-view与SupportContext，回答引用改为逐条展开，支持紧凑标签。商家只使用ticket.report和客户选定原文，不读取私有助手回答作新报告；客户编辑的ticket.summary是核查诉求，不把旧handoff_summary冒充确认后的建议。物流展示保存的引用/版本与回答时间，缺记录明确留空，不假称实时查询成功。来源全文保持可展开，未更改服务端协议。

新3项覆盖商家使用确认快照而非更新私有内容、缺共享材料不造事实、物流事件排序与UNKNOWN保留。首轮签收措辞断言红测后实现“记录显示已签收”；`vitest run tests/support-context.spec.ts tests/support-workspace.spec.ts tests/support-client.spec.ts`共13项通过，`vue-tsc --noEmit`通过。本步骤只改组件和呈现函数，主布局接入在后续独立步完成；未启动业务服务或调用模型。
