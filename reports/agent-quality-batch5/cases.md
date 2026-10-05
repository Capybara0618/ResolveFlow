# 32例逐案核对（自动分数，非独立人审）

原始输入/Gold保持aligned-v2；完整请求与Observation在live-all.json。人审模板不填写执行者结论。

| 案例 | 类别 | 允许动作 | 最终动作 | 联合检查 | 终止 |
| --- | --- | --- | --- | --- | --- |
| A01A | unshipped | REFUND | REFUND | 通过 | COMPLETED |
| A01B | unshipped | REQUEST_INFO, MANUAL_REVIEW | 无终局 | 未通过 | CONTEXT_REQUIRED_OVERFLOW |
| A02A | unshipped | REFUND | REFUND | 通过 | COMPLETED |
| A02B | unshipped | REQUEST_INFO, MANUAL_REVIEW | 无终局 | 未通过 | CONTEXT_REQUIRED_OVERFLOW |
| A03A | unshipped | REFUND | REFUND | 通过 | COMPLETED |
| A03B | unshipped | REQUEST_INFO, MANUAL_REVIEW | REQUEST_INFO | 未通过 | COMPLETED |
| A04A | unshipped | REFUND | REFUND | 通过 | COMPLETED |
| A04B | unshipped | REQUEST_INFO, MANUAL_REVIEW | 无终局 | 未通过 | ACTION_REFUSED |
| A05A | lost | REFUND | 无终局 | 未通过 | CONTEXT_REQUIRED_OVERFLOW |
| A05B | lost | REQUEST_INFO, MANUAL_REVIEW | MANUAL_REVIEW | 通过 | COMPLETED |
| A06A | lost | REFUND | REFUND | 通过 | COMPLETED |
| A06B | lost | REQUEST_INFO, MANUAL_REVIEW | MANUAL_REVIEW | 通过 | COMPLETED |
| A07A | lost | REFUND | 无终局 | 未通过 | CONTEXT_REQUIRED_OVERFLOW |
| A07B | lost | REQUEST_INFO, MANUAL_REVIEW | MANUAL_REVIEW | 未通过 | COMPLETED |
| A08A | lost | REFUND | REFUND | 通过 | COMPLETED |
| A08B | lost | REQUEST_INFO, MANUAL_REVIEW | MANUAL_REVIEW | 通过 | COMPLETED |
| A09A | signed | REFUND | REFUND | 通过 | COMPLETED |
| A09B | signed | REQUEST_INFO, MANUAL_REVIEW | MANUAL_REVIEW | 通过 | COMPLETED |
| A10A | signed | REFUND | REFUND | 通过 | COMPLETED |
| A10B | signed | REQUEST_INFO, MANUAL_REVIEW | MANUAL_REVIEW | 通过 | COMPLETED |
| A11A | signed | REFUND | REFUND | 通过 | COMPLETED |
| A11B | signed | REQUEST_INFO, MANUAL_REVIEW | 无终局 | 未通过 | CONTEXT_REQUIRED_OVERFLOW |
| A12A | signed | REFUND | REFUND | 通过 | COMPLETED |
| A12B | signed | REQUEST_INFO, MANUAL_REVIEW | 无终局 | 未通过 | CONTEXT_REQUIRED_OVERFLOW |
| A13A | quality | REFUND | REFUND | 通过 | COMPLETED |
| A13B | quality | REQUEST_INFO, MANUAL_REVIEW | MANUAL_REVIEW | 通过 | COMPLETED |
| A14A | quality | REFUND | REFUND | 通过 | COMPLETED |
| A14B | quality | REQUEST_INFO, MANUAL_REVIEW | REQUEST_INFO | 通过 | COMPLETED |
| A15A | quality | REFUND | REFUND | 通过 | COMPLETED |
| A15B | quality | REQUEST_INFO, MANUAL_REVIEW | MANUAL_REVIEW | 通过 | COMPLETED |
| A16A | quality | REFUND | REFUND | 通过 | COMPLETED |
| A16B | quality | REQUEST_INFO, MANUAL_REVIEW | REQUEST_INFO | 未通过 | COMPLETED |
