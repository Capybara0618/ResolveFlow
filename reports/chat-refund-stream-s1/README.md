# S1：Provider增量传输与正文投影

2026-10-23；按[开发方案](../../docs/customer-chat-refund-stream-v1.md)分步实现。当前生产入口仍用原缓冲客户端，本报告不是网页流式验收。

## S1a：Provider SSE客户端

- 新增独立`StreamingLiveModelClient`，复用原`LiveModelClient`的请求构造、上限、错误分类、一次请求记录及最终ModelReply/usage解析；显式`stream:true`/`include_usage:true`，没有额外总结调用或重试。SDK接口和默认部署未改。
- 严格增量UTF-8/SSE解析，支持CR/LF/CRLF跨块、注释、多行data；忽略reasoning字段，正文片段回调发生在读取下一网络片段之前。保存首content/完成时间、片段数与字符数；这是内部JSON的首片段，不是用户首正文指标。
- 支持DeepSeek同一finish块携usage及兼容空choices usage尾块；无usage沿用估算。无finish/[DONE]、断流、错误JSON/UTF-8、过大事件/响应及观察器异常失败，不生成可复用的完整结果；已发送尝试仍记录一次。
- 先增加测试，模块不存在时collection失败1；实现后26通过。增加CR-only及时性用例后曾1失败/28通过，修正CR立即分行及跨块LF去重后29通过。原缓冲客户端测试包含在29项内。

实际命令（cwd `agent`）：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_streaming_model.py tests/unit/test_live_model_client.py -q
.venv/Scripts/python.exe -m ruff check src/resolveflow/harness/streaming_model.py tests/unit/test_streaming_model.py
.venv/Scripts/python.exe -m mypy --strict --follow-imports=silent src/resolveflow/harness/streaming_model.py
```

结果：29 passed in 1.42s；Ruff及1源码strict mypy通过。全是合成HTTP流，真实请求0、累计usage保持2011，无数据库/Java/网页业务启动。尚未测供应商TTFT、浏览器首正文或退款建单。

官方协议在本次开发中直接核验：[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)，`stream`/`stream_options`及响应delta；实际供应商互通仍待有限真实验证。
