# 买家客服停机提示验收（2026-10-30）

## 问题与实现

Agent 未启动时，SupportAgentTurns 将连接失败/5xx不断回排 PENDING；既有 deadline 没有在领取前终止，且前端 SSE 状态合并丢弃 reason，造成一直“正在准备查看”。连接错误和5xx现结束为 FAILED/ASSISTANT_UNAVAILABLE，消息保留、允许买家重新发送；HTTP409仍在同一 run/deadline 内重试，过期队列或重试明确 ASSISTANT_TIMEOUT，不重置期限。通用运行错误结束为失败，版本与 fence 检查保持。SSE携带并保留失败原因；页面用买家语言提示，不暴露异常细节。

## 验证

- 新后端3例先红：连接拒绝/503实际PENDING，过期队列仍调用Agent。修正后 `JAVA_HOME=JDK21; ./java/mvnw.cmd -f java/pom.xml -B -pl case-service -am -Dtest=SupportApiTest,SupportBuyerViewApiTest,SupportRefundApiTest -Dsurefire.failIfNoSpecifiedTests=false test`：124项通过，隔离MySQL，未调用模型。
- `pnpm --dir web test -- tests/support-workspace.spec.ts tests/support-events.spec.ts`：40项通过。前端提示回归先红；首轮新增测试选择器/fixture输入版本不符导致2例失败，修正测试后通过。
- `pnpm --dir web build`：类型检查/构建通过。两个Java文件定向Spotless格式化通过。
- 受归属脚本停止/重建/重启Case；Agent8182保持无监听。买家01原机械键盘咨询新增一句“请再帮我查一下物流。”，实机发送到可见停机提示约407ms，等待元素0。刷新仍保留2条买家消息和失败提示；填入文字后发送可用，清空验收草稿。
- 原14:45队列已过10分钟排队期限，重启后显示已停止等待，不继续自动重试。未修改原消息/订单/退款；本步新增1条验收消息，模型请求0。
- 截图：`tmp/buyer-reviews-20261030/assistant-offline.png`。原始命令输出在忽略目录 `tmp/support-offline-*.log`。

## 边界

本次验证服务关闭、503、过期队列和既有正常/流式/退款确认回归；不是新一轮真实模型质量评测。正在执行但响应慢仍按原120秒任务期限及130秒HTTP读超时收口，连接建立超时3秒；没有把正常模型等待缩短为停机失败。三Java/前端保持运行，Agent/PG未启动，完整启动的55433端口冲突未在本步处理。保留原4个无关脏文件。
