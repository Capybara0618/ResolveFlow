# S3：实际工具进度与正文增量

2026-10-23，沿[目标协议](../../docs/customer-chat-stream-contract-v1.md)实施；下文工程测试不等于真实模型性能验收。

## S3a：限定进度入口与生成视图

- 新增独立support:progress凭据，绑定原run/conversation/input/dispatch fence/店/客户/行，不能读事实或进入退款；原support:read不能发进度。原ServiceTokenFilter按新路由匹配新scope，领域仍重新核验当前身份、版本、lease与fence。
- 追加V30临时视图/批次序号；短事务锁内应用有序增量，最后相同批次幂等返回、乱序/不同载荷/旧attempt拒绝。Python仅允许start/reset/delta和受控工具类别，不能伪造committed或退款；字符offset用Unicode码点，当前合计正文4000、批次16事件/16000字符、每fence最多500进度事件，保留终局容量。
- snapshot携当前运行生成视图，已过时/非RUNNING视图不可见；新dispatch fence清空旧临时视图/批次。临时正文不进入消息/分享/退款。身份失效或会话删除时已经建立的SSE正常关闭，避免试图在已提交SSE响应里写JSON错误。
- Java派发附独立progress_token，Python请求类型兼容可选SecretStr且从持久输入排除；本步先接收而不使用，生产仍原缓冲模型。OpenAPI同步内部路由/事件类型/可选凭据，共享fixture增加正文delta。

验证：关键凭据测试先编译失败（新API不存在）；实现后共享凭据2项通过，Case第一轮26通过/1失败，发现ServiceTokenFilter仍要求support:read；补路由匹配后27通过。添加总量上限和SSE关闭修正后确认轮Case27/共享2通过，0跳过，reactor53.365秒。契约/原OpenAPI106项通过（14.81秒）；最新fixture定向确认单列后续记录。限定相关Java格式检查通过。

实际命令：

```powershell
# JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1，cwd java
./mvnw.cmd -B -pl case-service -am '-Dtest=SupportApiTest,SupportCredentialTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./mvnw.cmd -B -pl shared-kernel,case-service '-DspotlessFiles=.*Support.*[.]java,.*JwtCodec[.]java,.*ServiceTokenFilter[.]java' spotless:apply spotless:check
# cwd root
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_support.py agent/tests/unit/test_contracts_support_agent.py agent/tests/unit/test_contracts_openapi.py -q
```

真实Provider新调用0，usage2011；使用Testcontainers临时MySQL，未启动原业务/数据库或清日常数据。后续S3b接Python真实模型观察器/实际工具事件，S3c接页面草稿reset/commit，之后才有限真实联调测速度。未完成链路不当已上线。

## S3b：Python模型/工具观察器

- 新派发有progress_token时，咨询模型使用StreamingLiveModelClient，原退款调查客户端和SDK单循环保持；manifest显式streaming并固定传输/投影/转发源码，不升级旧active run。独立token不入PG输入/manifest/日志。
- 真实非缓存工具调用开始/结束发送受控类别；理解、工具选择JSON不发正文。正文投影首段立即入队，后续约40字符或数据到达时80ms合并，结束flush；进度后台线程按16条有序批次发送，HTTP1秒超时、队列/事件有界，异常停止转发、不重发模型；收尾最多2秒drain。不承诺没有新token到来时强制定时flush。
- 旧attempt拒绝立即reset，新模型调用按step切attempt，完整决定仍经过原来源/任务/金额/导航/终止校验并只记一次usage；投影语法异常只撤候选，不丢掉完整响应的用量记录/原纠错机会。缓存结果/工具不伪造重新执行进度。
- 新单元红测缺模块collection失败，实现3通过；真实SDK+隔离PG+合成Provider SSE/进度HTTP测试确认理解→物流→错引用→一次修复成功，4模型/1工具账均COMPLETE，已完成run重放0新增HTTP/进度线程。原staged API一起6通过，真实模型调用0。
- 相关客服单元/传输/SDK/PG集中332通过（9.50秒、0跳过），Ruff及4源码strict mypy通过。第一次扩大收集因缺根PYTHONPATH报import scripts错误而未运行，补PYTHONPATH后上述332通过；两处测试长行及先前源码长行/导入排序已修正，不跳过断言。已有Starlette/anyio弃用提示单列，未升级锁。

实际命令（cwd agent，PYTHONIOENCODING=utf-8，PYTHONPATH=仓库根，RESOLVEFLOW_AGENT_DB=原本机PG）：

```powershell
$streamUnitFiles=Get-ChildItem tests/unit/test_support*.py | ForEach-Object FullName
.venv/Scripts/python.exe -m pytest @streamUnitFiles tests/unit/test_streaming_model.py tests/unit/test_live_model_client.py tests/integration/test_support_stream_runtime.py tests/integration/test_support_stream_socket.py tests/integration/test_support_staged_api.py -q
.venv/Scripts/python.exe -m ruff check src/resolveflow/support/progress.py src/resolveflow/support/service.py src/resolveflow/support/api.py src/resolveflow/support/engine.py tests/unit/test_support_progress.py tests/integration/test_support_stream_runtime.py
.venv/Scripts/python.exe -m mypy --strict --follow-imports=silent src/resolveflow/support/progress.py src/resolveflow/support/service.py src/resolveflow/support/api.py src/resolveflow/support/engine.py
```

S3a `efc3f37`已普通push核实；最新fixture定向契约19通过（8.37秒）。仅启动原PG供临时schema测试，public业务表不写/不清，收尾停原PG；原业务服务未起，无真实Provider消费，usage2011。前端尚未识别这批新kind，因此S3c接线后才具备完整产品路径。
