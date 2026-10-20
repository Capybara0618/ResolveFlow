# 客服首场景：演示环境与设计验证

2026-10-20。用户授权接通物流模拟器、准备独立订单、细化首场景及双端预期图。实际进度仅维护在 [todo顶部](../../tasks/todo.md)。本报告记录证据，不将原型交互当作已实现的客服后台。

## 演示环境与样本

- 原有本地Compose项目`resolveflow-review-demo`只启动MySQL，保留数据卷。Commerce迁移前备份保存在忽略目录`tmp/customer-agent-design-v1/commerce-before-v16.sql`，未提交原始数据。
- 使用既有JDK21构建Commerce、Case及共享模块，`-DskipTests package`成功；本次是运行接线，不重复上一批28/146项的测试结论。
- 临时Java进程使用原演示端口、持久数据库和身份，明确关闭调查派发、MQ消费者/发布者、Outbox投递及退款执行/对账循环；Python Agent/worker未启动。
- Commerce正常Flyway启动到V16。付款、订单发布和商家首次发货走现有Case/Commerce接口；后续物流通过正式模拟器过程追加。
- [运行样本](runtime-samples.json)包含7笔新增模拟订单：A店在途/延迟/签收，B店丢失/未知/查询失败/签收。同一买家buyer01；订单行实付分别32900/12900分，商品与店铺名称取真实接口，不补造材料或结论。

## 实际核查

脚本`scripts/prepare_logistics_samples.py`完成一次准备及一次重放，始终共7个独立订单，没有二次创建；幂等键在请求前保存在忽略目录`tmp/logistics-samples-v1/state.json`。脚本不提交退款申请、不生成Case或触发模型。

运行核查：正常六例私有物流读取200，专用故障例503；故障关闭200、重新开启503（503→200→503），物流事实/version不因开关变化；故障只留在新建B-QUERYFAIL订单。buyer01列表看到两店全部7个订单；buyer02读取这些购买记录全部404；各商家读另一店的新订单全部404。

原记录保留核查：Commerce原5订单/5行/5账本/5退款槽/5物流/5事件的每行hash均仍在；新增后分别12/12/12/12/12/25。原4条退款操作及4条Case授权hash保持。真实Case表名为`aftersale_case`：首版核查误用不存在的case_record，修正后取得5条Case的后置见证并明确标记`case_witness_captured_after_purchase_preparation=true`；不声称拥有该表在购买前的完整逐行见证。准备路径未调用任何Case创建接口，调查派发关闭；后置见证在重放后保持。

实际命令：

```powershell
.\java\mvnw.cmd -f java/pom.xml -B -pl commerce-service,case-service -am -DskipTests package
.\agent\.venv\Scripts\python.exe scripts/prepare_logistics_samples.py
.\agent\.venv\Scripts\python.exe -m ruff check scripts/prepare_logistics_samples.py
```

MySQL启动、受保护的临时进程启动与故障/越权验证脚本保留在忽略目录`tmp/customer-agent-design-v1/`，不作为新的日常运行入口。源码现有日志可能包含控制台中文编码显示差异；样本JSON的Unicode已核对为正确中文，不修改原商品或交易快照。

## 后续设计与使用

物流迁移/样本可供后续真实评测使用；A-SIGNED/B-SIGNED的“客户未收到”只是接下来对话样例的客户陈述，不是已经创建的售后案件。A-DELAYED是异常延迟事件，不能称七天无扫描；外部原文评测材料不自动成为商家生效政策。

本轮不会自动运行真实模型或把设计文案记作实测回复；预期图中的咨询核查/确认申请/商家回复仍需要后续协议和功能实施。

## 首场景与双端预期图验证

新增[首场景规格](../../docs/customer-agent-scenario-v1.md)、[12个开发样例](../../evals/customer-agent-v1/dev-dialogues.json)及[双端图文约定](../../docs/ui-customer-agent-v1/README.md)。开发样例绑定上述7笔模拟订单，覆盖普通问询、已提供信息、政策插问、仅人工咨询、确认退款、签收争议、纠正/暂停、UNKNOWN/503、人工接续与跨店切换；尚未运行Agent，不能作为任务完成率或效果提升。

可交互原型共7个视图，配套7张截图。`scripts/check_customer_agent_preview.cjs`使用既有Playwright及已安装Edge：7视图×3种宽度=21项无横向溢出；14项原型交互通过，无JavaScript页面异常，详见[检查JSON](preview-check.json)。检查包含转交摘要修改/共享原文选择、接收方、商家回复/客户补充、退款待核验及商品上下文保持；不等于真实客服API验收。

开发中修正了原型函数与浏览器全局名称冲突、hash切换截图未更新及本地商品图片路径；Playwright默认浏览器未安装，使用既有Edge完成，无下载或新增依赖。1440px截图人工检查用户转交及商家详情，排版与信息分区正常。

补充摘要传递断言时，首次选择器同时命中主栏与侧栏导致strict mode失败，限定首个摘要元素后通过；脚本同时增加finally关闭浏览器。新增结构报告曾使用Windows CRLF触发差异空白检查，保存为LF后检查通过。

复现：在仓库根目录以可解析既有Playwright的Node执行`node scripts/check_customer_agent_preview.cjs`。本轮没有启动正式完整应用、Python Agent或付费模型，没有修改旧量化报告/Gold/简历；Agent质量、真实人工接续和退款新入口仍未运行。

[结构与来源检查](design-verification.json)：12个唯一开发样例均绑定现有7笔样本，公开页面字段逐项对照运行JSON，7张PNG尺寸/哈希与6份设计/脚本来源哈希已保存；检查92个本地Markdown链接可达。验证助手保存在忽略目录`tmp/customer-agent-design-v1/validate_design.py`。

收尾：通过演示进程归属记录分别停止`design-case`和`design-commerce`，确认两个端口均关闭、无所属临时Java进程；MySQL及新增/原有数据保留。首次关闭后的端口核查少传host参数导致TypeError，修正核查后通过，没有重新启动服务。原四个工程/验证历史改动与旧图/日志排除提交。
