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

## 部署与集中验证收口（2026-10-04）

`./stop.ps1`、`./start.ps1 -NoBrowser`成功重建并启动当前3个Java服务、真实调查配置Agent和网页；已有三店政策精确索引READY。没有清库、删除卷、重建样本或触发Live调查。`./status.ps1`最终9项健康通过，密钥没有输出到证据。

- `agent/.venv/Scripts/python.exe scripts/aftercare_ui_acceptance.py`：33项真实只读HTTP检查通过，[机器证据](aftercare-ui/http-verification.json)。现有buyer01三店工单的商品图片/名称/规格/数量/实付与本商家一致；其他买家/其他店铺（含伪造query）404、平台403、匿名/服务令牌401。已成功退款仍不能再申请；履约精确包含原工单行。本驱动只登录和读取，要求当前固定基础数据的三笔已结束申请，不是通用线上健康探针。
- 最终CSS及返回队列清理政策定位修复后，`pnpm --dir web test -- tests/app.spec.ts tests/customer-workspace.spec.ts tests/marketplace.spec.ts`：3文件39 passed；`pnpm --dir web build`成功。此前完整回归22文件162 passed；此次没有重跑未改的Java/Python测试，没有把39项说成重新跑过162项。新驱动Ruff check/format check、精确提交diff检查通过。
- [数据保留证据](aftercare-ui/data-preservation.json)：46业务表行数和全表hash与部署前一致，Agent仍3COMPLETED/12历史mock模型/9工具/6回调。identity、协作分派、Flyway表不在这46表hash范围内；本轮未修改账号或分派，没有新订单、申请、退款或模型调用。

实际浏览器截图：买家[列表](aftercare-ui/buyer-list.jpg)/[已完成详情](aftercare-ui/buyer-detail.jpg)，商家[列表](aftercare-ui/merchant-list.jpg)/[详情](aftercare-ui/merchant-detail.jpg)。商品插画沿用商城实际asset_key，UUID和原始日志默认收起；政策引用仍能打开绑定版本并将焦点移至所引条款，已结束工单没有审批按钮。浏览器发现并修正折叠入口12px、调查标题15px、空输入框13px及父样式覆盖按钮颜色的问题；取消商家详情嵌套滚动，返回列表清除上次政策定位。

现有三笔业务申请都已完成，为保留数据且不制造收费调查，申请/补证页使用真实CustomerWorkspace组件的临时合成状态预览，顶部明确标注“不写入业务”；所有HTTP请求被预览入口拒绝，没有生产认证绕过。[申请页](aftercare-ui/buyer-apply-preview.jpg)/[补证详情](aftercare-ui/buyer-waiting-preview.jpg)仅证明前端呈现，不能冒充新端到端业务操作。临时入口已删除，源夹具保留为[HTML](aftercare-ui/preview-fixture.html)/[TS](aftercare-ui/preview-fixture.ts)，复现时分别复制到web/tmp/aftercare-visual.html与aftercare-visual.ts，仅用于本地Vite；勿用于生产构建。

[浏览器原始测量](aftercare-ui/browser-verification.json)保留初轮失败及最终结果：初轮四个实际视图在1280/1440/1680无横向溢出；修正后申请/补证预览在三宽度及所有实际视图在1440检查了渲染叶节点与空表单控件字号，均无小于16px。创建临时标签后viewport能力绑定失效，后续请求1280/1680时实际业务标签仍1440，因此这些重复1440记录不算三宽度通过；最终实际业务页1280/1680的全字号复查未完成，不能宣称所有状态、所有宽度都已视觉通过。未测移动端；历史资料缺图明确“图片未提供”。此次不评估DeepSeek回答质量，运行样例的旧mock来源保持可见。

启动未就绪时第一个标签连接失败，另开成功业务标签继续；失败标签的data错误页受浏览器URL策略限制，未绕过。浏览器只读DOM不支持TreeWalker/parseFloat，改用元素集合和computed style测量；测量只对渲染叶节点和表单控件负责，不是逐字符排版证明。日志保留在忽略的tmp/project-startup/aftercare-{stop,start,final-web-tests,final-build}.log。
