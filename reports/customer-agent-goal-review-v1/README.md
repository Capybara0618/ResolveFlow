# 错误目标不再强制改写正确产物

2026-10-24，基线b91cacb，修复[原M02/2](../customer-agent-close-v1/README.md)的目标锁死问题。实现及成本边界见[规格](../../docs/customer-agent-goal-review-v1.md)，原失败数据保持。

## 工程验证

- [初始失败](red.txt)：新建五项边界测试先失败；当时尚无REVIEW_GOAL协议及冲突返回入口。
- [阶段性针对回归](targeted.txt)：34项通过。之后增加流式断言，发现新测试误把两个不同attempt的reset当一次；按真实投影合同校正为model-4撤回、model-5切换。没有修改生产流式组件来迁就测试。
- [最终扩大单元/契约](unit.txt)：450通过，0跳过；命令为全部`agent/tests/unit/test_support*.py`加`test_contracts_support.py`、`test_contracts_support_refund.py`，`pytest -q --tb=short`。新测试中原M02/2三个决定及最终正确摘要均原样复用；脚本核对与真实模型调用分开，不把重放称为新模型成功。
- [PG/API/SSE/恢复](runtime.txt)：19通过，0跳过；运行`test_support_goal_review_runtime.py`、`test_support_orchestrated_runtime.py`、`test_support_staged_api.py`、`test_support_stream_runtime.py`及`test_support_store.py`。使用所属PG端口55433；核对后5模型/2工具journal可恢复，恢复0新发送，原事件只应用一次。
- [静态检查](static.txt)：四生产文件strict mypy及四生产文件/两新测试Ruff通过。未运行Java/Web、全仓测试或简历量化；Starlette的既有DeprecationWarning保留。

## 实际变化与限制

程序不判断人工和退款哪个语义一定正确；只检测候选产物与目标合同冲突，并让同一个模型受控核对一次。它可更正，也可确认原目标，随后重新检查证据。事项、记忆和预算保留，冲突不再伪装成字段遗漏反馈。

本工程步0新模型请求，账本2318。下一独立小步固定3组4轮、最多20实际请求；冻结后执行一次并逐轮源审。只有真实记录能说明当前模型是否使用核对、回答是否完整及额外延迟，不能用450项单元通过代替客服质量。
