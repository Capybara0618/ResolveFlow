# 新编排独立对话与确认建单验收

2026-10-24，按docs/customer-agent-orchestration-acceptance-v1.md及用户授权执行。原默认staged-v1，新候选orchestrated-v1及RAG/模型/预算保持。五新合成329元LOST订单，四组6消息和主链1消息，主链最多初始Case调查1run；不审批/退款，不自动重发失败题。

## 准备

新增accept_support_adoption_v1.py、controls/primary两个CJS驱动，复用现有账户/购物/发货/物流场景/会话/原始计量。primary复用原完整网页确认逻辑，独立新目录，旧脚本/失败保持。四组逐组保存状态/内存/来源/草稿/前端事件；机械检查后还有Codex逐条源审，SUCCEEDED不等于语义通过。

实际命令：Python Ruff/py_compile、两CJS node --check通过；prepare已创建policy/correction/pause/human/primary五单与会话，provider_requests0、全局账本2108。准备期间核对票据API以ticket_id读取，脚本import排序已修正；执行前统一冻结最终脚本hash，尚未执行或重写任何真实结果。source_files/15保护文件SHA及固定输入见plan.json。

先精确commit普通push核实，再无在途时显式启用候选、controls仅一次；保存所有请求费用并源审，通过后primary仅一次。所有功能/语义及工程无新增回归后才切日常默认。结果/失败/未运行和下一步集中更新本报告，当前唯一进度仍在tasks/todo.md顶部。
