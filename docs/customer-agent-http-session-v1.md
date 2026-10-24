# 同run流式HTTP连接生命周期

2026-10-24，接续[首正文第一轮](../reports/customer-latency-close-live-v1/README.md)：复杂请求3次模型调用已真实采用，签收仍5.23秒、另一店丢失3.30秒，4秒目标1/2，不改该轮结果。

## 改动与边界

源码确认StreamingLiveModelClient._send每次构造并关闭httpx.Client，同run多次调用没有应用层连接池复用。新增request_session上下文，由SupportAgent.run在唯一SDK循环外拥有：该run全部供应商调用共用一个HTTP客户端，头部仍逐请求生成，响应仍逐请求关闭；成功、失败、异常退出均释放客户端并清空引用。

没有跨run/跨用户全局客户端，不改变请求次数、重试、超时、重定向禁用、trust_env=False、原usage/预算/fence/manifest。嵌套复用同模型实例明确拒绝，直接单次decide未进入session时保持原独立客户端语义。旧run代码manifest不兼容时仍拒绝换版本恢复。

这是移除重复建连的确定性开销，不保证供应商首token时间或4秒目标；请求已有Keep-Alive及服务端状态是否允许复用由HTTP库/供应商决定。先生命周期、异常/无重试、请求头及实际SDK测试，再有限真实确认，不把模拟Transport复用说成真实延迟改善。

## 本批确认

工程0供应商，usage2367保持。接下来同3输入新版本一次，总最多10新请求，连同前轮8次仍在本次服务端18上限内；页面最多12，总上限30。保留首轮目标失败和旧3/3质量，若第二轮未达也不自动追题。页面仍需用户开启本地浏览器控制，不能以后台持久化替代DOM。

命令和保护核对见[工程报告](../reports/customer-agent-http-session-v1/README.md)，当前状态仅tasks/todo.md顶部。
