# 评测记录

模式：live；数据：resolveflow-evaluation-calibrated-v3；来源：合成；Gold未经独立人审。

代码：103aabe4bf468f970b475ab92306620c2dd7a19e；数据清单hash：087f709b3dbf764daec9c4eb25bc00059c012e4a44326557d3b8e8a2713e82de。

自动联合达标：31/32；动作匹配：31/32；未完成：1；调用：158。

脚本模型只测试接线；自动评分不代替提问相关性、解释可信度的人审。

provider准确usage：158/158次；输入273381、输出18588 tokens。未知计费不计为零。

完整配对：16；两成员均达标：15；单成员不计配对分。

终止原因：{"COMPLETED": 31, "MISSING_EVIDENCE_ON_REFUND": 1}

| 案例 | 分组 | 动作 | 联合达标 | 失败/缺口 |
| --- | --- | --- | --- | --- |
| A01A | dev | REFUND | True | — |
| A01B | dev | MANUAL_REVIEW | True | — |
| A02A | dev | REFUND | True | — |
| A02B | dev | MANUAL_REVIEW | True | — |
| A03A | dev | REFUND | True | — |
| A03B | dev | — | False | MISSING_EVIDENCE_ON_REFUND |
| A04A | dev | REFUND | True | — |
| A04B | dev | REQUEST_INFO | True | — |
| A05A | dev | REFUND | True | — |
| A05B | dev | MANUAL_REVIEW | True | — |
| A06A | dev | REFUND | True | — |
| A06B | dev | MANUAL_REVIEW | True | — |
| A07A | dev | REFUND | True | — |
| A07B | dev | MANUAL_REVIEW | True | — |
| A08A | dev | REFUND | True | — |
| A08B | dev | MANUAL_REVIEW | True | — |
| A09A | test | REFUND | True | — |
| A09B | test | MANUAL_REVIEW | True | — |
| A10A | test | REFUND | True | — |
| A10B | test | MANUAL_REVIEW | True | — |
| A11A | test | REFUND | True | — |
| A11B | test | MANUAL_REVIEW | True | — |
| A12A | test | REFUND | True | — |
| A12B | test | MANUAL_REVIEW | True | — |
| A13A | test | REFUND | True | — |
| A13B | test | MANUAL_REVIEW | True | — |
| A14A | test | REFUND | True | — |
| A14B | test | MANUAL_REVIEW | True | — |
| A15A | test | REFUND | True | — |
| A15B | test | MANUAL_REVIEW | True | — |
| A16A | test | REFUND | True | — |
| A16B | test | MANUAL_REVIEW | True | — |

案例耗时：median 13972.87 ms，p95 15618.09 ms（含本机执行开销）。

逐轮显式动作、工具Observation、原始请求和usage见对应JSON；不保存隐式思维链。
