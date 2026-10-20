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
