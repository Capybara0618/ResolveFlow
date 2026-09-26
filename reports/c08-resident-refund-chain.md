# C08.2 真实服务模拟退款闭环（2026-09-26）

`scripts/e2e_resident_refund.py` 使用既有MySQL、PostgreSQL、RocketMQ容器和新构建的Case/Commerce JAR；每次创建全新已支付订单行及LOST物流记录，不清理/复用旧退款槽。Case打开工单并固定政策版本后，驱动以该run的Case凭证通过真实MCP stdio读物流，从PG READY索引按相同manifest进行dense检索，取实际观察的版本/hash与返回的政策规则组成显式mock脚本。随后启动常驻Agent（兼作模拟provider）；Case真实派发，AgentScope按脚本发起一次物流读取、一次政策检索并提出有引用的全行退款候选。Case复核为 `VALIDATED`，生成授权；demo reviewer经真实登录/审批API批准，Case/Commerce通过真实MQ及出站/收件箱完成模拟退款和结果回投。

根目录命令：`agent/.venv/Scripts/python.exe scripts/e2e_resident_refund.py`。首次运行 `20260926-212446` **PASSED（47.1秒）**，证明工单 `CLOSED_SUCCESS`、Commerce退款 `SUCCEEDED`。补全金额和幂等断言后，最新运行 `20260926-212632` **PASSED（46.7秒）**：新run `c66a5936-5490-51dc-81af-0813e53e7847`、行 `9212641`；Case方案 `VALIDATED`、授权1条且由人工批准，Case收到 `STARTED`/`PROPOSAL` 两条 `ACCEPTED`；Commerce仅1条成功退款2599分，账本 `paid=2599/refunded=2599/reserved=0`，同行退款槽 `CONSUMED`；provider同一operation `SUCCEEDED` 且请求尝试次数1。Case最后 `CLOSED_SUCCESS`。这次provider未注入UNKNOWN/丢响应故障，不以一次尝试推断所有故障路径。

验证：`agent/.venv/Scripts/python.exe -m ruff check scripts/e2e_resident_refund.py`、`-m py_compile scripts/e2e_resident_refund.py`、`git diff --check` 均通过。此步只增加联调驱动、工程命令和报告，未改生产逻辑；前一小步生产源码的全量Python为 **1055 passed / 9 skipped**，不写成此步重跑。Java JAR以 `java/mvnw.cmd -DskipTests -pl case-service,commerce-service -am package` 构建成功，未跑本步Java单元/Spotless或all-offline。原始日志、动态mock脚本和provider SQLite位于本机忽略的`tmp/c08-resident-refund/`，不提交；既有其他未跟踪数据库快照仍保留。

这是**显式mock模型**的完整业务接线验证，模型决策由脚本固定，不能证明H1自主选行动、live模型表现、C09崩溃恢复或C10 strict回放。政策预检与模拟模型使用同一个固定manifest/查询；运行中Case对政策哈希和金额另行重算。下一步先按C08/H1-H3清单审计还缺的证据与最小真实模型样本预算，再决定是否需要补观察持久性或新测试；不把mock闭环自动等同于整包验收。
