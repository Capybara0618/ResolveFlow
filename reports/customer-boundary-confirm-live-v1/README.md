# 两处状态/引用边界修复真实确认

2026-10-25，工程bffe5cd普通push核实后，冻结原固定3组11轮输入与逐轮判据，新源码/权重及40请求上限，见[manifest](../../evals/customer-boundary-confirm-live-v1/manifest.json)。这是原题修复确认，不是独立盲测；原报告/失败保留。模型参数、RAG、每run预算/修正次数沿用，不追加题、不收费重跑补分。

`python -m scripts.confirm_customer_boundary_v1 freeze`、`check`完成后提交推送，随后`execute`仅一次。只启动原PG，真实DeepSeek+PG+本店只读政策，订单/物流为合成冻结HTTP；无新Java/UI/退款写链路。准备起点ledger2410、0新模型，原public及旧报告保持。
