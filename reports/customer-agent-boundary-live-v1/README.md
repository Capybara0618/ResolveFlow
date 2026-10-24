# 客服共同边界：六条真实模型验收

2026-10-24，用户批准有限真实确认。业务基线7bce02d，[验收协议](../../docs/customer-agent-boundary-live-v1.md)、[六条输入与判据](../../evals/customer-agent-boundary-live-v1/scenarios.json)、[冻结清单](../../evals/customer-agent-boundary-live-v1/manifest.json)。当前进度只见tasks/todo.md顶部。

复用现有流式模型、运行存储和评测器，独立新运行；本批全部真实模型请求总上限24，每轮一次，失败保留、不自动续测。业务HTTP是原标明的合成快照，政策读取原PG索引；不创建Case、人工单、退款或正常业务会话。

准备：新驱动2单元通过（固定6条/Gold不入请求/原快照不改/请求上限在发送前），Ruff两文件通过；初次3项导入分组诊断自动整理后通过。`freeze`与`check`完成，后者核对原精确generation和11公共表前后相同，[预检](preflight.json)为0新模型。进程环境原无模型key，但用户环境已配置，执行时仅在进程内读取该既有变量，不写配置或日志。

准备文件精确提交普通push核实后，执行`python scripts/accept_support_boundary_live_v1.py execute`一次。逐条结果及源审随后追加，不能以准备通过提前宣称真实效果成功。
