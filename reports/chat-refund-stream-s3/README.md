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
