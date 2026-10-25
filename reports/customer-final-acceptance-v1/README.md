# 当前客服架构有限收口验收

2026-10-25。按用户授权冻结当前架构，新增开发可见合成3组11轮，只执行一次，每批最多40真实供应商请求，不用追加题或更换措辞补分。

- [规格](../../docs/customer-final-acceptance-v1.md)、[固定输入与逐轮判据](../../evals/customer-final-acceptance-v1/scenarios.json)、[冻结manifest](../../evals/customer-final-acceptance-v1/manifest.json)。
- 准备验证：`python -m pytest agent/tests/unit/test_customer_final_driver.py agent/tests/unit/test_customer_current_eval.py -q`，7通过；新驱动及测试Ruff通过。
- `python -m scripts.accept_customer_final_v1 freeze`及`check`通过；[预检](preflight.json)确认原PG/政策/索引可用，尚无新模型请求，ledger起点2381。
- 真实模型、实际接受状态、PG临时schema、真实只读政策RAG；订单/物流HTTP事实为受主体约束的冻结响应。本批不重新验收Java/UI，不提交申请或共享核查。

准备提交推送核实后执行`python -m scripts.accept_customer_final_v1 execute`。全部11轮保留，分别报告发布状态、业务完整与次要体验问题，不把成功返回当语义正确。结果在本报告追加，不更新简历原文。
