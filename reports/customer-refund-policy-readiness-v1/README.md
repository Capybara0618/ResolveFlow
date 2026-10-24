# 履约退款准备的政策依据修复

2026-10-24，用户批准接续Agent质量与速度收口。本步只修政策就绪合同，规格见[开发说明](../../docs/customer-refund-policy-readiness-v1.md)。生产仍唯一AgentScope循环，不改RAG索引或退款执行。

## 问题、根因与实现

原真实S02/1把签收争议理解为APPLICATION/PREPARE_REFUND，needs含SHIPMENT但没有POLICY。旧程序在指南、订单及物流齐备后进入回答，未检索政策，因此不属于本次已观测到的召回失败。

`Orchestration.required`对活跃PREPARE_REFUND且needs含SHIPMENT的事项补POLICY；在就绪时计算，也覆盖后续REFINE_NEEDS。不改变模型选择物流相关性、工具顺序、Query及条款的职责。原POLICY引用门槛随之适用，回答合同和提示要求解释相关前提及核验条件；政策未读取不能结束，不可重试来源失败才受阻，不生成申请摘要。纯入口、物流查询、独立人工及取消/暂停/结束不被强制检索政策。

## 实际验证

| 验证 | 结果与命令 | 证据 |
| --- | --- | --- |
| 失败先行 | 新14例8失败/6通过，原S02/1被旧实现直接发布 | [red.txt](red.txt) |
| 针对回归 | 新14例及编排/SDK/目标核对48通过；首次两条旧脚本尚未补政策，保留失败记录 | [targeted.txt](targeted.txt)、[最终48项](targeted-final.txt) |
| 全部客服单元/契约 | `pytest agent/tests/unit/test_support*.py`及两个support合同文件，482通过0跳过 | [unit.txt](unit.txt) |
| 真PG恢复/SDK/API/流式 | `test_support_refund_policy_runtime.py`、`test_support_goal_review_runtime.py`、`test_support_orchestrated_runtime.py`、`test_support_summary_grounding_runtime.py`、`test_support_stream_runtime.py`，10通过0跳过 | [首轮旧脚本失败](runtime.txt)、[最终结果](runtime-final.txt) |
| 静态 | 两生产源码strict mypy、两源码与五测试Ruff；首次新增测试导入排序已修正 | [static.txt](static.txt) |

原S02/1决定/文本原样放入SDK，新的POLICY缺口阻止发布和候选流式泄出；没有改原真实结果文件或分母。随后显式脚本选政策、带引用解释后可以完成。PG两分支覆盖政策可用/不可用，原模型决定及缺口落库，过期租约重取后0新模型/工具发送、预算和结果保持。旧测试仅补足新增政策读取/引用与计数，不删除原金额、状态、流式、manifest和恢复断言。

本步无真实供应商请求，usage2349保持。TokenizedScript的live模式用于严格发布校验，不能称真实模型已改善。没有Java/网页/全仓构建或新的RAG排序测量。PG只写测试独占schema，公共表基线与上批结束完全一致，最终[保护审计](audit.json)核对旧业务/索引、188历史报告及四历史脏文件。

## 边界与接续

这一步保证已识别为履约退款准备的事项取得政策并引用；不能证明模型不会漏识别物流，也不能用引用存在代替语义完整性。实际解释质量仍待新版本有限验收。接下来分析已有网页的串行请求关键路径，保留必要政策依据，优先研究由模型显式选择的独立只读合并；不以离线脚本吞吐冒充真实耗时收益。
