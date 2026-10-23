# S2：咨询事件与页面进度

2026-10-23，沿[开发方案](../../docs/customer-chat-refund-stream-v1.md)实施。事件不推进会话输入版本，不增加模型调用。

## S2a：事务事件账本

- 追加V29迁移，增加独立event_sequence及会话事件表。接收、领取、失效、失败/待重试及正式回答发布记录到同一个原业务事务；最终事件引用同一已持久message_id/文本/来源。旧fence不能写终局事件，不修改原模型循环。
- 每会话保留最近512条事件，写入时清理该会话超过24小时的事件；未活跃会话物理清理为惰性。旧游标恢复快照由S2b接入，尚未提供对外SSE或Python工具进度。
- 关键三测试先3 errors（表不存在）；实施后完整SupportApiTest 22通过，0失败/跳过，真实临时MySQL/Flyway迁移。验证发送与接收事件一起回滚、连续新输入失效旧turn、独立事件序号、一次正式回复/事件、原本人/商家隔离及无退款副作用。

实际命令（cwd java，JAVA_HOME=`C:/Users/hjn/.jdks/jdk-21.0.12.1+1`）：

```powershell
./mvnw.cmd -B -pl case-service -am '-Dtest=SupportApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
./mvnw.cmd -B -pl case-service '-DspotlessFiles=.*Support.*[.]java' spotless:apply spotless:check
```

测试22项33.89秒，reactor总50.370秒；限定Support文件格式检查通过。初次PowerShell未完整引用`-Dsurefire.failIfNoSpecifiedTests=false`导致生命周期参数错误，未运行测试，修正引用后执行红绿测试。格式文件参数先误用glob、再含管道被cmd拆分，两次失败均未改文件；改为不含shell元字符的正则后通过。

无真实Provider请求，usage仍2011；生产项目和原数据库未启动，测试仅使用Testcontainers临时库，未清理日常数据。网页订阅、工具进度、正文增量与聊天退款尚未交付。
