# 完整客服流式：前两轮真实记录

生产仍d4836e7；驱动a79b655。原v1收件人错误零模型调用已保留；本次原三条输入不变，明确选择助手。

`agent/.venv/Scripts/python.exe scripts/accept_support_stream_v1.py execute --directory reports/chat-stream-live-v2`：浏览器退出1，后台2/2回合SUCCEEDED，7次模型请求全部COMPLETE，usage2012→2019；退款/订单/物流/政策索引/原调查表hash均保持。不是整组三轮通过。

- 第一轮物流：点击后处理状态146ms、首候选正文4694ms、正式消息观察5488ms；真实SHIPMENT工具，草稿早于正式回答，最终一条正式消息/草稿清理。
- 第二轮政策：启动后204ms整页刷新，随后找不到会话入口30秒超时；页面App登录状态仅内存保存，刷新回登录，不是后台Agent失败。后台policy+guide成功并保存答复，正文/完成的浏览器计时缺失，不补造为通过。新会话订阅的网络观察也有刷新空窗。

[browser.json](browser.json)、[runtime-results.json](runtime-results.json)保持原文；已有输入不得重发刷分。后续v3重新登录只读确认第二轮已保存答复，只发送剩余第三条更正，并以真实fetch AbortController断开SSE验证同登录会话内的网络续接。v3新before快照和独立计划绑定本报告原结果SHA，不重算前两轮模型。

完整页面刷新需重新登录是当前已知体验限制，不能把SSE游标恢复说成已实现登录会话持久化。第一轮只是单样本耗时，未做30次p50/p95验收。
