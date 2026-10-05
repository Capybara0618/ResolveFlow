# 评测记录

模式：mock；数据：resolveflow-evaluation-v1；来源：合成；Gold未经独立人审。

代码：c9160d1ca68fe64be3f9e15fefa28f85b8ae0da2；数据清单hash：1a430eacd39d6f64b303e63bcfd2654f0b8686382191a968ff2a9869f649d359。

自动联合达标：0/32；动作匹配：0/32；未完成：32；调用：92。

脚本模型只测试接线；自动评分不代替提问相关性、解释可信度的人审。

完整配对：16；两成员均达标：0；单成员不计配对分。

终止原因：{"CONTEXT_REQUIRED_OVERFLOW": 32}

| 案例 | 分组 | 动作 | 联合达标 | 失败/缺口 |
| --- | --- | --- | --- | --- |
| A01A | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A01B | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A02A | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A02B | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A03A | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A03B | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A04A | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A04B | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A05A | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A05B | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A06A | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A06B | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A07A | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A07B | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A08A | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A08B | dev | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A09A | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A09B | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A10A | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A10B | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A11A | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A11B | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A12A | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A12B | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A13A | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A13B | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A14A | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A14B | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A15A | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A15B | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A16A | test | — | False | CONTEXT_REQUIRED_OVERFLOW |
| A16B | test | — | False | CONTEXT_REQUIRED_OVERFLOW |

案例耗时：median 4591.75 ms，p95 4969.88 ms（含本机执行开销）。

逐轮显式动作、工具Observation、原始请求和usage见对应JSON；不保存隐式思维链。
