# Harness/上下文计量与故障接线

2026-10-26，接续[原评测协议](customer-harness-context-v1.md)。本批不修改已冻结16段材料、rubric、生产源码或原准备报告，当前进度仅tasks/todo.md顶部。本文件限定接线与验证方式，不替代正式模型结果。

## 模型与上下文

[MeasuredModel](../scripts/evaluation/customer_harness_measurement_v1.py)继承生产StreamingLiveModelClient，保留实际provider body、上限、SSE解析、served model及usage；在_send前检查发送上限、记录预约和持久化。实际发送失败仍计数；usage缺失保留UNKNOWN/估算，汇总已知部分与未知数量，不把缺失写0。记录不含HTTP头/凭据。请求日志写入失败时不继续发送，复用现有有界Windows写重试。

两组都由SupportRuntime/SupportStore持久化；raw只替换为已冻结RawHistoryAgent，SDK循环、阶段、预算、检查保持。evaluation标签绑定variant及计量源码hash，完成run返回原结果，不重新调用模型。新适配额外拒绝foreign conversation_update，再调用原准备阶段的请求组装；不改旧准备文件迁就新接线。

当前CLI仅offline，强制MockTransport，不读真实模型密钥，不开放收费execute。类本身可接实际provider供后续有界运行，但真实入口还需共享账本锁、明确起点/上限、正式manifest/逐轮结果恢复及源审汇总，不能因为已有Streaming客户端就称正式评测就绪。

上下文样本中的订单/物流/历史沿生产BoundSources、HTTP MockTransport和相同合成快照提供；仅GET绑定本run的current/order/shipment/history，未知身份拒绝。三条政策明确标记合成，两个组完全相同，走生产small_context接口，非本次RAG效果评测，也没有变更商城政策。检索索引由本地合成适配提供，不假称PG真实政策查询。真实模型对照前需再次固定这些来源与适用范围。

64轮offline矩阵用固定脚本理解和回答经真实HTTP/SSE客户端执行；脚本usage是显式构造的100输入/30输出，仅用于核对解析/累计，不能称真实token成本或压缩收益。保存每次实际body和PG原始调用，语义评分保持null。

## 进程与恢复

[进程驱动](../scripts/evaluation/customer_harness_crash_v1.py)只接受t_hctx_开头的隔离schema与MOCK_SSE。两独立子进程执行prefix/post，真实os._exit(73)，现有SupportJournal.complete前后注入；新进程不重置原manifest、deadline或已消费预算。从头组使用新run并继承原spend/绝对deadline，旧记录保留。仅使自有故障run租约过期，恢复fence递增，旧持有者操作必须STALE_FENCE。

工具故障按每题business_fault_source命中ORDER/SHIPMENT/POLICY，排除自动GUIDE。无模型落库窗口保留STARTED并验证UNKNOWN_MODEL_RESULT与0新发送，是明确失败/停止合同，不把少请求当有效恢复。已保存模型/工具窗口则应复用原结果。故障前后完整run/call记录与消费情况导出到各job审计后，调用者才可清理本次新建schema；不删除数据库或卷。

offline脚本统一读取三类业务来源是为了确保所有故障位置可达，只验证恢复接线；真实模型仍需自主选择工具。脚本完成不证明五类业务回答正确、也不证明真实模型一定到达目标窗口。正式若未到达必须保留为FAULT_NOT_REACHED，不替换任务补分。

## 本批验证入口

先设置PYTHONPATH至仓库/agent/src/agent、PYTHONIOENCODING=utf-8，并将RESOLVEFLOW_AGENT_DB指向既有独立65433测试PG；业务55433不动。仅创建唯一t_hctx_临时schema，迁移/执行/导出/删除都限定该schema。

```powershell
agent/.venv/Scripts/python.exe -m pytest agent/tests/unit/test_customer_harness_measurement_v1.py agent/tests/integration/test_customer_harness_measurement_v1.py -q
agent/.venv/Scripts/python.exe -m ruff check scripts/evaluation/customer_harness_measurement_v1.py scripts/evaluation/customer_harness_crash_v1.py agent/tests/unit/test_customer_harness_measurement_v1.py agent/tests/integration/test_customer_harness_measurement_v1.py
agent/.venv/Scripts/python.exe -m scripts.evaluation.customer_harness_context_v1 check
```

测试包含实际请求/PG记录一致、同run完成结果复用0新发送、三类真实进程退出及旧fence拒绝、未知窗口明确失败、从头组预算/deadline继承。下一步在新manifest下集中执行64上下文/30故障前缀矩阵，逐行核对而非只看汇总；原报告/源码hash保留。
