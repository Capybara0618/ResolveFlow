# 独立 Workflow 对照的执行入口

2026-10-25，准备已完成，正式新对照尚未运行。实现a941206，冻结142个源码/资产文件，32场景×两组×一次，共64会话/100客户轮；24复杂与8普通分别报告。保持原输入与快照，评分检查对外正确性、完成性、上下文，不要求Workflow输出Agent内部状态。

在E:\Code\Agent+Backend，沿用agent/.venv和原PG55433/原政策卷；模型凭据只通过已有环境变量提供，不能放命令、报告或Git。以下路径均为仓库相对路径，Python可用agent/.venv/Scripts/python.exe代替。

```powershell
$env:PYTHONPATH="$PWD;$PWD/agent/src"
agent/.venv/Scripts/python.exe -m scripts.customer_workflow_comparison_live check
```

check验证[执行manifest](../../evals/customer-workflow-comparison-v2/execution-manifest.json)的源码/参数/输入，以及原PG两组政策原文/指南一致；不调用生成模型。实际[冻结预检](frozen-preflight.json)和[最终保留审计](final-preparation-audit.json)已通过。不要再次freeze覆盖现有manifest；若实现有意变化，应另立版本而非改旧结果。

正式执行命令如下，400是拟议的新请求上限，尚未在本轮启动或消费；需用户安排正式测量后使用。正常预估约250请求不构成保证。

```powershell
agent/.venv/Scripts/python.exe -m scripts.customer_workflow_comparison_live execute --live --max-provider-requests 400 --output reports/customer-workflow-comparison-v2/agent-runtime.json
```

输出必须新文件；两组实际共享这一全局上限，不各拿400。额度或中断不自动补跑；已发送失败、格式修正也保留，额度前拦截单列，未运行填NOT_RUN仍在分母。每轮原始记录在忽略的tmp/customer-workflow-comparison-v2/自有schema目录持续保存，正常或异常结束尽力导出实际run/call后清理自有schema；导出失败保留库供核查，不清public。正式文件不存在前不能运行后续源审命令。

```powershell
agent/.venv/Scripts/python.exe -m scripts.customer_workflow_comparison_prepare review-template --runtime reports/customer-workflow-comparison-v2/agent-runtime.json --output reports/customer-workflow-comparison-v2/source-review.json
```

逐轮读取实际请求、回答、草稿和原始来源，填写correctness/completion/context三个布尔项和evidence。模板内业务判据只供源审，不进入模型。技术发布成功不等于业务成功；明确要草稿但没实际草稿不能通过；NOT_RUN/技术失败也需记录原因并判未完成。该审查由Codex完成、非独立人工盲审，来源可见合成集边界保留。

```powershell
agent/.venv/Scripts/python.exe -m scripts.customer_workflow_comparison_prepare summarize --runtime reports/customer-workflow-comparison-v2/agent-runtime.json --review reports/customer-workflow-comparison-v2/source-review.json --output reports/customer-workflow-comparison-v2/agent-summary.json
```

汇总绑定runtime/review字节hash；主指标复杂场景完整率及百分点差，普通/总体另列。辅助真实模型请求/token、业务HTTP、服务端保留首正文/最终P50/P95与样本数，全量与双方都完整完成的配对成本分开。不能将桩测56通过写成客服成功率，也不预先保证Agent每项获胜。旧正式Agent负向结果和RAG40问600检索保持，新对照不自动重测RAG或修改简历。
