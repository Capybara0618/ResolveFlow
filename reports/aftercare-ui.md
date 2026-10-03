# 售后简约改版 v3 实施证据（2026-10-03）

依据[图册与合同](../docs/ui-aftercare-v3/README.md)，五张图片是生成设计参考，不是运行证据。当前唯一实施者，不清库、不重建样本、不额外调用收费模型；原工程/verify/退款测试与旧草图/日志不夹带。

## 商品快照与受保护读取

新增Case `GET /api/v1/orders/lines/{line_id}`：身份来源于持久账号校验，平台买家逐可信店铺绑定查本人商品；商家按本店读，越界404。Commerce展示投影从PAID购物草稿取asset_key，SINGLE匹配精确SKU，MULTI匹配精确子行，订单/商家/客户全部一致才提供；历史无快照省略字段。未改变金额上下文、退款状态、写入协议或Agent工具。

实际命令（根目录，JAVA_HOME指向本机JDK21）：

- Maven关联六类：`java/mvnw.cmd -f java/pom.xml -pl commerce-service,case-service -am -Dtest=AftercareProductReadDatabaseTest,OrderLineReadServiceDatabaseTest,OrderApiTest,CommerceOrderLineClientTest,BuyerOrderServiceTest,PlatformBuyerApiTest -Dsurefire.failIfNoSpecifiedTests=false test`：Commerce15+Case30=45 passed，0 skipped。新路由先红（预期200实际404），实现后绿；新数据库测试验证改目录不改历史图、准确多行SKU、缺快照/主体不一致不造图、金额不变/越店不可见。
- `agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_core_routes.py -q`：最终80 passed。首次79 passed/1 failed，新路由缺summary/权威文档引用，已补齐；没有删断言。Commerce/Case展示字段契约一致、历史fixture仍有效，路由表同步Case69条，展示图不进入资金LineContext。
- `agent/.venv/Scripts/ruff.exe check agent/tests/unit/test_contracts_core_routes.py`、`git diff --check`通过。定点Spotless apply成功；最初glob被当正则及含管道正则被cmd拆开两次失败，改成逐文件正则列表成功，未全仓格式化。

日志为忽略的tmp/project-startup/aftercare-{red,data-tests,contract-tests,format}.log。此批尚未重启运行JAR，真实HTTP/网页运行验证在双端UI完成后的集中批次进行；不以单元桩证明部署已更新。

## 买家售后批次

共享AftercareProduct展示真实下单插画/名称/规格/数量/本行实付；缺图明确缺失。独立商品缓存按line_id精确匹配、最多四路并发、跨会话迟到响应丢弃、故障可重试且申请继续可读。商城导航类名恢复并高亮售后，平台买家取消重复侧栏。买家列表改商品卡片，申请左右表单/金额，详情状态/商品/原申请/当前问题直接可见，历史问答/全部轨迹/编号折叠。保留写入幂等冻结、补证期限、UNKNOWN只读、材料待核对与撤销门禁。

`pnpm --dir web test -- tests/aftercare-products.spec.ts tests/customer-workspace.spec.ts tests/marketplace.spec.ts`：21 passed；`pnpm --dir web build`通过。新增缓存并发/身份隔离/错误商品/重试测试，原10项申请/补证/撤销回归未删断言。运行浏览器和各桌面尺寸仍待双端集中验证。上批新JSON fixture首次cached diff因Windows CRLF报尾随空白，但当时shell未停止仍提交；本批已统一LF，重新diff check通过，无协议内容更改；后续提交门禁失败立即停止。

## 商家售后批次

单商家工单卡片列表与详情分离，登录/筛选不自动打开首单；详情商品摘要、原申请/材料、关键政策引用与审批可见，完整轨迹、调查工具原记录、政策解释/编号默认收起。模型mock/live来源仍可见，冲突/缺资料/旧建议/UNKNOWN及人工方案保留。新增受保护商家履约读取，无法读取明确缺失，不编造发货状态。返回列表清理工单上下文/协作和事件流，迟到订单响应不得覆盖下一工单；缓存登录/退出清空。样式按16px正文及两栏桌面规则，实际浏览器待部署核验。

`pnpm --dir web test`最终22文件162 passed；`pnpm --dir web build`通过。新增买家商品读取失败独立重试、商家列表/详情和旧响应隔离；六种三角色审批仍验证冻结时的工单/授权/协作版本，不删除原安全断言。集中初轮158/160通过，旧表格选择器和申请标题与新布局不一致；更新卡片选择器、恢复申请标题/可展开旧订单记录后159/160通过，发现Vue布尔props省略时默认false导致实付隐藏，显式默认true修复后160/160，再加入两个场景至162/162。未以仅build冒充回归通过。

部署前保存tmp/project-startup/aftercare-before.json：46业务表hash/计数，Agent3COMPLETED、12历史mock模型/9工具/6回调，下一集中部署/只读验证保留这些记录。
