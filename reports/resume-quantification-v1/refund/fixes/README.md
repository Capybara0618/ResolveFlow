# 正式退款矩阵前的通用修复

2026-10-07 的代表故障接线发现两个实际问题：

- 相同批准操作以不同事件 ID 并发接受，初次普通查询都未见操作，等待账本锁后仍按旧快照判断行占用，给同一操作发出错误失败结果。现在取得账本锁后用 `findForUpdate` 当前读识别已提交操作并返回原预留；锁顺序与结算沿用账本→操作。
- provider 已接收请求后关闭连接，Spring 读取响应头时将 SocketException 包成 RestClientException，原先仅捕获 ResourceAccessException，导致未进入 UNKNOWN。现在额外识别有 IOException 根因的响应读取错误；仍保留占用、查询原操作。其他非传输异常继续原有行为。

先复现再实现：新增确定性十线程测试在真实 MySQL 查询账本前用屏障确保全部经过首次未命中，修复前出现同行占用拒绝；新增真实 HTTP 服务接收请求后直接断连，修复前出现读取响应异常。首次并发测试的 MyBatis spy 不能直接 callRealMethod，改为事务绑定的 SqlSessionTemplate 真实 Mapper 后才得到领域反例。

最终集中测试 `MultiLineRefundDatabaseTest,RefundProviderTransportTest,RefundDispatchApiTest,RefundCommandConsumerApiTest`：**28 项通过，0 失败/错误/跳过**。覆盖同操作十并发、跨行资金及重复结算、真实独立模拟provider、MQ消费领域逻辑。此处不把测试通过数当成正式60次真实MQ故障成绩。

```powershell
java/mvnw.cmd -f java/pom.xml -pl commerce-service -am '-Dtest=MultiLineRefundDatabaseTest,RefundProviderTransportTest,RefundDispatchApiTest,RefundCommandConsumerApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
java/mvnw.cmd -f java/pom.xml -pl commerce-service -am -DskipTests package
```

Sanitized JUnit 数量和相关源码 SHA 在 [verification.json](verification.json)。开发失败日志位于本地 `tmp/resume-refund-concurrent-red.log`、`tmp/resume-refund-concurrent-red2.log`、`tmp/resume-provider-transport-red.log`；通过日志为 `tmp/resume-refund-green.log`。已有用户修改的 `RefundAcceptanceApiTest.java` 未修改或提交。
