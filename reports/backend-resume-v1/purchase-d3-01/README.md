# D3：买家订单列表批量读取

2026-10-26。第4/5条已按用户确认[冻结](../../../docs/resume-backend-trade-refund-frozen-20261026.md)，本步为第7条SQL/Redis的SQL部分，不修改个人PDF或已冻结三条Agent侧成绩。

## 实际结果

真实MySQL8.4/Flyway、原Java21服务实现、JDBC PreparedStatement执行点计量。固定时钟与确定UUID的70份合成购买：本店本买家64份，另一店同买家3份，本店另一买家3份；覆盖SINGLE/MULTI、每单1–3行、WAITING_PAYMENT/UNKNOWN付款/PAID/取消/逻辑到期/已关单到期、无草稿的历史订单、付款失败后最新尝试、不同退款汇总，所有主样本created_at相同用于游标边界。

| 页大小 | 每条件重复 | 优化前SQL/页 | 优化后SQL/页 | 减少 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 10 | 4 | 4 | 0% |
| 24 | 10 | 110 | 8 | 92.73% |
| 48 | 10 | 238 | 8 | 96.64% |

[完整离线汇总](summary.json)。30组优化前后完整DTO及next_cursor逐字段相等；每组优化后DTO也与保留的原详情入口独立算法比较。空页只有候选SQL一次。4/8/8是本混合夹具实测，非任意页恒定8；实现最多候选+七批SQL，页面组成不同可跳过空批。指标是业务PreparedStatement执行次数，不包括连接池会话设置、BEGIN/COMMIT或HTTP认证查询，不冒充接口p95或整个跨店页面总SQL。

Case保留原串行跨店归并：1/2/3店×1/24/48页×10次，全部商家及选定单店两种共180次逻辑读取，生产CommerceShoppingClient实际发出270次loopback HTTP，服务JWT由接收端校验。全店读取每店一次（1/2/3），选定店始终一次，与limit无关。HTTP接收端为空列表显式fixture、BuyerScopes为stub，因此只证明真实传输扇出/可信scope参数，不把这270次称真实Commerce/MySQL端到端正确性或延迟样本；真实数据语义由MySQL测试验证，原归并/游标绑定/任一分片失败整体失败另两测试通过。

## 实现与事务

[PurchaseReads](../../../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/PurchaseReads.java)保留候选ID查询、状态筛选、created_at/id顺序及limit+1游标，只将逐条read改为[PurchasePageReader](../../../java/commerce-service/src/main/java/com/resolveflow/commerce/catalog/PurchasePageReader.java)按页批量装配：草稿头、MULTI快照行、最新sequence付款尝试、已成功付款行映射、历史订单头及行、统一退款账本。各批均使用绑定的merchant/customer及候选ID，复用详情的付款映射、快照完整性与退款不变量检查；详情入口保留原权威查询。

整页显式readOnly/REPEATABLE_READ，同一now用于候选和到期展示；无Redis/提供方网络调用。测试把连接默认改为READ_COMMITTED，实际执行时逐次检查只读RR，并在候选已读后另一连接提交全额退款，当前页仍读原IN_PROGRESS，后续详情读新REFUNDED，证明未混合两个提交版本。多行快照数量不完整或已付款行映射缺失时整页失败，付款最新FAILED/UNKNOWN隐藏未发布order/line ID。篡改及恢复仅在自有Testcontainers测试夹具，原库/卷未操作。

8条实际SQL及绑定值的EXPLAIN ANALYZE已保留。候选UNION仍有派生表及排序，新批量读取使用已有scope/主键/外键及付款sequence索引；没有新增索引迁移或声称完全消除扫描。EXPLAIN来自小夹具，单条时间不作为吞吐/HTTP性能结论；大数据与正式P2仍需按原评测计划执行。

## 验证与失败记录

- 原版实际计量30组先保存baseline.json；第一轮3项中快照测试选的固定订单不在未过滤前48页，2通过/1失败，资金/投影未坏。改为PAID页覆盖全部已付样本后，baseline-verified.json再次保存30组；2项语义通过，SQL上界断言按预期失败（110/238>8），先失败再实施。
- 第一候选3项通过；补默认RC连接/RR检查、残缺快照/映射、最新FAILED后，Commerce购买/恢复/多行/履约/HTTP等7类49项全部通过/0跳过，53.448秒；另实际绑定SQL/EXPLAIN一项通过、Case真实HTTP及原归并3项通过。总计本步相关53检查，无全项目回归或新收费模型。
- 仅所涉文件Spotless通过。最早将根目录写入和Maven放同一java工作目录导致写入命令找不到Python；该次Maven未跑目标用例，不计成功。随后分工作目录执行。格式参数一次含管道被Windows批处理解释、一次glob不符合Spotless正则而失败，最终逗号分隔的正则明确限定文件；未格式化原四脏文件。
- package -Dmaven.test.skip=true构建成功，单独记录其不运行测试；候选Commerce JAR已只增保存tmp/backend-resume-candidates/purchase-d3-01/commerce.jar，hash见candidate-manifest，后续性能不拿会变化的target当冻结构建。D0优化前JAR保持。

实际命令：java目录下JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1，Maven用项目mvnw.cmd。

```powershell
./mvnw.cmd -B -pl commerce-service -am test '-Dtest=PurchaseBatchDatabaseTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dresolveflow.purchase.output=E:/Code/Agent+Backend/reports/backend-resume-v1/purchase-d3-01/baseline-verified.json'
./mvnw.cmd -B -pl commerce-service -am test '-Dtest=PurchaseBatchDatabaseTest,CheckoutPaymentDatabaseTest,MultiCheckoutDatabaseTest,CheckoutRecoveryDatabaseTest,ShoppingBatchDatabaseTest,CheckoutApiTest,FulfillmentDatabaseTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dresolveflow.purchase.output=E:/Code/Agent+Backend/reports/backend-resume-v1/purchase-d3-01/candidate-final.json'
./mvnw.cmd -B -pl commerce-service -am test '-Dtest=PurchaseBatchDatabaseTest#recordsActualPageStatementsAndExecutionPlans' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dresolveflow.purchase.plans=E:/Code/Agent+Backend/reports/backend-resume-v1/purchase-d3-01/explain-analyze.json'
./mvnw.cmd -B -pl case-service -am test '-Dtest=BuyerPurchaseHttpFanoutTest,BuyerPurchaseServiceTest' '-Dsurefire.failIfNoSpecifiedTests=false' '-Dresolveflow.purchase.fanout=E:/Code/Agent+Backend/reports/backend-resume-v1/purchase-d3-01/fanout.json'
./mvnw.cmd -B -pl commerce-service -am package '-Dmaven.test.skip=true'
# 根目录，输出只允许新文件名
agent/.venv/Scripts/python.exe reports/backend-resume-v1/purchase-d3-01/audit.py reports/backend-resume-v1/purchase-d3-01 tmp/purchase-d3-recomputed.json
```

[20文件原字节归档](evidence.tar.xz)、[文件/包hash及解压复算](archive-index.json)保留两次基线/两次候选、计划、实际HTTP扇出和前后源码；[基线manifest](baseline-manifest.json)/[候选manifest](candidate-manifest.json)关联源码/锁/JAR及实际命令日志hash与测试计数。完整解压到新tmp后重新运行离线审计，结果相等。原日志留tmp，数据库由Testcontainers退出回收，未启动原业务lab/MQ/Agent。没有密钥/令牌/数据库快照进入归档。

D3证明订单列表SQL不再逐单增长。第7条完整指标仍需D4工作台与Redis/Redisson双实例保护和正式数据规模下配对HTTP评测，不拿本页92.73%直接套工作台或缓存收益。
