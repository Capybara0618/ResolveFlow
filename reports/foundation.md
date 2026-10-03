# 干净演示基础管理集中验收

2026-10-03，按用户确认的[规格](../docs/demo-foundation.md)实施；初始化是合成数据，本地支付/发货/退款均模拟。历史环境数据清理由本轮用户明确授权，范围仅resolveflow-review-demo。

## 身份、管理与契约

新增独立PLATFORM_ADMIN，无商家/客户/买家声明，不能进入业务读取或审批。Case V25、Commerce V15只追加；平台维护商家及买家、短事务记录审计、跨库目录同步在事务外按版本可重试。商家管理员通过可信本店身份管理商品，Commerce管理凭证只允许case-service，Agent不能调用。商品/SKU不能迁移归属或硬删除，改价拒绝旧报价并保留已创建草稿/已付订单快照。

关键失败测试先行：共享身份测试初次因角色不存在失败，接入后身份/JWT17项通过；新增平台与商品集成测试分别3/4项，沿用人员11项、两服务交易5/2项，共管理批26项通过/0跳过。第一次联合运行中旧交易测试因新增测试遗留身份绑定而失败，新增测试增加清理，旧断言保留，联合复测通过。

实际Java命令（会话JAVA_HOME指向本机JDK21）：`java/mvnw.cmd -f java/pom.xml -pl case-service,commerce-service -am test -Dtest=PlatformAdminIdentityTest,CatalogManagementTest,PlatformManagementApiTest,StaffAdminApiTest,MerchantTradeApiTest -Dsurefire.failIfNoSpecifiedTests=false -Dspotless.skip=true`。定点格式化19个本轮文件通过，不改旧未提交退款测试。补充格式化后的复测遗漏人员测试选择名，其余15项通过；人员11项为前一次有效结果，没有把未选择项报成复测。

Case/Commerce core OpenAPI现在68/30条，Agent仍7条；16条新增管理接口、共享类型和fixture同步，outdoor及独立平台身份同步。`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_contracts_foundation.py agent/tests/unit/test_contracts_core_routes.py agent/tests/unit/test_contracts_platform_buyer.py agent/tests/unit/test_contracts_cart_checkout.py agent/tests/unit/test_contracts_checkout_payment.py -q`：112通过。初次生成的YAML共享锚点、security位置和oneOf嵌套错误在写入或协议验证中发现并修正，没有删旧契约断言。

本机默认Java17导致一次额外Maven命令被版本门禁拒绝，改用已锁JDK21后复测通过；PowerShell含点的-D参数需加引号，否则一次被解析为错误phase。构建时旧应用锁住JAR，停止所属进程后package成功。

## 网页与初始化

平台有商家、买家工作台；商家新增商品管理；商城补户外分类及本地SVG商品插画。`pnpm --dir web test`：21文件153通过；`pnpm --dir web build`：vue-tsc/Vite通过。新增回归覆盖编辑冲突保留输入、平台入口不加载售后队列。首次新增测试使用get().exists造成TS拒绝，按find().exists修正；Vue代理行用展开复制而非structuredClone。

`agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_demo_foundation.py agent/tests/unit/test_reviewer_demo_driver.py -q`：29通过，覆盖未授权/共享端口/路径越界/备份失败不清理和固定基准。

首次`demo.ps1 reset -ClearDemoData -SkipBuild`完成备份和清理后因Windows命令行长度失败；SQL改为docker exec -i标准输入，复测重建成功。原旧记录备份保留在`tmp/reviewer-demo/backups/20261003-104641-179070`；后续验收重建另存备份，不替代原备份。清理保留Flyway迁移历史，检查项目/端口/容器标签，重建所属临时broker，PG重新导入三店政策及真实索引；共享项目、代码、Git、历史报告和原未提交文件保留。

## 真实HTTP购物退款批

集中驱动为`scripts/foundation_acceptance.py`，只在空白固定环境运行，真实HTTP登录20账号、越权、创建/启停/重置、商品改价及三店新购买/工单/指定run/人工审批/账本验证。Agent采用生产AgentScope与真实MCP、PG dense政策检索，模型决策用明确mock，未启收费Live，不扫历史队列。

驱动联调已纠正三处预期：创建单SKU草稿实际200而非201；政策top_k最大5；RunWorker.finish先CALLBACK_PENDING、Java接受后才COMPLETED。保留最终持久状态断言，不将异步中间状态改成终态。最终结果与清空基准尚在接续，当前不宣称该全链批完成。

新商家只支持平台受控开通；政策仍需受控导入/索引，页面显示待准备。platform的policy_ready只是已导入当前政策，索引状态由商家既有“政策与版本”页核对。未实现公开入驻申请/审批、自助政策发布、真实支付、库存或移动端；本轮mock不是新的Live质量评测。
