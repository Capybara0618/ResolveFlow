# 核验衔接修复后的单样本真实验收

2026-10-24，用户授权实施确认原因/正常待核验调查/商家接续修复及完整链路验证。固定生产6d997d8，沿原DeepSeek Flash、AgentScope、RAG政策与预算；新合成329元耳机订单，由原模拟器追加LOST，不复用或重发上次失败题。

一次客服消息请求查物流并整理申请摘要→自动准备可编辑卡（只准备不建单）→客户编辑确认→同键/刷新同一Case→初始revision1的未核验确认原因→首个有效MANUAL_REVIEW建议且无可批准授权→商家从原材料区CONFIRMED核验→revision2调查得到有效REFUND→商家独立审批→Java模拟退款一次成功→买家原会话和原申请详情查看结果。

固定[plan](../reports/chat-refund-handoff-v1/live-v2/plan.json)与驱动SHA；至多一个客服turn、两个原Case调查run，原单run次数/时间/修正预算不变。无第二循环/强制工具路线，不重跑失败刷分；真实FAILED时保留并停止，不改库或手写退款方案。原订单/政策/旧失败/调用账保留，全局live_guard下finally记全部客服和Case模型attempt，含修正/失败/未知，原usage2076续计。

浏览器只访问真实Vue/Java/Python和真实Provider，无业务API替身。监听器在当前文档主动安装，避免之前hash跳转未触发addInitScript的漏采；采集DOM反馈/候选正文/终局和实际SSE事件。候选正文不等于最终发布，不做p50/p95或简历指标。所有读数、截图和原响应独立存live-v2，当前样本结果不外推整体准确率。

prepare复用既有创建订单/模拟付款发货/物流工具和只读基线，0模型请求；最终冻结两个新驱动及原准备helper SHA。正常start已加载V32与当前源码，不重建政策索引、不清库或删卷。
