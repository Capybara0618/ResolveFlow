# 售后简约改版 v3 实施证据（2026-10-03）

依据[图册与合同](../docs/ui-aftercare-v3/README.md)，五张图片是生成设计参考，不是运行证据。当前唯一实施者，不清库、不重建样本、不额外调用收费模型；原工程/verify/退款测试与旧草图/日志不夹带。

## 商品快照与受保护读取

新增Case `GET /api/v1/orders/lines/{line_id}`：身份来源于持久账号校验，平台买家逐可信店铺绑定查本人商品；商家按本店读，越界404。Commerce展示投影从PAID购物草稿取asset_key，SINGLE匹配精确SKU，MULTI匹配精确子行，订单/商家/客户全部一致才提供；历史无快照省略字段。未改变金额上下文、退款状态、写入协议或Agent工具。

实际命令（根目录，JAVA_HOME指向本机JDK21）：

- Maven关联六类：`java/mvnw.cmd -f java/pom.xml -pl commerce-service,case-service -am -Dtest=AftercareProductReadDatabaseTest,OrderLineReadServiceDatabaseTest,OrderApiTest,CommerceOrderLineClientTest,BuyerOrderServiceTest,PlatformBuyerApiTest -Dsurefire.failIfNoSpecifiedTests=false test`：Commerce15+Case30=45 passed，0 skipped。新路由先红（预期200实际404），实现后绿；新数据库测试验证改目录不改历史图、准确多行SKU、缺快照/主体不一致不造图、金额不变/越店不可见。
- `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py -q`：最终80 passed。首次79 passed/1 failed，新路由缺summary/权威文档引用，已补齐；没有删断言。Commerce/Case展示字段契约一致、历史fixture仍有效，路由表同步Case69条，展示图不进入资金LineContext。
- `agent/.venv/Scripts/ruff.exe check agent/tests/unit/test_contracts_core_routes.py`、`git diff --check`通过。定点Spotless apply成功；最初glob被当正则及含管道正则被cmd拆开两次失败，改成逐文件正则列表成功，未全仓格式化。

日志为忽略的tmp/project-startup/aftercare-{red,data-tests,contract-tests,format}.log。此批尚未重启运行JAR，真实HTTP/网页运行验证在双端UI完成后的集中批次进行；不以单元桩证明部署已更新。
