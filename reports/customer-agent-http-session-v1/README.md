# 同run HTTP连接复用工程

2026-10-24，接续已同步的dc8d338首轮真实结果，实施[连接生命周期说明](../../docs/customer-agent-http-session-v1.md)。保持原模型/SDK/协议/取证与预算，仅在SupportAgent.run范围内复用HTTP客户端。

新增request_session，run成功/失败/异常后关闭；每个响应仍独立关闭、请求头逐次生成，禁止同实例嵌套。单次decide和其他调用方未进入session时仍按原方式独立构造客户端。不设跨run全局池，不增加供应商自动重试。

验证：新增5生命周期测试先5失败，随后与原streaming/live model及evidence batch共44通过。扩大到全部客服/两个合同/streaming/live及session，540通过0跳过；PG七文件17通过0跳过。两生产源码strict mypy、两源码一测试Ruff通过（首次行宽和导入已整理）。[red.txt](red.txt)、[targeted.txt](targeted.txt)、[unit.txt](unit.txt)、[runtime.txt](runtime.txt)、[static.txt](static.txt)。

测试跟踪Transport确认两次供应商发送之间未关闭、退出仅关闭一次；请求头API key变化仍按本次值发送；非法流不自动重试且关闭；SDK三调用共用生命周期，协议失败也关闭。PG/API原恢复、fence、预算及流式结果保持。这里证明客户端生命周期，不冒充真实TLS复用率或耗时下降。

工程0供应商请求，usage2367，[保护审计](audit.json)核对公共11表、188历史报告及四历史脏文件。PG仍仅用于下一版有限确认，未启动Java/Web或创建Case/退款；原首轮5.23秒未修改。下一版同3输入最多10请求（本任务服务端总上限18剩余10），各题一次，另页面≤12，总≤30，不以失败反复追加。
