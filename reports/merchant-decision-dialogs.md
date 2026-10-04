# 商家处理弹窗实施与集中验证

2026-10-04，用户批准简化人工退款方案、补充说明、拒绝申请。沿用四区工单v4，[本批合同](../docs/merchant-decision-dialogs.md)定义UI及服务端准备范围。

共享 MerchantDecisionForm 展示商品图片/名称/规格/金额、18px表单及明确按钮。补充说明与拒绝均预览客户正文，拒绝保留结束提醒。人工方案默认系统检查与政策标题，其他场景的实际材料/政策选择折叠且仍须显式选择。App中待审授权的批准/补证/拒绝也复用同一商品表单；冻结原版本、授权、身份和协作凭证的写入逻辑保留。旧专员工作台材料选择兼容路径没有删除。

原弹窗遇到没有case_evidence时无法提交，却没有整理已存在的付款/履约记录。本批新增负责人可用的只读准备接口及 `use_order_facts=true`；仅自动准备绑定唯一未发货规则，使用真实 scoped 订单、付款、当前履约和原政策/金额校验。POST重新核对，拒绝混合客户端引用、金额变化与其他动作。ORDER_LINE原始事实、来源/版本/hash、新修订、人工方案、待审授权同事务保存；生成方案不会批准或退款，批准仍重新核对原未发货方案。没有绕过已消费/UNKNOWN/资金与协作门禁。

## 实际命令与结果

| 命令 | 实际结果 |
| --- | --- |
| `pnpm --dir web test` | 最终23文件182项通过，涵盖后台刷新仍提交原版本/授权/归属、真实准备/阻塞/旧版本/迟到/401、两种客户预览、其他材料显式选择。 |
| `pnpm --dir web build` | 最终类型检查及生产构建通过。 |
| Java21 `java/mvnw.cmd -f java/pom.xml -pl case-service -am -Dtest=ManualProposalApiTest,UnshippedRefundCheckTest,ReviewerOwnershipApiTest,ReviewDecisionApiTest -Dsurefire.failIfNoSpecifiedTests=false test` | 66项通过、0 skipped；测试数据库由Testcontainers隔离，生产记录不受影响。 |
| Java21同入口，`-Dtest=ManualProposalApiTest` | 随后新增两例核对中金额变化门禁，最终30项通过。与前38项不重叠合计68项；没有声称最后一次重跑全66/68。 |
| Case定点 `spotless:apply spotless:check` | 正则只匹配ManualRefundFacts、ManualProposalService、ReviewerWorkspaceService、ReviewerWorkspaceController、UnshippedRefundCheck、ManualProposalApiTest六文件，最后三文件再定点验证通过。 |
| `uv run --project agent --frozen pytest agent/tests/unit/test_contracts_core_routes.py -q` | 81项通过；Case路由70、OpenAPI、准备fixture、旧引用/新服务端模式条件同步。 |
| `uv run --project agent --frozen ruff check agent/tests/unit/test_contracts_core_routes.py`、`git diff --check` | 通过。 |
| `stop.ps1`后`start.ps1 -NoBrowser` | 最终JAR构建和全部九项健康通过；现有政策imported 0/skipped 3，使用原数据、真实Agent配置，未重建基础数据。 |
| 真实Gateway新接口，只读7项 | 本店READY/69900且响应符合新Schema；匿名401、他店404、买家/平台403、终态409、不存在404。见[HTTP证据](merchant-decision-dialogs/http-verification.json)。 |

后端检查包括预览不写材料/授权、人工提交可审但不执行、保存原始事实与正确canonical hash、引用指向同一材料、旧版本重提不重复写、批准时已发货拒绝、缺记录/占用金额/外主体/无绑定政策不产生方案、UNKNOWN禁止新方案、核对阶段金额竞争拒绝且材料/方案/授权均无新增。实际成功提交与状态推进使用隔离数据库；浏览器没有提交用户现有申请。

## 浏览器与数据

admin01现有办公显示器申请，三个弹窗1280×900：商品插画与信息可见，文字叶节点无小于18px字号、无横向溢出，短样例无需弹窗内部滚动；退款方案另核对1440/1680×900。长内容仍可在整张弹窗滚动，不宣称任意内容一屏。截图为真实页面：

- [退款方案](merchant-decision-dialogs/manual-refund.jpg)
- [补充说明与客户预览](merchant-decision-dialogs/request-info.jpg)
- [拒绝与结束提醒](merchant-decision-dialogs/reject.jpg)
- [字号/尺寸记录](merchant-decision-dialogs/browser-verification.json)

测试输入仅填草稿并关闭，没有发送客户问题、拒绝、人工方案、批准、购物或新调查。临时viewport已恢复。更新前后46业务表hash/行数一致，Agent4COMPLETED/15模型记录/10工具记录/8回调均不变；身份登录/协作元数据不在46表集合中。见[保留数据证据](merchant-decision-dialogs/data-preservation.json)。没有新付费模型调用。

## 修复过的初轮失败与未运行

最初主机默认Java不是21，切到现有JDK21。新增成功路径首次422：来源前缀manual-refund不符合受控引用格式，改为manual_refund后全部66项通过。金额竞争补测增加两例并加两处全额一致检查，最终人工方案30项通过。前端初轮金额格式断言误期望¥、一处按钮旧文案选择未同步，修正断言/选择后保留原冻结版本断言，最终182通过。契约初轮80过/1失败因为新GET未引用权威文档，补充后81通过。Spotless首次误用glob而非正则，后用定点正则通过。

运行中的Windows JAR不能被repackage重命名，首次单独package失败；按正式入口停止后重建并启动成功。重启触发网页重载，首次1440/1680测量时弹窗已消失，空测量没有算通过；重新登录打开真实弹窗后完成测量，正式证据只保留有效记录。

新增HTTP/数据报告JSON首次暂存检查发现Windows CRLF被判为尾空白；定点转换LF并重新解析JSON，最终暂存diff检查通过，未修改业务或其他报告。

未新跑模拟退款全链路、新Live质量评测、全仓Java/Python或移动端。Agent当前建议质量与自动工具选取本批未修改。既有工程说明、verify脚本、Commerce退款测试及历史草图/日志不属本批，保留且不夹带提交。后续由用户主导，不自动开启旧任务。
