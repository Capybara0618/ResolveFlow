# Harness/上下文正式执行边界 v1

2026-10-26，在[原协议](customer-harness-context-v1.md)和[真实进程接线](customer-harness-context-wiring-v1.md)之上补正式模型入口。当前进度仍在tasks/todo.md顶部，本文件固定运行边界，不是新效果报告。

## 范围与上限

64上下文回答轮、五种恢复任务×三窗口×两组=15组配对，均各一次，沿用原16段材料/rubric和同一orchestrated-v1/DeepSeek Flash，temperature=0、非thinking/JSON、8192输入/1024输出、32768 provider容量、每run12模型/120秒。模型按观察选工具，不能用接线脚本规定真实路径。

固定上下文最多400新模型请求，恢复最多300，合计700；这不是预计实际发送量，也不是700次全用完目标。相同任务可能涉及理解/调查/补读/回答，64个回答轮不等于64请求。达到任一phase上限立即停止该phase后续发送，失败/未运行保留，不追加预算、重测失败或自动新建session。

真实累计账本为tmp/evaluation-live-budget.json，开始时显式传原始used起点。当前只读为3289，若届时仍相同，则本批最大累计3989；起点变化必须核对其他使用，不覆盖旧计数。本批准备/测试只使用临时账本，没有修改真实账本或发送收费请求。freeze/check都不消费预算，execute必须用户授权本固定范围后运行。

## 共享计数与恢复

父进程持有现有全局.lock（与其他评测共用）；子进程通过短时hctx-mutex互斥预约同一个session。session绑定manifest hash、原起点、分phase上限与总上限，不允许重开会话重置。持久化used及phase计数后才允许_send；响应失败仍消耗预约。预约成功但实际发送前中断可能高估用量，保留并单列，不自动退计数。

同一输出路径绑定同一session。正常收口释放全局锁；进程突然退出遗留锁必须先确认所属进程已停止，不能自动删锁再运行。主进程的owner临时令牌仅进程环境传递，不写spec/报告或打印。父进程与子进程发送均计入共享账本；并行其他评测、起点/manifest/上限变化明确拒绝。

正式runtime逐轮保存已确定输入、deadline、body、状态、真实usage/估算标记及失败。已完成上下文前缀可复用，第二检查点继承本组实际状态；STARTED/未知模型或已有未收录job目录必须先源审，不自动重发。故障作业复用已验证的SupportJournal hook与真实os._exit，新child使用同一共享账本，不重置deadline/spend。旧脚本helper中的real_provider_requests=0占位在正式row移除，以真实记录和账本汇总。

## 来源与评分

上下文两组使用已接线的同一合成订单/签收事实、三条合成政策和生产BoundSources/小集合政策接口，不是本轮RAG评测。恢复申请题明确未发货，新增评测来源适配把其ORDER标为PAID、SHIPMENT/承运结论标为NOT_SHIPPED；其他任务沿用签收事实。该覆盖记录在新manifest，不修改旧接线源码/报告、Java或政策库。请求事实/陈述/政策仍分别记录，用户自述不能当权威结论。

源审模板包含64上下文检查点、30恢复任务的pass/result_correct、理由和证据，初始全null；仅从实际输出和原文标注，不以JSON合法/状态SUCCEEDED当业务正确。技术失败保留分母。上下文token统计完整模型输入，未知usage不填0，并展示双方通过配对；恢复未保存窗口UNKNOWN失败不能把0调用当节省。恢复质量通过且同任务完成才解释调用差，同时总15组与已保存窗口分列。Agent/RAG已冻结数字和原16.4%不改。

## 命令与产物

入口scripts/customer_harness_live_v1.py：freeze写新live-manifest.json（存在拒绝覆盖），check严格校验全部绑定文件；execute另需新输出目录、原expected-start、HCTX_TEST_DSN隔离测试PG及进程内RESOLVEFLOW_MODEL_API_KEY。不在命令参数或输出中放DSN/密钥。

```powershell
agent/.venv/Scripts/python.exe -m scripts.customer_harness_live_v1 freeze
agent/.venv/Scripts/python.exe -m scripts.customer_harness_live_v1 check
# 仅在固定范围授权后：
agent/.venv/Scripts/python.exe -m scripts.customer_harness_live_v1 execute --output reports/customer-harness-context-v1/live-v1 --expected-start 3289
```

使用既有独立65433测试PG及唯一t_hctx_ schema。正式结果完整导出run/call，成功完成后只删除自有schema；错误/预算停止时导出并保留该schema供核查，不清库或删卷。保留业务public哈希；与中断前不同则明确失败。凭据不进入版本库/报告，原4脏文件和冻结Agent/RAG/旧评测输入保持。
