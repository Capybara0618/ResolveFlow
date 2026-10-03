# 第四批前置：多行退款资金规则

2026-10-03。本子步完成多行资格、复核/审批与并发结算的资金前置，购物车/多行报价及支付发布尚未实现，不宣称第四批完成。正式规格见[按店购物车与多行结算](../docs/cart-multiline-checkout.md)，沿用批准的M05/M06路线；不重做前三批、AgentScope循环或旧迁移。

## 修正与覆盖

原Case用本行实付减整单已退/预留，导致一行已退后另一行被误拒；当前Commerce LineContext追加实际order_paid_amount和本行line_refund_state，Case统一计算FREE行的原实付与整单剩余额度的较小值，已占用/已消费或缺失新事实不放行。客户资格、方案复核与审批都调用同一方法。旧响应同时缺新字段时保留旧保守算法，14参数测试/旧类型构造仍兼容。原金额字段保持整单含义，旧兼容模型/Schema与断言保留。

退款只读视图新增实际整单实付及本行已退/预留。本行金额按真实槽与整行全额约束投影，Agent P2区分本行与整单金额，保留来源/版本/hash；新增事实缺失不能回退为其他行金额，也不产生新的模型运行或权限。

还修复真实并发结算失败：原事务读取非终态后等待，另一请求先完成，本请求继续更新会抛状态冲突。现在先锁共享整单账本，再对原operation锁定当前读，已终态直接返回；与退款接受的账本→本行顺序统一，不重复扣钱/发结果。UNKNOWN继续原占用，确定失败释放原预留；provider不进入资金事务。

新增隔离MySQL测试使用专用两行32900/39800分，合计72700分，验证另一行已退后当前FREE行原金额与两行最终全退、UNKNOWN/确定失败释放/新授权重试、两行并发预留及16个重复结算恰好两事件、低于两行合计的整单资金拒绝且不留半预留。自身夹具仅在可丢弃Testcontainers按独立商家清理，原演示库未创建/结算退款。Case新增HTTP资格、方案VALIDATED/2599分、人工APPROVED及占用后409/授权不消费的完整入口回归；客户端同时核对整单限额、缺槽/缺整单事实及旧响应。

## 实际命令与结果

```powershell
# JAVA_HOME=C:/Users/hjn/.jdks/jdk-21.0.12.1+1
./java/mvnw.cmd -f java/pom.xml -pl commerce-service,case-service -am '-Dtest=MultiLineRefundDatabaseTest,CommerceOrderLineClientTest,OrderLineContextControllerTest,OrderLineRefundStatusControllerTest,OrderLineReadServiceDatabaseTest,CheckoutPaymentDatabaseTest,ProposalReCheckApiTest,ReviewDecisionApiTest,CustomerWorkspaceApiTest' '-Dsurefire.failIfNoSpecifiedTests=false' test
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_multiline_money.py agent/tests/unit/test_context_builder.py agent/tests/unit/test_context_facts.py agent/tests/unit/test_context_scenarios.py agent/tests/unit/test_contracts_core_schemas.py agent/tests/unit/test_contracts_core_corpus.py -q
agent/.venv/Scripts/python.exe -m ruff check agent/src/resolveflow/harness/context.py agent/tests/unit/test_contracts_multiline_money.py scripts/multiline_money_acceptance.py
```

Java9类90 passed/0 skipped（Commerce39，Case51），Python152 passed；补强“只提供槽却缺整单金额”拒绝后Case四类51和同六文件Python152复测通过。定点Spotless apply与Ruff通过，完整源/类型编译随Maven通过；未修改前端，不重复跑前端测试或绘制新图。协议新fixture五份见[multiline-money.json](../contracts/core/fixtures/multiline-money.json)，旧fixture继续验证。

失败与修复：首轮新Java4项有效RED：缺orderPaidAmount 1断言失败、重复并发结算1异常；2项成功用于保护UNKNOWN/资金上限。首轮Python新回归调用extract_facts参数顺序错误，2 failed/126 passed，按现有签名修正后128通过；拓展既有事实/场景后152通过。Ruff1处行长已修正，无删除断言。原始日志在忽略tmp/multiline-*，未提交凭据、原快照或敏感日志。

## 保留数据部署与边界

只读验收驱动见[multiline_money_acceptance.py](../scripts/multiline_money_acceptance.py)：实际执行snapshot→`demo.ps1 stop`→`demo.ps1 -NoBrowser`重新构建3JAR→verify，12项真实HTTP只读检查通过（原7001/7002及第三批两行的context/refund-status/客户资格），新字段/核心schema/本行状态金额/整单上限一致，第三批两行仍可申请。无新申请/退款/付款/provider/模型调用，演示保持5174、Agent只读。结果见[verification.json](multiline-refunds/verification.json)。

原34工单、5归属、34政策绑定、6政策、17授权、9退款操作、38支付账本、38订单、14账号、6草稿、38退款槽及92run/预算按完整只读快照逐条不变。原快照只在忽略tmp，公开报告仅保留各组行数/一致性hash与合成行ID；没有清库、删卷、改密钥或迁移历史修改。本子步没有新迁移。

未运行：购物车/多商品下单与付款、商家模拟发货、新购物未发货/当日政策、完整新购物退款链和收费模型。本子步不新增资金或物流状态，不将PAID假装成未发货/已签收，也不修改已有run预算/fence。后续接本规格的购物车和不可变多行草稿，再原子发布多个行/槽；不能绕过资金前置或继续使用旧整单未退假设。历史工程/verify/Commerce退款测试/未定稿图片/日志保留，不夹带本提交。

收口检查：实际只读Python检查通过上述规格/README/报告的73个本地链接、12项HTTP与所有保护组不变断言，确认验收驱动依赖已经跟踪；git diff --check通过。账本与交接只更新顶部保留历史。本子步精确commit后正常推送origin/main，SHA及远端确认见交接消息。
