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

## S1b：正文增量投影与实际本地HTTP验证

- 新增独立`AnswerProjection`：按JSON结构只提取根`ANSWER_PARTS.parts[].text`，不会把工具参数、理解阶段、reasoning或嵌套同名text当正文。kind在后时先有界缓存；解码转义、分片Unicode和代理对；每段增量含稳定part索引与offset（Unicode码点，浏览器后续不能直接用UTF-16索引去截取）。
- 占位符左/右花括号、金额符号或数字出现后，该part尾部暂留给终局来源填充。此处是候选正文投影，不是来源审核器；物流状态、政策适用性等仍须S3接入既有来源/发布校验，不能将投影直接当已审核消息或启用退款卡片。
- 原文总长、嵌套深度、parts索引和每段text长度有上限；重复key、错误/半截JSON、无效转义或孤立代理对会终止该投影。上一批已显示的候选内容须由S3按attempt reset/failed清除，不能凭`finish()`落库。
- 新增真实loopback HTTP测试：服务端flush首段后等待客户端首正文，再发tail和[DONE]；客户端在tail之前已获得正文，最后只返回一次完整ModelReply并按usage结算。这个测试未访问真实模型，也未使用人为打字延时。
- 先加测试得到模块缺失1collection失败；实现后1失败/17通过，发现测试把六个中文字符的offset误写7，改为实际len后通过，并补单字符分片/上限/本地socket测试。

实际命令（cwd `agent`，`PYTHONIOENCODING=utf-8`）：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/test_support_stream_projection.py tests/unit/test_streaming_model.py tests/unit/test_live_model_client.py tests/integration/test_support_stream_socket.py -q
.venv/Scripts/python.exe -m ruff check src/resolveflow/support/stream_projection.py tests/unit/test_support_stream_projection.py tests/integration/test_support_stream_socket.py
.venv/Scripts/python.exe -m mypy --strict --follow-imports=silent src/resolveflow/support/stream_projection.py src/resolveflow/harness/streaming_model.py
```

结果：52 passed in 2.16s；相关Ruff与2源码strict mypy通过。S1隔离机制完成；S2持久事件/SSE及S3生产正文转发尚未接入，R1–R3聊天退款仍未实施。尚不能声称页面流式可用或性能目标达标。真实新调用0，usage2011；原项目/数据库保持停止，静态预期稿服务保留。

S1a已提交`a79ae21`并普通push到原`origin/main`，远端SHA已核实；本小步同样独立提交推送，不改历史失败、旧评测原文/清单或原四脏文件。
