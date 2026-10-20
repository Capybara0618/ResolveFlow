# 物流场景模拟器验证

2026-10-20。实现依据[开发计划与操作说明](../../docs/logistics-simulator.md)。验证对象为本地CLI、V16迁移/事务过程及Java物流读取故障；使用锁定依赖和隔离Testcontainers MySQL8.4。没有清理演示数据、写现有交易、启动日常业务栈或调用付费模型。

## 结果

| 验证 | 结果 |
| --- | --- |
| LogisticsSimulatorTest | 10通过，0失败/跳过；Flyway V1–V16真实MySQL执行 |
| FulfillmentDatabaseTest | 9通过，原首次发货/多行/资金约束回归 |
| MerchantTradeApiTest | 2通过，原商家履约API回归 |
| OrderLineShipmentControllerTest | 7通过，原私有物流HTTP读取回归 |
| Python契约/工具/CLI | 146通过，0失败/跳过，含CLI9项 |
| Java Spotless针对本步4个Java文件 | check通过 |
| Python Ruff check/format | 脚本及其测试通过 |
| CLI advance --help、差异/本地链接 | 完成，具体命令与计数见todo顶部 |

10个新增Java测试覆盖：签收及历史/金额/槽保持；延迟不是丢失及UNKNOWN恢复；请求重试/换载荷拒绝/旧版本；错商家/未发货/倒退时间；真实HTTP503与恢复且物流不变；并发同键只追加一次；多行不完整历史整批回滚及修复后原键成功；200事件上限及未来时间；后续进展后重放旧收据；Python CLI通过Docker/MySQL客户端真实执行、重试及独立观察时间只读。

CLI集成测试只在测试进程中将LocalMysql构造替换为已识别的隔离测试容器，执行的解析器、SQL构造、Docker客户端传输、输出及inspect均为正式代码。正常CLI仍保留演示Compose项目归属检查，不提供任意数据库/容器参数。没有将测试容器装作日常演示环境。

## 实际命令

在仓库根目录、JAVA_HOME指向既有JDK21：

```powershell
$env:JAVA_HOME='C:/Users/hjn/.jdks/jdk-21.0.12.1+1'
.\java\mvnw.cmd -f java/pom.xml -B -pl commerce-service -am '-Dtest=LogisticsSimulatorTest,FulfillmentDatabaseTest,MerchantTradeApiTest,OrderLineShipmentControllerTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
.\java\mvnw.cmd -f java/pom.xml -B -pl commerce-service -am '-DspotlessFiles=.*LogisticsSimulatorTest.java,.*ShipmentReadService.java,.*ShipmentRepository.java,.*ApiExceptionHandler.java' spotless:check
.\agent\.venv\Scripts\python.exe -m pytest agent/tests/unit/test_contracts_openapi.py agent/tests/unit/test_tool_catalog.py agent/tests/unit/test_tool_result_validation.py scripts/test_logistics_simulator.py -q
.\agent\.venv\Scripts\python.exe -m ruff check scripts/logistics_simulator.py scripts/test_logistics_simulator.py
.\agent\.venv\Scripts\python.exe -m ruff format --check scripts/logistics_simulator.py scripts/test_logistics_simulator.py
.\agent\.venv\Scripts\python.exe scripts/logistics_simulator.py advance --help
```

本地原始输出保留在忽略目录`tmp/logistics-simulator/`；`test-20261020-v2.log`为28项最终Java批次。测试源码与实现的hash见[文件清单](verification.json)。不提交包含测试容器环境和原始业务数据的完整日志。

## 失败与修正

- 首先执行6个新测试，确认因缺少simulate_logistics过程而失败（1断言失败、5错误），再实现。
- 首轮实现6项中4项因新发货事件与DB时钟轻微偏差触发时间拒绝；增加默认时间对齐到最后事件、最多允许1秒应用/DB偏差，显式未来/倒退时间仍拒绝。单项诊断通过后删除诊断打印。
- 2026-10-14集中批次原18项通过，后10项遇到数据库关闭/无法连接，保留失败输出，不计作通过。
- 2026-10-20独立10项中9通过，CLI集成测试使用Docker的publish筛选未找到按主机端口映射的容器；改为Testcontainers Docker API按实际publicPort定位。随后28项集中通过。
- 格式命令最初使用glob而Spotless参数需要regex；一次带竖线的regex又被Windows cmd解释。改用逗号分隔的简单regex后apply/check通过。Python首次新增测试import排序已由Ruff修复。

## 使用边界及未运行

代码和隔离验证完成，不表示日常Java进程/演示库已部署V16。使用前让Commerce正常构建启动并完成Flyway，旧Java进程需要更新后才会返回模拟503；本次没有启动Python worker或使用新场景重跑Agent/RAG质量实验。

整单推进而非拆包裹；DELIVERED/LOST终局不能回退。DELAYED是新异常事件，不等于长期无更新；inspect的observed-at只作参考时刻，不改变Agent/服务时钟。历史种子、已记录的调用/Case/revision及原量化结果不重写。

没有验证真实快递、公网部署、全系统虚拟时钟、故障时所有页面的视觉表现或整个退款系统全量回归。没有运行本次范围以外的历史测试套件。
